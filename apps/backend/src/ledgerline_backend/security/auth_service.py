"""Authentication service.

Encapsulates the auth use-cases — register, login, refresh, logout — over the
User / UserCredential / RefreshToken models. Pure-ish: it takes a Session and
Settings and performs no I/O beyond the database, which keeps it testable.

Security properties enforced here:
  * passwords stored only as Argon2id hashes;
  * generic failure for bad-credentials (no user-enumeration via error text);
  * temporary lockout after N failed attempts;
  * refresh-token rotation — issuing a new token revokes the presented one;
  * revoked/expired refresh tokens are rejected.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import CursorResult, delete, or_, select
from sqlalchemy.orm import Session

from ledgerline_backend.config import Settings
from ledgerline_backend.models import Organisation, RefreshToken, User, UserCredential
from ledgerline_backend.security import passwords, tokens
from ledgerline_backend.util.time import utcnow


class AuthError(Exception):
    """Base class for authentication failures."""


class InvalidCredentialsError(AuthError):
    """Wrong email/password, or unknown user. Deliberately non-specific."""


class AccountLockedError(AuthError):
    """The account is temporarily locked due to failed attempts."""


class AccountInactiveError(AuthError):
    """The account is not in a state that permits login."""


class InvalidRefreshTokenError(AuthError):
    """The presented refresh token is unknown, expired, or revoked."""


class UnknownOrganisationError(AuthError):
    """Registration referenced an organisation that does not exist."""


class DuplicateEmailError(AuthError):
    """Registration used an email that already exists."""


@dataclass(frozen=True)
class TokenPair:
    """An issued access token (JWT) and its companion refresh token (opaque)."""

    access_token: str
    refresh_token: str
    expires_in: int
    # True when the authenticated account is flagged for multi-factor auth. The
    # second-factor challenge itself is implemented in F-08; this reports the
    # account's MFA state so clients can branch correctly once it lands.
    mfa_required: bool = False


# Backwards-compatible alias for the shared helper.
_utcnow = utcnow


def _as_utc(value: dt.datetime) -> dt.datetime:
    """Coerce a possibly-naive datetime (e.g. read back from SQLite, which does
    not preserve tzinfo) to a UTC-aware datetime so comparisons are valid."""
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.UTC)
    return value


class AuthService:
    """Authentication use-cases bound to a session and settings."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self._session = session
        self._settings = settings

    # -- registration -----------------------------------------------------

    def register(
        self,
        *,
        org_id: uuid.UUID,
        email: str,
        display_name: str,
        password: str,
    ) -> User:
        """Create a new active user with credentials.

        The organisation must already exist (a user cannot be attached to an
        arbitrary or non-existent tenant), and the email must be unique.
        """
        normalized = email.strip().lower()

        organisation = self._session.get(Organisation, org_id)
        if organisation is None:
            raise UnknownOrganisationError

        existing = self._session.scalar(select(User).where(User.email == normalized))
        if existing is not None:
            raise DuplicateEmailError

        user = User(
            org_id=org_id,
            email=normalized,
            display_name=display_name,
            status="active",
        )
        self._session.add(user)
        self._session.flush()  # assign user.id

        credential = UserCredential(
            user_id=user.id,
            password_hash=passwords.hash_password(password),
        )
        self._session.add(credential)
        self._session.flush()
        return user

    # -- login ------------------------------------------------------------

    def login(self, *, email: str, password: str, now: dt.datetime | None = None) -> TokenPair:
        """Authenticate and issue a token pair, applying lockout policy."""
        moment = now or _utcnow()
        normalized = email.strip().lower()
        user = self._session.scalar(select(User).where(User.email == normalized))
        credential = (
            self._session.scalar(
                select(UserCredential).where(UserCredential.user_id == user.id)
            )
            if user is not None
            else None
        )

        if user is None or credential is None:
            # Run a dummy verify to keep timing similar regardless of existence.
            passwords.verify_password(password, _DUMMY_HASH)
            raise InvalidCredentialsError

        if credential.locked_until is not None and _as_utc(credential.locked_until) > moment:
            raise AccountLockedError

        if user.status != "active":
            raise AccountInactiveError

        if not passwords.verify_password(password, credential.password_hash):
            self._register_failure(credential, moment)
            # Persist the failure counter / lockout BEFORE raising, otherwise the
            # request-scoped session rolls back and brute-force throttling is lost.
            self._session.commit()
            raise InvalidCredentialsError

        # Success: reset failure state and (optionally) upgrade the hash.
        credential.failed_attempts = 0
        credential.locked_until = None
        if passwords.needs_rehash(credential.password_hash):
            credential.password_hash = passwords.hash_password(password)

        return self._issue_pair(user.id, moment, mfa_required=user.mfa_enabled)

    def _register_failure(self, credential: UserCredential, moment: dt.datetime) -> None:
        credential.failed_attempts += 1
        if credential.failed_attempts >= self._settings.max_failed_logins:
            credential.locked_until = moment + dt.timedelta(
                seconds=self._settings.lockout_seconds
            )

    # -- refresh / logout -------------------------------------------------

    def refresh(self, *, refresh_token: str, now: dt.datetime | None = None) -> TokenPair:
        """Rotate a refresh token: validate, revoke it, and issue a new pair."""
        moment = now or _utcnow()
        token_hash = tokens.hash_refresh_token(refresh_token)
        row = self._session.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        if row is None or row.revoked or _as_utc(row.expires_at) <= moment:
            raise InvalidRefreshTokenError

        row.revoked = True
        new_pair = self._issue_pair(row.user_id, moment)
        # Link the old token to its replacement for audit.
        replacement = self._session.scalar(
            select(RefreshToken).where(
                RefreshToken.token_hash == tokens.hash_refresh_token(new_pair.refresh_token)
            )
        )
        if replacement is not None:
            row.replaced_by_id = replacement.id
        return new_pair

    def logout(self, *, refresh_token: str) -> None:
        """Revoke a refresh token so it can no longer be used."""
        token_hash = tokens.hash_refresh_token(refresh_token)
        row = self._session.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        if row is not None:
            row.revoked = True

    # -- maintenance ------------------------------------------------------

    def prune_refresh_tokens(self, *, now: dt.datetime | None = None) -> int:
        """Delete refresh tokens that are expired or revoked.

        Intended to be run periodically (a scheduled job) so the table does not
        grow unbounded. Returns the number of rows deleted.
        """
        moment = now or _utcnow()
        result = cast(
            "CursorResult[Any]",
            self._session.execute(
                delete(RefreshToken).where(
                    or_(
                        RefreshToken.revoked.is_(True),
                        RefreshToken.expires_at <= moment,
                    )
                )
            ),
        )
        return result.rowcount

    # -- helpers ----------------------------------------------------------

    def _issue_pair(
        self, user_id: uuid.UUID, moment: dt.datetime, *, mfa_required: bool = False
    ) -> TokenPair:
        access = tokens.create_access_token(self._settings, user_id, now=moment)
        raw_refresh = tokens.generate_refresh_token()
        self._session.add(
            RefreshToken(
                user_id=user_id,
                token_hash=tokens.hash_refresh_token(raw_refresh),
                expires_at=tokens.refresh_token_expiry(self._settings, now=moment),
            )
        )
        self._session.flush()
        return TokenPair(
            access_token=access,
            refresh_token=raw_refresh,
            expires_in=self._settings.access_token_ttl_seconds,
            mfa_required=mfa_required,
        )


# A precomputed hash of a random value, used to equalise timing on unknown users.
_DUMMY_HASH = passwords.hash_password("x" * 16)

# Sync Protocol

## Overview

This document defines the offline-first synchronization protocol for the desktop client and backend.

## Push/Pull flow

- Push: desktop batches local `SyncEvent` records and posts them to `/api/sync/push`
- Pull: desktop requests server changes from `/api/sync/pull?cursor={cursor}`

## Event semantics

- All domain writes are represented as events
- Events are idempotent by `eventId`
- Events include `baseVersion` to detect concurrent edits

## Conflict handling

- The server returns `conflict` for version mismatch or posted-record edits
- Conflicts are stored locally with `sync_conflicts`
- Resolution is manual for financial entities

## Tokens and state

- Client stores `lastPulledCursor` and `lastPushedCursor`
- Each sync response includes a new `cursor`
- Device registration uses secure device credentials

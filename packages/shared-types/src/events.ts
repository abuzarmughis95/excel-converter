/**
 * Canonical sync-event envelope contract.
 *
 * Every domain write is represented as an immutable, ordered event. Events are
 * the system of record; relational rows (Postgres / SQLite) are projections of
 * the event stream. This module defines the wire/storage shape of an event so
 * the TypeScript sync client and the Python server agree byte-for-byte.
 *
 * NOTE: this is a type contract only. Hashing, signing, and HLC mechanics are
 * implemented in later tickets (Phase 3) against this shape.
 */

import type { EventId, Uuid, CompanyId, UserId } from './ids.js';

/** Hybrid Logical Clock — orders events causally without trusting wall clocks. */
export interface Hlc {
  /** Physical time component, milliseconds since Unix epoch. */
  readonly wall: number;
  /** Logical counter, incremented when wall time does not advance. */
  readonly counter: number;
  /** Originating device's globally-unique node id (server reserves 0). */
  readonly nodeId: number;
}

/** Aggregate types an event may target. Extended as modules land. */
export type AggregateType =
  | 'account'
  | 'period'
  | 'journal'
  | 'bank_account'
  | 'reconciliation'
  | 'customer'
  | 'supplier'
  | 'invoice'
  | 'bill'
  | 'vat_return'
  | 'spreadsheet_workbook'
  | 'ixbrl_file'
  | 'document';

/**
 * The immutable event envelope.
 *
 * `payload` is serialized canonically (sorted keys, fixed number formatting)
 * for reproducible hashing across hosts. `thisHash` chains to `prevHash` per
 * aggregate, giving a tamper-evident per-entity history. `serverSeq` is absent
 * until the server accepts and assigns a monotonic global sequence.
 */
export interface EventEnvelope<TPayload = Readonly<Record<string, unknown>>> {
  readonly eventId: EventId;
  readonly aggregateType: AggregateType;
  readonly aggregateId: Uuid;
  readonly eventType: string;
  /** Schema version of `payload`, enabling upcasting of historical events. */
  readonly eventVersion: number;
  readonly payload: TPayload;
  readonly hlc: Hlc;
  readonly actorUserId: UserId;
  readonly companyId: CompanyId;
  /** The command/event that caused this one (provenance). */
  readonly causationId?: EventId;
  /** Groups events emitted atomically by one logical operation. */
  readonly correlationId?: Uuid;
  /** Aggregate version this event assumes — drives conflict detection. */
  readonly baseVersion?: number;
  /** Hex-encoded hash of the previous event for this aggregate. */
  readonly prevHash: string;
  /** Hex-encoded hash of this event (chain link + integrity). */
  readonly thisHash: string;
  /** Device signature over `thisHash`. */
  readonly signature: string;
  /** Server-assigned monotonic global sequence; absent until accepted. */
  readonly serverSeq?: number;
  /** ISO-8601 UTC timestamp the event was created on its origin host. */
  readonly createdAt: string;
}

/** Per-event result returned by the server during push. */
export type EventAck =
  | { readonly eventId: EventId; readonly status: 'accepted'; readonly serverSeq: number }
  | { readonly eventId: EventId; readonly status: 'conflict'; readonly serverEvent: EventEnvelope }
  | { readonly eventId: EventId; readonly status: 'rejected'; readonly reason: string };

/** Request body for POST /v1/sync/push. */
export interface SyncPushRequest {
  readonly deviceId: Uuid;
  readonly companyId: CompanyId;
  readonly baseServerSeq: number;
  readonly events: readonly EventEnvelope[];
}

/** Response body for POST /v1/sync/push. */
export interface SyncPushResponse {
  readonly results: readonly EventAck[];
  readonly newServerSeq: number;
}

/** Response body for GET /v1/sync/pull. */
export interface SyncPullResponse {
  readonly events: readonly EventEnvelope[];
  readonly serverSeq: number;
  readonly hasMore: boolean;
}

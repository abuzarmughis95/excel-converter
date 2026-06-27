# Event Contracts

## SyncEvent

- `eventId`: UUID
- `companyId`: UUID
- `deviceId`: UUID
- `entityType`: string
- `entityId`: UUID
- `eventType`: string
- `payload`: JSON object
- `metadata`: object including `createdAt`, `baseVersion`, `localVersion`, `source`

## Common event types

- `create_journal_entry`
- `update_journal_entry`
- `post_journal_entry`
- `create_invoice`
- `update_invoice`
- `submit_vat_return`

## Response contract

- `eventId`
- `status`: `accepted | rejected | conflict`
- `serverVersion`
- `errors?`
- `conflictPayload?`

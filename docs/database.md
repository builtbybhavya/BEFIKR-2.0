# Database design

## Development database

The local app creates SQLite tables automatically in `backend/data/befikr.db`. Foreign keys and WAL mode are enabled. Tables cover users, revocable sessions, preferences, consent events, contacts, private reports, moderation history, appeals, SOS event records, tracking sessions, Tap Me journeys/events, managed places, and audit logs. SQLite is for local evaluation; `CREATE TABLE IF NOT EXISTS` is not a production migration system.

## Production schema

`database/postgresql/001_initial_schema.sql` is a PostgreSQL/PostGIS schema reference. It defines UUID keys, foreign keys, timestamp columns, geographical types, indexes, separation of private reports from aggregate safety cells, and data entities requested in the build brief. It is not currently applied by the FastAPI runtime.

Key relationships:

- A user owns contacts, reports, SOS events, tracked journeys, check-in journeys and preferences.
- A report has a private owner, zero or more evidence records, a moderation history and appeals.
- Aggregated safety cells are derived from validated reports and carry their own coverage, confidence and refresh timestamp; no reporter identity belongs in this table.
- Route sessions own alternatives and segment scores.
- SOS events own recipient and delivery state records, separate from the event itself.
- Tracking sessions own consented recipient grants and time-limited location updates.
- Admin actions reference role/actor and write append-only audit entries.
- Safe Spot entries retain source and verification timestamps.

## Retention defaults to decide before launch

This development build does not run scheduled deletion jobs. Before real operation, set policy for account/session expiry, exact tracking-point deletion, SOS event retention, rejected-report and appeal retention, evidence retention, aggregate aging, audit retention and backups. Removing a user from the SQLite database cascades related user-owned rows; backups and offline browser drafts require separate deletion policies.

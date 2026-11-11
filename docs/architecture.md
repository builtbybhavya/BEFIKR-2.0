# Technical architecture

## Current executable architecture

The initial deliverable is a same-origin PWA served by FastAPI. The backend is a modular monolith with a local SQLite store; no external runtime dependency is needed in the browser. Static PWA resources can be cached, but authenticated API calls require the server. The API and PWA share an origin to keep local setup simple.

```text
Mobile / desktop browser
  ├─ PWA shell, accessible responsive UI, local unsent draft queue
  ├─ browser speech synthesis (device-dependent)
  └─ HTTPS/localhost API calls
       └─ FastAPI modular monolith
            ├─ auth + profile + consent
            ├─ private RAAZ + moderation + appeal + audit
            ├─ Raahi risk + privacy-gated report aggregation
            ├─ contacts + SOS records + Track Me + Tap Me
            ├─ Safe Spot managed directory + on-demand OpenStreetMap Overpass lookup
            └─ SQLite development database
```

## Production target

The target described in the product brief is Flutter/Dart with local SQLite, FastAPI, PostgreSQL/PostGIS, a React/Next admin, FCM/SMS adapters, and Google Routes/Places or Mapbox adapters. This checkout does not pretend those adapters are live. The browser UI includes the consumer and admin surfaces in one PWA. `database/postgresql/001_initial_schema.sql` describes the target data model, but the API currently runs only on SQLite and does not load that schema.

## Service boundaries

- **Authentication:** PBKDF2-SHA256 password hashing, HMAC-signed expiring tokens, stored session IDs and logout revocation. The signing secret must be overridden outside local development.
- **RAAZ:** user-scoped report queries and submissions; separate moderation history and appeal records; admin/moderator role check.
- **Aggregation:** validated reports only; approximate grid key rounded to two decimal places; at least three distinct reporters; only derived incident/freshness signals reach route calculation.
- **Risk engine:** pure functions in `backend/app/risk.py`; missing dimensions reduce coverage and confidence; thresholds and weights are configurable in code.
- **Notifications:** capability reporting only. An interface/provider and delivery persistence still need implementation.
- **Mapping:** demo-only by default. Operators can explicitly enable OSMnx pedestrian routing or Mapbox Directions. Both return route geometry for map display, but neither is treated as a personal-safety score. Safe Spot uses a separate, bounded OpenStreetMap Overpass query for mapped nearby places.
- **Safe Spot:** admin-created records retain their source and verification date. On explicit user search, a bounded Overpass query returns community-mapped police, clinics/hospitals and public places. Results are not verified as safe; support and confidential shelter listings are not queried from OSM.

## Authentication and authorisation

All personal endpoints require a bearer session. Admin endpoints additionally require `admin` or `moderator` role. Tokens include a random session ID persisted in `auth_sessions`; logout revokes that session. Bootstrap an administrator from environment variables at startup. Changing the bootstrap password does not reset an existing account; manage that through a future controlled admin workflow or DB operation.

## Failure behavior

- API disconnect: the UI states an action was not sent; RAAZ can store a local draft with an explicit unsent label.
- Mapping unavailable: no fabricated navigable routes or risk scores are shown.
- Safety coverage insufficient: no green fallback; result is “insufficient information.”
- Notification provider unavailable: SOS remains `created` / `not_configured`.
- OpenStreetMap unavailable or no nearby records: show an explicit empty/unavailable state and do not infer area safety.
- Device speech unsupported: call UI remains controlled; speech playback may be unavailable.

## Production hardening still required

Replace SQLite with the PostGIS-backed repository, add migrations and transactional tests, connect an authorized Safetipin/IUDX audit feed, add secret management, stronger password reset/MFA, rate limits, CSRF review if cookie auth is adopted, evidence object storage/scanning, notification delivery callbacks, background scheduling, observability, backup/restore drills, and native app integrations. The open API and PWA are not a production deployment until these controls and services are operational.

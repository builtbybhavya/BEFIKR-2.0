# BEFIKR

**Bhool ja apne sare dar, Ban Befikr.**

BEFIKR is a mobile-first safety support application with five connected modules: RAAHI, RAAZ, BAAT BANAO, BACKUP, and SAFE SPOT. This workspace contains a runnable progressive web app (PWA), a FastAPI modular-monolith development backend, local SQLite persistence, a privacy-gated moderation pipeline, an explainable prototype risk engine, a PostGIS production schema reference, and workflow tests.

The Flutter SDK is not installed in the inspected environment, so the first runnable client is an installable PWA rather than a Flutter binary. It is responsive on mobile and desktop and caches its interface for offline access. It does not yet have native Android/iOS permission, background location, notification, or app-store packaging support.

## Start locally

Python 3.12+ is recommended. From the repository root in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
$env:BEFIKR_TOKEN_SECRET = [Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
$env:BEFIKR_DATA_DIR = "$PWD\backend\data"
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). Create a user account in the app. The SQLite database is created at `backend/data/befikr.db` and is ignored by Git.

Optional pedestrian-route providers must be configured before starting the API:

```powershell
# OpenStreetMap pedestrian network via OSMnx (no API key)
$env:BEFIKR_MAPPING_PROVIDER = "osmnx"

# Or Mapbox Directions (keep the token server-side)
$env:BEFIKR_MAPPING_PROVIDER = "mapbox"
$env:MAPBOX_ACCESS_TOKEN = "your-server-side-token"
```

The default remains the demo route fallback. OSMnx/Mapbox provide walking geometry and estimates, not a safety rating. OSMnx uses shared public OpenStreetMap geocoding and road-network services; use it in response to a user's explicit route request and follow service usage policies. Mapbox requires a token and may incur usage charges.

The other listed sources need separate configuration before they can inform route risk. Safetipin requires an authorized IUDX resource ID and token, or an approved spatial data export with usable audit fields. `data.gov.in` requires a specific resource ID and API key, and the selected dataset must contain suitable location/time fields. DDA GIS can provide infrastructure context, not personal-safety audits. Google Places can provide place information but is not a safety-rating source and is not connected in this build. The Nirakshak feed/API was not supplied or connected. Until a relevant authorized audit feed is configured, route safety scoring remains unavailable; the manual calculator is only a prototype.

To enable the role-gated admin console, set these variables **before** starting the API. Admin bootstrap happens only when the email is not already in the database:

```powershell
$env:BEFIKR_ADMIN_EMAIL = "moderator@example.org"
$env:BEFIKR_ADMIN_PASSWORD = "use-a-unique-password-with-14-or-more-characters"
```

Sign in with that account, then choose **Admin** from the mobile navigation. Keep development credentials local and use a managed secret store for hosted environments.

## Verify the project

```powershell
Set-Location backend
python -m unittest discover -s tests -v
```

API reference: `http://127.0.0.1:8000/docs`. Health: `http://127.0.0.1:8000/api/health`.

## What works in this build

| Area | State | What is implemented |
|---|---|---|
| Account | Functional local flow | Registration, login, password hashing, signed short-lived sessions, logout revocation, profile edit/delete, data export |
| RAAHI | Partial | Optional OSMnx/Mapbox pedestrian route geometry displays on a map; Google Maps handoff remains available. No Safetipin/Nirakshak route-risk score is shown until an authorized audit feed is configured |
| Map access | Partial | A Map shortcut is available from the app header. Location and the OpenStreetMap preview are opt-in; route previews use OpenStreetMap tiles |
| RAAZ | Functional local workflow | Private submissions, status history, duplicate warning for same-account submissions, status view, appeal, offline local draft queue |
| Report evidence | Unavailable | Secure object storage, malware scanning, attachment upload, and retention jobs are not configured |
| Moderation | Functional local workflow | Role-gated report review, status history, appeal decisions, audit logs; human decisions are required for validation |
| BAAT BANAO | Local simulation | Preset dialogues, caller choices, speech synthesis, and controls; prefers Hindi/Indian English browser voices where available. Age-specific natural voices need an external TTS provider or licensed recordings; no real call is placed |
| BACKUP / SOS | Manual phone handoff | Saves/cancels an event, opens the phone dialer for India 112, and prepares a text to a saved contact. The user must place the call/send the text; there is no automatic dispatch or escalation |
| Track Me | Partial | Consent-started session, optional user-requested last location, expiry, stop/revoke and location deletion; no contact sharing |
| Tap Me | Partial | Server-persisted check-in journey and local status; browser reminder only while the app is open, no external escalation |
| SAFE SPOT | Nearby search | Explicit location search returns community-mapped OSM police, hospitals/clinics and selected public places plus operator-curated listings. Results are not safety-verified; support organisations come only from the managed directory |
| Offline | Partial | PWA shell caching, explicit local-only report drafts, browser-local script UI; API actions need a connection |
| Admin | Functional local tools | Report moderation, appeal handling, Safe Spot administration, aggregate counts, audit log, role gate |

**This build is a development foundation, not a production emergency service.** The app labels all demo and unavailable behavior. A local event record and a prepared text are not a dispatched SOS; a route is not certified safe; a blank map is not evidence of safety.

## Project map

- `web/` — responsive PWA, design system, module screens and offline shell.
- `backend/app/main.py` — FastAPI routes, access controls and service orchestration.
- `backend/app/risk.py` — configurable segment/route scoring and comparisons.
- `backend/app/db.py` — local SQLite schema and connection lifecycle.
- `backend/tests/` — risk and API workflow tests.
- `database/postgresql/001_initial_schema.sql` — PostGIS production-schema reference; not wired to the development API adapter.
- `docs/` — architecture, API, database, privacy, setup, testing and rollout notes.

## Operational and security notes

- Never expose the API publicly with the development token secret or an ephemeral SQLite disk.
- Configure HTTPS, a managed PostgreSQL/PostGIS database, backups, rate limiting, monitoring, secrets, retention workers and an operational incident response process before any real users.
- Set a strict `BEFIKR_CORS_ORIGINS` value when hosting. The local default only allows `http://localhost:8000`.
- Data is sensitive even when a report is anonymous to other users. Restrict staff accounts, audit access and define retention with qualified privacy/legal review.
- Indian privacy and emergency-service obligations require qualified legal review for the specific release and operating model. This repository does not claim compliance certification.

Read [the deployment and limitations guide](docs/deployment.md) before putting this on a network.

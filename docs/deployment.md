# Setup, deployment and known limitations

## Local development

Use the PowerShell steps in the root README. The app runs as one process at `127.0.0.1:8000`; keep it local. Database files are under `backend/data` unless `BEFIKR_DATA_DIR` is set. Configure an administrator with `BEFIKR_ADMIN_EMAIL` and a unique 14+ character `BEFIKR_ADMIN_PASSWORD` before first startup.

## Container image

Build and run the included container for a local/staging evaluation with a persistent data volume. It is still a SQLite development deployment and does not become production-ready by being containerized.

```powershell
docker build -t befikr-dev .
docker run --rm -p 8000:8000 -v befikr-data:/data `
  -e BEFIKR_DATA_DIR=/data `
  -e BEFIKR_TOKEN_SECRET="replace-with-managed-random-secret" `
  -e BEFIKR_ADMIN_EMAIL="moderator@example.org" `
  -e BEFIKR_ADMIN_PASSWORD="use-a-unique-long-password" befikr-dev
```

## Production deployment gate

The repository has no hosting account, provider credentials, production database adapter, mapping key, notification credentials, or operational approval. Do not claim an external integration or deploy an emergency-facing service based on this demo. To prepare a real release:

1. Implement and test a PostgreSQL/PostGIS repository and Alembic migrations using the included schema as a reference.
2. Set `BEFIKR_MAPPING_PROVIDER=osmnx` for OpenStreetMap pedestrian topology, or `BEFIKR_MAPPING_PROVIDER=mapbox` with `MAPBOX_ACCESS_TOKEN` for Mapbox walking routes. OSMnx uses shared public OpenStreetMap services; respect their usage policies. Keep Mapbox tokens on the server and comply with provider terms.
3. Obtain a Safetipin/IUDX resource identifier and authorized token, or an approved data export, before connecting audit scores to route segments. A data.gov.in API key and a specific resource ID are needed before assessing whether a government dataset is spatially and temporally suitable. DDA GIS layers may describe infrastructure or plans but are not personal-safety audit data. Do not infer safety ratings from road topology alone.
4. Securely configure FCM/SMS and receive provider delivery callbacks. Model sent/delivered/acknowledged separately; never show a sent state before confirmation.
5. Add evidence storage, signed access, malware scanning and deletion jobs before enabling uploads.
6. Add background reminders/escalation only with Android/iOS permission and battery-restriction handling; use a server job only for explicitly authorized remote delivery.
7. Set TLS, managed secrets, strict CORS, rate limits, request logging with sensitive-field redaction, error monitoring, backup/restore drills, retention workers and incident response.
8. Complete accessibility, security, privacy/legal, device, connectivity and end-to-end release testing; validate data sources and aggregation thresholds with domain experts.
9. Package a native mobile client if app-store delivery and dependable background features are required.

## Environment variables

See `backend/.env.example`. The example is a reference file; the app does not auto-load `.env`. Inject settings through the shell, container, or secret manager. Never commit secrets.

## Known limitations

- PWA instead of the requested Flutter/Dart native app.
- SQLite-only API runtime; PostGIS SQL is a reference schema.
- OSMnx and Mapbox route geometry are optional; Mapbox requires a server token. There is no live route-safety feed, Google Places adapter, safety reports seed, or emergency/service directory seed.
- No outgoing notification, SMS, real call, police dispatch, live contact map, background reminder or background location.
- Speech synthesis uses available browser voices, which may need network downloads on some devices.
- Report draft storage is browser localStorage and can be cleared with site data; no encrypted offline database.
- No attachment upload, malware scanner, real moderator staffing, rate limiter, password reset, email verification or API pagination.
- No production metrics/tracing, deployment health dashboard or automated retention worker.

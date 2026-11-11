# Test coverage and results

## Run

From `backend/`:

```powershell
python -m unittest discover -s tests -v
```

The suite uses isolated workspace-local SQLite files and does not open a network socket. It covers risk input validation, missing data, normalized model coverage, route scoring and comparison; account/session revocation; report privacy; report review transitions; report aggregation only after independent validated submissions; duplicate-review signals; appeal reopening and audit; SOS delivery-state honesty and cancellation; Track Me consented location removal; Tap Me responses; admin role rejection; Safe Spot source-backed directory search; and the demo mapping disclosure.

## Verified in this workspace

- 17 Python unit/service workflow tests pass.
- `python -m compileall -q backend/app backend/tests` passes.
- `node --check web/app.js` passes.
- FastAPI OpenAPI generation succeeds and exposes 40 paths.

## Not yet covered

These are service-level workflow tests, not full HTTP, browser, Android/iOS, offline-device, screen-reader or load end-to-end tests. A local browser smoke check could not connect to the attempted development server in this environment. The deck’s public-data and helpline references also have not been independently validated or connected. Do not treat this as public-release acceptance testing.

Before release, add HTTP contract and concurrency tests, browser/device journeys, offline/online synchronization, permission-denial and background/battery tests, accessibility checks, security/abuse tests, provider failure simulations and database migration/backup restore tests. Use only test recipients for notification delivery verification.

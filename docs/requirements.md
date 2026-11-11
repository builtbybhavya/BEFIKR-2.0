# BEFIKR product requirements and build status

## Purpose

BEFIKR supports informed travel choices, private community reporting, a discreet simulated call, trusted-person journey tools, and nearby support discovery. It is not an emergency dispatch system and it does not guarantee safety.

## Brand

- BEFIKR — “Bhool ja apne sare dar, Ban Befikr.”
- RAAHI — “Route Smart, Reach Safe.”
- RAAZ — “Naam Rahe Raaz, Safety Ki Awaaz.”
- BAAT BANAO — “Ring Ring, Awkwardness Gone!”
- BACKUP — “One Tap, Your Gang's Got Your Back!”
- SAFE SPOT — “Need a Breather? Find Your Safe Corner!”

Visual system: burgundy, muted gold, ivory, accessible neutral text, restrained motion, and no stereotyped pink styling.

## Module acceptance summary

1. **RAAHI:** User can enter locations and receive pedestrian route geometry from an explicitly configured OSMnx or Mapbox provider. Route lines display on a map. Until an authorized Safetipin audit dataset is connected, route classification stays unavailable. The manual risk calculator remains an unvalidated prototype.
2. **RAAZ:** User submits a structured private report with optional approximate coordinates and time; sees status; appeals a rejection. Reports remain private. Moderators can review history, validate/reject, process appeals, and write audit records. Only validated reports in a coarse cell with at least three distinct reporters may contribute to the route engine. The raw narrative, reporter identity, and precise coordinates are never returned through the route-risk response.
3. **BAAT BANAO:** Caller identity and preset are selectable; the interaction clearly says simulated; speech synthesis can be paused, replayed, continued, or ended. It uses the browser/device voice inventory; real telephony, ringtone and bundled voice packs are not present.
4. **BACKUP:** Trusted contacts are account-scoped. SOS creates an event with `delivery_state=not_configured`, and a user can cancel it. Track Me records a session, accepts optional location only on an explicit action, expires, and deletes stored last location on stop. Tap Me stores check-in timing and responses. No contact delivery or remote escalation is claimed.
5. **SAFE SPOT:** After an explicit search, return nearby OpenStreetMap community-mapped police, hospitals/clinics and selected public places plus operator-curated listings. Support organisations are managed-directory only. No confidential shelter locations are queried. Community-mapped places are not safety certifications.

## Privacy defaults

- Location permissions are requested only from a user-initiated feature.
- Report location/time/evidence are optional; evidence upload is disabled until secure storage and scanning exist.
- The public app sees only the report owner’s status; staff access is role-gated and audited.
- Local report drafts show “NOT submitted” until server receipt.
- Tracking is opt-in and account-only in this build; stop clears the current precise location.
- No analytics SDK, external font fetch, or marketing pixel is bundled.
- Data export is available. Account deletion cascades through associated records in the local database.

## Explicit exclusions for this build

No Safetipin/IUDX resource or export, route-matched personal-safety feed, emergency service integration, FCM, SMS/call provider, object storage, malware scanner, background worker, native mobile app, background location, biometric action, or generative AI moderation is connected. Route topology is opt-in via OSMnx or Mapbox; Safe Spot uses an on-demand public OpenStreetMap Overpass query, which can be incomplete or temporarily unavailable.

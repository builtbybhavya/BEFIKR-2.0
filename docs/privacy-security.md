# Privacy and security notes

## Data in this build

The service stores account name/email/password hash, trusted contact name/phone/relationship, private report narrative and optional approximate location/time, moderation reason/history, appeal text, SOS event coordinates when shared, selected Track Me last-location coordinates until stopped, check-in timing, managed Safe Spot listings, revocable session identifiers, consent events and admin audit events. Passwords are PBKDF2-SHA256 hashed. Browser auth tokens and queued offline reports are stored in `localStorage` for this PWA; a native secure storage integration is not present.

## Access boundaries

- Users list only their own contacts, reports, SOS and journey records.
- Public/user routes never return report location or reporter identity.
- Only validated, coarsened aggregates from a minimum group of three different report owners can inform Raahi.
- Admin/moderator actions require role and write an audit entry.
- Evidence attachments are not accepted because secure evidence storage and malware scanning are absent.
- Admin access to report coordinates and narratives is sensitive and should be limited to trained reviewers.

## Location behavior

The browser asks for geolocation only when the user clicks a location action or starts an SOS event. Safe Spot sends coordinates to the BEFIKR API only after the user submits a nearby search; the API forwards them to OpenStreetMap's Overpass service. Track Me explicitly stores a last location only after the user chooses “Update location now”; it is deleted when the session stops. The Track Me service is account-only and does not send contact grants anywhere. Local browser permissions can be revoked in browser settings.

## Incident response and legal review

This repository is not a legal compliance attestation. Before Indian public launch, obtain qualified review of applicable privacy, data-protection, consumer, evidence, telecom, intermediary, emergency-response and child-safety requirements for the actual organization and service design. Establish a breach response, user request process, contact for grievances, access reviews and retention schedule. Provide users an accurate privacy notice and consent flow for each new processing purpose.

## Security limits

The local token default is explicitly insecure; set a random secret. Password reset, email verification, MFA, abuse throttling, credential stuffing defenses, admin provisioning/recovery, evidence scanning, encryption-at-rest management, database access policies, key rotation, monitoring and production backups remain to be implemented. Host behind TLS and a managed secret/database service. Do not put real sensitive user data into this development instance.

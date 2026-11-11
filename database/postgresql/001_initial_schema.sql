-- PostgreSQL/PostGIS production schema reference for BEFIKR.
-- The current FastAPI development adapter uses SQLite and does not execute this file.
BEGIN;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), email text NOT NULL UNIQUE,
  password_hash text NOT NULL, role text NOT NULL DEFAULT 'user' CHECK(role IN ('user','moderator','admin')),
  email_verified_at timestamptz, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz
);
CREATE TABLE user_profiles (
  user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  display_name text NOT NULL CHECK(length(display_name) BETWEEN 1 AND 80), locale text NOT NULL DEFAULT 'en-IN',
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE user_preferences (
  user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  analytics_opt_in boolean NOT NULL DEFAULT false, push_opt_in boolean NOT NULL DEFAULT false,
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE auth_sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash text NOT NULL UNIQUE, created_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL,
  revoked_at timestamptz, user_agent_hash text
);
CREATE INDEX ix_auth_sessions_user_expiry ON auth_sessions(user_id, expires_at);
CREATE TABLE consent_records (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  purpose text NOT NULL, scope jsonb NOT NULL DEFAULT '{}'::jsonb, granted boolean NOT NULL,
  captured_at timestamptz NOT NULL DEFAULT now(), withdrawn_at timestamptz
);
CREATE INDEX ix_consent_user_purpose ON consent_records(user_id, purpose, captured_at DESC);

CREATE TABLE trusted_contacts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name text NOT NULL, phone_encrypted bytea NOT NULL, relationship text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(user_id, phone_encrypted)
);

CREATE TABLE report_categories (
  id text PRIMARY KEY, label text NOT NULL, active boolean NOT NULL DEFAULT true, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE reports (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), owner_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  category_id text NOT NULL REFERENCES report_categories(id), description_private text NOT NULL,
  approximate_location geography(Point,4326), occurred_at timestamptz,
  status text NOT NULL DEFAULT 'pending_review' CHECK(status IN ('submitted','pending_review','under_review','corroborated','validated','rejected')),
  duplicate_group uuid, retention_until timestamptz, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_reports_status_created ON reports(status, created_at);
CREATE INDEX ix_reports_owner_created ON reports(owner_id, created_at DESC);
CREATE INDEX ix_reports_location ON reports USING gist(approximate_location);
CREATE TABLE evidence_attachments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), report_id uuid NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
  object_key text NOT NULL UNIQUE, mime_type text NOT NULL, size_bytes bigint NOT NULL CHECK(size_bytes BETWEEN 1 AND 20971520),
  malware_state text NOT NULL DEFAULT 'pending' CHECK(malware_state IN ('pending','clean','blocked','failed')),
  uploaded_at timestamptz NOT NULL DEFAULT now(), deleted_at timestamptz
);
CREATE TABLE moderation_history (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), report_id uuid NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
  actor_id uuid REFERENCES users(id) ON DELETE SET NULL, previous_status text, new_status text NOT NULL,
  internal_reason text NOT NULL DEFAULT '', created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_moderation_report_time ON moderation_history(report_id, created_at);
CREATE TABLE report_appeals (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), report_id uuid NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
  owner_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE, message_private text NOT NULL,
  status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','upheld','reopen')),
  reviewed_by uuid REFERENCES users(id) ON DELETE SET NULL, created_at timestamptz NOT NULL DEFAULT now(), reviewed_at timestamptz
);
CREATE TABLE reporter_quality_metrics (
  user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  validation_rate numeric(5,2), corroboration_quality numeric(5,2), location_accuracy numeric(5,2),
  quality_score numeric(5,2), computed_at timestamptz NOT NULL DEFAULT now()
);

-- This cell is deliberately coarser than the private report location. Enforce a
-- minimum group threshold in the aggregation service before any row is published.
CREATE TABLE geographic_cells (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), cell_key text NOT NULL UNIQUE,
  boundary geometry(Polygon,4326), cell_size_m integer NOT NULL CHECK(cell_size_m > 0), created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_geo_cells_boundary ON geographic_cells USING gist(boundary);
CREATE TABLE aggregated_safety_scores (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), cell_id uuid NOT NULL REFERENCES geographic_cells(id) ON DELETE CASCADE,
  category_id text REFERENCES report_categories(id), risk_magnitude numeric(5,2) NOT NULL CHECK(risk_magnitude BETWEEN 0 AND 100),
  confidence numeric(5,2) NOT NULL CHECK(confidence BETWEEN 0 AND 100), independent_reporter_count integer NOT NULL CHECK(independent_reporter_count >= 3),
  model_version text NOT NULL, last_report_at timestamptz NOT NULL, refreshed_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz,
  UNIQUE(cell_id, category_id, model_version)
);
CREATE INDEX ix_aggregate_cell_expiry ON aggregated_safety_scores(cell_id, expires_at);
CREATE TABLE risk_scores (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), segment_id uuid, route_alternative_id uuid,
  score numeric(5,2), confidence numeric(5,2) NOT NULL CHECK(confidence BETWEEN 0 AND 100), coverage numeric(5,3) NOT NULL,
  classification text NOT NULL, factors jsonb NOT NULL DEFAULT '{}'::jsonb, explanation jsonb NOT NULL DEFAULT '[]'::jsonb,
  model_version text NOT NULL, computed_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE route_sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  origin_private geography(Point,4326), destination_private geography(Point,4326), provider text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz
);
CREATE TABLE route_alternatives (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), route_session_id uuid NOT NULL REFERENCES route_sessions(id) ON DELETE CASCADE,
  provider_route_id text, geometry geometry(LineString,4326), distance_m integer, duration_s integer,
  risk_score_id uuid REFERENCES risk_scores(id) ON DELETE SET NULL, comparison_score numeric(5,2), created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE geographic_segments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), route_alternative_id uuid NOT NULL REFERENCES route_alternatives(id) ON DELETE CASCADE,
  segment_order integer NOT NULL, geometry geometry(LineString,4326) NOT NULL, cell_id uuid REFERENCES geographic_cells(id),
  length_m integer NOT NULL CHECK(length_m > 0), safety_score_id uuid REFERENCES risk_scores(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(route_alternative_id, segment_order)
);
CREATE INDEX ix_route_geometry ON route_alternatives USING gist(geometry);
CREATE INDEX ix_segments_geometry ON geographic_segments USING gist(geometry);

CREATE TABLE sos_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  status text NOT NULL CHECK(status IN ('created','cancelled','closed')), delivery_state text NOT NULL,
  location geography(Point,4326), location_at timestamptz, created_at timestamptz NOT NULL DEFAULT now(), cancelled_at timestamptz
);
CREATE TABLE sos_recipients (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), event_id uuid NOT NULL REFERENCES sos_events(id) ON DELETE CASCADE,
  contact_id uuid REFERENCES trusted_contacts(id) ON DELETE SET NULL, recipient_snapshot_encrypted bytea NOT NULL
);
CREATE TABLE alert_delivery_records (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), event_id uuid NOT NULL REFERENCES sos_events(id) ON DELETE CASCADE,
  recipient_id uuid REFERENCES sos_recipients(id) ON DELETE SET NULL, channel text NOT NULL,
  status text NOT NULL CHECK(status IN ('created','queued','sent','delivered','acknowledged','failed','not_configured')),
  provider_reference text, error_code text, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_delivery_status_time ON alert_delivery_records(status, updated_at);

CREATE TABLE tracking_sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  destination_private text, status text NOT NULL CHECK(status IN ('active','stopped','expired','revoked')),
  created_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL, stopped_at timestamptz
);
CREATE TABLE tracking_recipients (
  session_id uuid NOT NULL REFERENCES tracking_sessions(id) ON DELETE CASCADE,
  contact_id uuid NOT NULL REFERENCES trusted_contacts(id) ON DELETE CASCADE,
  consented_at timestamptz NOT NULL DEFAULT now(), revoked_at timestamptz, PRIMARY KEY(session_id, contact_id)
);
CREATE TABLE location_updates (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), session_id uuid NOT NULL REFERENCES tracking_sessions(id) ON DELETE CASCADE,
  point geography(Point,4326) NOT NULL, accuracy_m numeric(8,2), recorded_at timestamptz NOT NULL DEFAULT now(), delete_after timestamptz NOT NULL
);
CREATE INDEX ix_location_session_time ON location_updates(session_id, recorded_at DESC);
CREATE INDEX ix_location_expiry ON location_updates(delete_after);

CREATE TABLE tap_me_journeys (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  destination_private text, status text NOT NULL CHECK(status IN ('active','needs_attention','completed','cancelled')),
  created_at timestamptz NOT NULL DEFAULT now(), completed_at timestamptz
);
CREATE TABLE checkin_schedules (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), journey_id uuid NOT NULL REFERENCES tap_me_journeys(id) ON DELETE CASCADE,
  interval_minutes integer NOT NULL CHECK(interval_minutes BETWEEN 5 AND 240), grace_minutes integer NOT NULL CHECK(grace_minutes BETWEEN 1 AND 60),
  next_due_at timestamptz NOT NULL, active boolean NOT NULL DEFAULT true
);
CREATE TABLE checkin_responses (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), journey_id uuid NOT NULL REFERENCES tap_me_journeys(id) ON DELETE CASCADE,
  response text NOT NULL CHECK(response IN ('safe','need_help','missed')), created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE escalation_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), journey_id uuid NOT NULL REFERENCES tap_me_journeys(id) ON DELETE CASCADE,
  escalation_level integer NOT NULL, state text NOT NULL, delivery_record_id uuid REFERENCES alert_delivery_records(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE safe_spot_categories (
  id text PRIMARY KEY, label text NOT NULL, active boolean NOT NULL DEFAULT true
);
CREATE TABLE safe_spots (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name text NOT NULL, category_id text NOT NULL REFERENCES safe_spot_categories(id),
  location geography(Point,4326) NOT NULL, address text NOT NULL, phone_encrypted bytea, source text NOT NULL,
  verified_at timestamptz NOT NULL, active boolean NOT NULL DEFAULT true, confidential boolean NOT NULL DEFAULT false,
  created_by uuid REFERENCES users(id) ON DELETE SET NULL, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_safe_spot_location ON safe_spots USING gist(location) WHERE active AND NOT confidential;

CREATE TABLE voice_scripts (
  id text PRIMARY KEY, title text NOT NULL, situation text NOT NULL, caller text NOT NULL,
  language text NOT NULL, lines jsonb NOT NULL, active boolean NOT NULL DEFAULT true, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE voice_audio_packs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), language text NOT NULL, voice text NOT NULL,
  object_key text NOT NULL UNIQUE, size_bytes bigint NOT NULL, checksum text NOT NULL,
  active boolean NOT NULL DEFAULT true, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE notification_records (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid REFERENCES users(id) ON DELETE CASCADE,
  channel text NOT NULL, purpose text NOT NULL, status text NOT NULL, provider_reference text,
  failure_detail text, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE admin_roles (
  id text PRIMARY KEY, description text NOT NULL
);
CREATE TABLE administrators (
  user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, role_id text NOT NULL REFERENCES admin_roles(id),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE audit_logs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), actor_id uuid REFERENCES users(id) ON DELETE SET NULL,
  action text NOT NULL, target_type text NOT NULL, target_id text NOT NULL, detail_redacted jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_audit_created ON audit_logs(created_at DESC);
CREATE INDEX ix_audit_target ON audit_logs(target_type, target_id);

COMMIT;

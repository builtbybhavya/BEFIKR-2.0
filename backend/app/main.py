"""BEFIKR modular monolith API. External integrations remain explicit adapters."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import db
from .providers import (UnconfiguredEvidenceStorage, UnconfiguredNotificationProvider,
                        configured_mapping_provider)
from .risk import calculate_route, calculate_segment, compare_routes

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.abspath(os.path.join(APP_DIR, "..", "web"))
TOKEN_SECRET = os.getenv("BEFIKR_TOKEN_SECRET", "development-only-change-this-secret")
TOKEN_HOURS = int(os.getenv("BEFIKR_TOKEN_HOURS", "12"))
REPORT_CATEGORIES = {"harassment", "suspicious activity", "poor lighting", "isolated area",
                     "unsafe public transport", "recurring local concern", "other"}
REPORT_STATUSES = {"submitted", "pending_review", "under_review", "corroborated", "validated", "rejected"}
PLACE_CATEGORIES = {"police", "hospital", "support", "public_place"}
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
DELHI_ROAD_SAFETY_REPORT_URL = "https://transport.delhi.gov.in/sites/default/files/2023-08/road_safety_data_to_action_report.pdf"
MAPPING_PROVIDER = configured_mapping_provider()
NOTIFICATION_PROVIDER = UnconfiguredNotificationProvider()
EVIDENCE_STORAGE = UnconfiguredEvidenceStorage()

app = FastAPI(title="BEFIKR API", version="0.1.0", description="Privacy-conscious safety ecosystem API")
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("BEFIKR_CORS_ORIGINS", "http://localhost:8000").split(","),
                   allow_credentials=True, allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["*"])


def now() -> datetime:
    return datetime.now(timezone.utc)


def stamp(value: datetime | None = None) -> str:
    return (value or now()).isoformat()


def uid() -> str:
    return str(uuid.uuid4())


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return f"pbkdf2_sha256${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, salt, expected = encoded.split("$")
        actual = hash_password(password, bytes.fromhex(salt)).split("$")[-1]
        return scheme == "pbkdf2_sha256" and hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def issue_token(user_id: str, role: str) -> str:
    expiry_at = now() + timedelta(hours=TOKEN_HOURS)
    expiry = int(expiry_at.timestamp())
    session_id = uid()
    with db.connect() as conn:
        conn.execute("INSERT INTO auth_sessions VALUES(?,?,?,?,NULL)", (session_id, user_id, stamp(), stamp(expiry_at)))
    body = base64.urlsafe_b64encode(json.dumps({"sub": user_id, "role": role, "exp": expiry, "jti": session_id}, separators=(",", ":")).encode()).decode().rstrip("=")
    signature = hmac.new(TOKEN_SECRET.encode(), body.encode(), hashlib.sha256).digest()
    return body + "." + base64.urlsafe_b64encode(signature).decode().rstrip("=")


def decode_token(token: str) -> dict[str, Any]:
    try:
        body, signature = token.split(".", 1)
        expected = hmac.new(TOKEN_SECRET.encode(), body.encode(), hashlib.sha256).digest()
        supplied = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
        if not hmac.compare_digest(expected, supplied):
            raise ValueError("signature")
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        if payload["exp"] < int(now().timestamp()):
            raise ValueError("expired")
        with db.connect() as conn:
            session = conn.execute("SELECT revoked_at FROM auth_sessions WHERE id=? AND owner_id=?", (payload["jti"], payload["sub"])).fetchone()
        if not session or session["revoked_at"] is not None:
            raise ValueError("revoked")
        return payload
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        raise HTTPException(401, "Session expired or invalid. Please sign in again.")


def current_user(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Sign in to continue.")
    payload = decode_token(authorization[7:])
    with db.connect() as conn:
        user = conn.execute("SELECT id,name,email,role FROM users WHERE id=?", (payload["sub"],)).fetchone()
    if not user:
        raise HTTPException(401, "Account no longer exists.")
    return dict(user)


def admin_user(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    if user["role"] not in {"admin", "moderator"}:
        raise HTTPException(403, "Administrator access required.")
    return user


def audit(conn, actor: str, action: str, target_type: str, target_id: str, detail: str = "") -> None:
    conn.execute("INSERT INTO audit_logs VALUES(?,?,?,?,?,?,?)", (uid(), actor, action, target_type, target_id, detail[:500], stamp()))


def rowdict(row) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


class RegisterInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=10, max_length=128)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter a valid email address")
        return value

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Enter your name")
        return value


class LoginInput(BaseModel):
    email: str
    password: str


class ProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)


class PreferencesInput(BaseModel):
    analytics_opt_in: bool
    push_opt_in: bool


class ContactInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    phone: str = Field(min_length=4, max_length=32)
    relationship: str = Field(default="", max_length=40)

    @field_validator("name", "phone")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be blank")
        return value


class ReportInput(BaseModel):
    category: str
    description: str = Field(min_length=10, max_length=2000)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    occurred_at: str | None = Field(default=None, max_length=50)

    @field_validator("category")
    @classmethod
    def valid_category(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in REPORT_CATEGORIES:
            raise ValueError("Select a supported report category")
        return value

    @field_validator("description")
    @classmethod
    def meaningful_description(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 10:
            raise ValueError("Please provide at least 10 non-space characters")
        return value


class AppealInput(BaseModel):
    message: str = Field(min_length=10, max_length=1000)


class ModerationInput(BaseModel):
    status: str
    reason: str = Field(default="", max_length=1000)

    @field_validator("status")
    @classmethod
    def valid_status(cls, value: str) -> str:
        if value not in REPORT_STATUSES:
            raise ValueError("Unsupported moderation status")
        return value


class SegmentInput(BaseModel):
    length_km: float = Field(gt=0, le=500)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    model_config = ConfigDict(extra="allow")


class RouteRiskInput(BaseModel):
    segments: list[SegmentInput] = Field(min_length=1, max_length=100)


class RouteInput(BaseModel):
    origin: str = Field(min_length=2, max_length=160)
    destination: str = Field(min_length=2, max_length=160)

    @field_validator("origin", "destination")
    @classmethod
    def strip_location_text(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Enter a place name")
        return value


class SosInput(BaseModel):
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class TrackingInput(BaseModel):
    recipient_ids: list[str] = Field(default_factory=list, max_length=10)
    destination: str | None = Field(default=None, max_length=160)
    duration_minutes: int = Field(default=120, ge=5, le=1440)


class LocationUpdate(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class CheckinInput(BaseModel):
    interval_minutes: int = Field(default=30, ge=5, le=240)
    grace_minutes: int = Field(default=10, ge=1, le=60)
    destination: str | None = Field(default=None, max_length=160)


class PlaceInput(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    category: str
    address: str = Field(min_length=3, max_length=240)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    phone: str = Field(default="", max_length=32)
    source: str = Field(min_length=3, max_length=200)
    verified_at: str = Field(min_length=10, max_length=50)
    active: bool = True

    @field_validator("category")
    @classmethod
    def valid_category(cls, value: str) -> str:
        if value not in PLACE_CATEGORIES:
            raise ValueError("Unsupported Safe Spot category")
        return value

    @field_validator("name", "address", "source")
    @classmethod
    def strip_place_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be blank")
        return value


@app.on_event("startup")
def startup() -> None:
    db.initialize()
    email = os.getenv("BEFIKR_ADMIN_EMAIL", "").strip().lower()
    password = os.getenv("BEFIKR_ADMIN_PASSWORD", "")
    if email and len(password) >= 14:
        with db.connect() as conn:
            existing = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
            if not existing:
                conn.execute("INSERT INTO users VALUES(?,?,?,?,?,?)", (uid(), "BEFIKR Admin", email, hash_password(password), "admin", stamp()))


@app.get("/api/health")
def health():
    with db.connect() as conn:
        conn.execute("SELECT 1").fetchone()
    return {"status": "ok", "service": "befikr-api", "database": "sqlite-development"}


@app.get("/api/capabilities")
def capabilities():
    return {"mapping": {"state": "demo_only", "provider": MAPPING_PROVIDER.name,
                         "requested_provider": os.getenv("BEFIKR_MAP_PROVIDER") or None, "live": False},
            "notifications": {"state": "not_configured", "credentials_present": {"push": bool(os.getenv("FCM_CREDENTIALS")), "sms": bool(os.getenv("SMS_API_KEY"))}},
            "evidence_storage": {"state": "not_configured"}, "background_jobs": {"state": "not_configured"},
            "tracking": {"state": "account_session_only", "external_sharing": False},
            "voice": {"state": "browser_speech_synthesis", "offline_availability": "device_dependent"}}


@app.post("/api/auth/register", status_code=201)
def register(data: RegisterInput):
    user_id = uid()
    try:
        with db.connect() as conn:
            conn.execute("INSERT INTO users VALUES(?,?,?,?,?,?)", (user_id, data.name.strip(), data.email, hash_password(data.password), "user", stamp()))
    except Exception as error:
        if "UNIQUE constraint failed" in str(error):
            raise HTTPException(409, "An account with that email already exists.")
        raise
    return {"access_token": issue_token(user_id, "user"), "token_type": "bearer", "user": {"id": user_id, "name": data.name.strip(), "email": data.email, "role": "user"}}


@app.post("/api/auth/login")
def login(data: LoginInput):
    email = data.email.strip().lower()
    with db.connect() as conn:
        user = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    if not user or not verify_password(data.password, user["password_hash"]):
        raise HTTPException(401, "Email or password is incorrect.")
    return {"access_token": issue_token(user["id"], user["role"]), "token_type": "bearer", "user": {"id": user["id"], "name": user["name"], "email": user["email"], "role": user["role"]}}


@app.post("/api/auth/logout")
def logout(user=Depends(current_user), authorization: str | None = Header(default=None)):
    payload = decode_token(authorization[7:])
    with db.connect() as conn:
        conn.execute("UPDATE auth_sessions SET revoked_at=? WHERE id=? AND owner_id=?", (stamp(), payload["jti"], user["id"]))
    return {"message": "This session has been revoked."}


@app.get("/api/profile")
def get_profile(user=Depends(current_user)):
    return user


@app.patch("/api/profile")
def update_profile(data: ProfileUpdate, user=Depends(current_user)):
    if data.name is not None:
        with db.connect() as conn:
            conn.execute("UPDATE users SET name=? WHERE id=?", (data.name.strip(), user["id"]))
        user["name"] = data.name.strip()
    return user


@app.delete("/api/profile", status_code=204)
def delete_profile(user=Depends(current_user)):
    with db.connect() as conn:
        conn.execute("DELETE FROM users WHERE id=?", (user["id"],))
    return None


@app.get("/api/profile/export")
def export_profile(user=Depends(current_user)):
    with db.connect() as conn:
        contacts = [dict(row) for row in conn.execute("SELECT id,name,phone,relationship,created_at FROM contacts WHERE owner_id=?", (user["id"],))]
        reports = [dict(row) for row in conn.execute("SELECT id,category,description,latitude,longitude,occurred_at,status,created_at,updated_at FROM reports WHERE owner_id=?", (user["id"],))]
        sos_events = [dict(row) for row in conn.execute("SELECT id,status,delivery_state,latitude,longitude,created_at,cancelled_at FROM sos_events WHERE owner_id=?", (user["id"],))]
        tracking = [dict(row) for row in conn.execute("SELECT id,status,destination,created_at,expires_at FROM tracking_sessions WHERE owner_id=?", (user["id"],))]
        consents = [dict(row) for row in conn.execute("SELECT purpose,granted,scope,created_at FROM consent_events WHERE owner_id=?", (user["id"],))]
    return {"profile": user, "contacts": contacts, "reports": reports, "emergency_events": sos_events,
            "journeys": tracking, "consent_history": consents, "exported_at": stamp()}


@app.get("/api/profile/preferences")
def get_preferences(user=Depends(current_user)):
    with db.connect() as conn:
        conn.execute("INSERT OR IGNORE INTO user_preferences(owner_id,updated_at) VALUES(?,?)", (user["id"], stamp()))
        row = conn.execute("SELECT analytics_opt_in,push_opt_in,updated_at FROM user_preferences WHERE owner_id=?", (user["id"],)).fetchone()
    return {"analytics_opt_in": bool(row["analytics_opt_in"]), "push_opt_in": bool(row["push_opt_in"]), "updated_at": row["updated_at"]}


@app.patch("/api/profile/preferences")
def update_preferences(data: PreferencesInput, user=Depends(current_user)):
    with db.connect() as conn:
        conn.execute("INSERT INTO user_preferences(owner_id,analytics_opt_in,push_opt_in,updated_at) VALUES(?,?,?,?) ON CONFLICT(owner_id) DO UPDATE SET analytics_opt_in=excluded.analytics_opt_in,push_opt_in=excluded.push_opt_in,updated_at=excluded.updated_at",
                     (user["id"], int(data.analytics_opt_in), int(data.push_opt_in), stamp()))
    return {"analytics_opt_in": data.analytics_opt_in, "push_opt_in": data.push_opt_in}


@app.get("/api/contacts")
def list_contacts(user=Depends(current_user)):
    with db.connect() as conn:
        return [dict(row) for row in conn.execute("SELECT id,name,phone,relationship,created_at FROM contacts WHERE owner_id=? ORDER BY created_at", (user["id"],))]


@app.post("/api/contacts", status_code=201)
def add_contact(data: ContactInput, user=Depends(current_user)):
    contact_id = uid()
    with db.connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM contacts WHERE owner_id=?", (user["id"],)).fetchone()[0]
        if count >= 10:
            raise HTTPException(400, "You can add up to 10 trusted contacts.")
        conn.execute("INSERT INTO contacts VALUES(?,?,?,?,?,?)", (contact_id, user["id"], data.name.strip(), data.phone.strip(), data.relationship.strip(), stamp()))
        return rowdict(conn.execute("SELECT id,name,phone,relationship,created_at FROM contacts WHERE id=?", (contact_id,)).fetchone())


@app.delete("/api/contacts/{contact_id}", status_code=204)
def delete_contact(contact_id: str, user=Depends(current_user)):
    with db.connect() as conn:
        cur = conn.execute("DELETE FROM contacts WHERE id=? AND owner_id=?", (contact_id, user["id"]))
        if cur.rowcount == 0:
            raise HTTPException(404, "Contact not found.")
    return None


@app.post("/api/reports", status_code=201)
def create_report(data: ReportInput, user=Depends(current_user)):
    report_id, moment = uid(), stamp()
    with db.connect() as conn:
        if data.latitude is not None and data.longitude is not None:
            duplicate = conn.execute("""SELECT id FROM reports WHERE owner_id=? AND category=? AND status!='rejected'
                AND created_at>=? AND latitude BETWEEN ? AND ? AND longitude BETWEEN ? AND ? LIMIT 1""",
                (user["id"], data.category, stamp(now() - timedelta(hours=24)), data.latitude - .005, data.latitude + .005,
                 data.longitude - .005, data.longitude + .005)).fetchone()
            if duplicate:
                raise HTTPException(409, "You already have a similar report awaiting review in this approximate area.")
        conn.execute("INSERT INTO reports(id,owner_id,category,description,latitude,longitude,occurred_at,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                     (report_id, user["id"], data.category, data.description.strip(), data.latitude, data.longitude, data.occurred_at, "pending_review", moment, moment))
        conn.execute("INSERT INTO report_history VALUES(?,?,?,?,?,?,?)", (uid(), report_id, user["id"], None, "pending_review", "Report submitted", moment))
        conn.execute("INSERT INTO consent_events VALUES(?,?,?,?,?,?)", (uid(), user["id"], "raaz_report_submission", 1, "Private account-linked report; not public; review and retention apply", moment))
    return {"id": report_id, "status": "pending_review", "message": "Report received by this development service and is awaiting review. It is not public."}


def public_report(row) -> dict[str, Any]:
    return {key: row[key] for key in ("id", "category", "description", "occurred_at", "status", "created_at", "updated_at")}


@app.get("/api/reports")
def list_reports(user=Depends(current_user)):
    with db.connect() as conn:
        rows = conn.execute("SELECT id,category,description,occurred_at,status,created_at,updated_at FROM reports WHERE owner_id=? ORDER BY created_at DESC", (user["id"],)).fetchall()
    return [public_report(row) for row in rows]


@app.get("/api/reports/status/{report_id}")
def report_status(report_id: str, user=Depends(current_user)):
    with db.connect() as conn:
        row = conn.execute("SELECT id,status,created_at,updated_at FROM reports WHERE id=? AND owner_id=?", (report_id, user["id"])).fetchone()
    if not row:
        raise HTTPException(404, "Report not found.")
    return dict(row)


@app.post("/api/reports/{report_id}/appeal", status_code=201)
def appeal_report(report_id: str, data: AppealInput, user=Depends(current_user)):
    with db.connect() as conn:
        report = conn.execute("SELECT status FROM reports WHERE id=? AND owner_id=?", (report_id, user["id"])).fetchone()
        if not report:
            raise HTTPException(404, "Report not found.")
        if report["status"] != "rejected":
            raise HTTPException(400, "Only rejected reports can be appealed.")
        appeal_id = uid()
        conn.execute("INSERT INTO appeals VALUES(?,?,?,?,?,?)", (appeal_id, report_id, user["id"], data.message.strip(), "pending", stamp()))
        return {"id": appeal_id, "status": "pending"}


@app.post("/api/routes/alternatives")
def route_alternatives(data: RouteInput, user=Depends(current_user)):
    """Transparent fallback: illustrative choices only; never claims to be navigable/live."""
    result = MAPPING_PROVIDER.alternatives(data.origin.strip(), data.destination.strip())
    result["routes"] = compare_routes(result["routes"])
    return result


@app.post("/api/routes/risk")
def route_risk(data: RouteRiskInput, user=Depends(current_user)):
    results = []
    for segment in data.segments:
        payload = segment.model_dump(exclude={"length_km", "latitude", "longitude"})
        corroboration = None
        aggregated = False
        if segment.latitude is not None and segment.longitude is not None and payload.get("incident") is None:
            with db.connect() as conn:
                reports = conn.execute("SELECT owner_id,created_at FROM reports WHERE status='validated' AND ROUND(latitude,2)=ROUND(?,2) AND ROUND(longitude,2)=ROUND(?,2)",
                                       (segment.latitude, segment.longitude)).fetchall()
            distinct_reporters = len({row["owner_id"] for row in reports})
            if distinct_reporters >= 3:
                ages = []
                for row in reports:
                    created = datetime.fromisoformat(row["created_at"])
                    if created.tzinfo is None:
                        created = created.replace(tzinfo=timezone.utc)
                    ages.append(max(0.0, (now() - created).total_seconds() / 86400))
                payload["incident"] = min(100, distinct_reporters * 20)
                payload["freshness"] = round(sum(100 * math.exp(-age / 90) for age in ages) / len(ages), 1)
                corroboration = 1.0
                aggregated = True
        result = calculate_segment(payload, corroboration=corroboration, minimum_coverage=0.40)
        results.append({"score": result.score, "confidence": result.confidence, "coverage": result.coverage,
                        "classification": result.classification, "explanation": result.explanation,
                        "length_km": segment.length_km, "aggregated_validated_reports": aggregated})
    return {"segments": results, "route": calculate_route(results), "model": "configurable prototype; not scientifically validated",
            "privacy_note": "Only validated reports from a coarse geographic cell with at least three distinct reporters can contribute. Raw report text and exact locations are not returned."}


@app.get("/api/routes/data-status")
def route_data_status(user=Depends(current_user)):
    return {"state": "not configured", "minimum_aggregation_threshold": 3,
            "last_updated": None,
            "message": "Walking-route geometry can use the configured OSMnx or Mapbox provider. No Safetipin audit resource/export is connected, so BEFIKR cannot score routes for personal safety. Delhi Transport Department's public report is historical road-crash analysis for 2019–2021; it is not a personal-safety dataset.",
            "source_url": DELHI_ROAD_SAFETY_REPORT_URL,
            "mapping_provider": getattr(MAPPING_PROVIDER, "name", "unknown"),
            "nirakshak_state": "official_feed_not_connected",
            "safetipin_state": "authorized_iudx_resource_or_export_required",
            "data_gov_state": "dataset_resource_id_and_api_key_required",
            "dda_state": "infrastructure_context_only",
            "google_places_state": "places_only_not_connected"}


@app.post("/api/sos", status_code=201)
def create_sos(data: SosInput, user=Depends(current_user)):
    event_id = uid()
    with db.connect() as conn:
        conn.execute("INSERT INTO sos_events VALUES(?,?,?,?,?,?,?,?)", (event_id, user["id"], "created", "not_configured", data.latitude, data.longitude, stamp(), None))
    with db.connect() as conn:
        conn.execute("INSERT INTO consent_events VALUES(?,?,?,?,?,?)", (uid(), user["id"], "emergency_event", 1, "User explicitly created an emergency event record; no dispatch", stamp()))
    return {"id": event_id, "status": "created", "delivery_state": "not_configured",
            "message": "Emergency event saved. No contact, emergency service, SMS, or push notification was sent."}


@app.get("/api/sos")
def list_sos_events(user=Depends(current_user)):
    with db.connect() as conn:
        return [dict(row) for row in conn.execute("SELECT id,status,delivery_state,created_at,cancelled_at FROM sos_events WHERE owner_id=? ORDER BY created_at DESC LIMIT 100", (user["id"],))]


@app.get("/api/sos/{event_id}")
def get_sos(event_id: str, user=Depends(current_user)):
    with db.connect() as conn:
        event = conn.execute("SELECT id,status,delivery_state,created_at,cancelled_at FROM sos_events WHERE id=? AND owner_id=?", (event_id, user["id"])).fetchone()
    if not event:
        raise HTTPException(404, "Event not found.")
    return dict(event)


@app.post("/api/sos/{event_id}/cancel")
def cancel_sos(event_id: str, user=Depends(current_user)):
    with db.connect() as conn:
        cur = conn.execute("UPDATE sos_events SET status='cancelled',cancelled_at=? WHERE id=? AND owner_id=? AND status='created'", (stamp(), event_id, user["id"]))
        if not cur.rowcount:
            raise HTTPException(404, "Active event not found.")
        event = conn.execute("SELECT id,status,delivery_state,cancelled_at FROM sos_events WHERE id=?", (event_id,)).fetchone()
    return dict(event)


@app.post("/api/tracking/start", status_code=201)
def start_tracking(data: TrackingInput, user=Depends(current_user)):
    session_id = uid()
    with db.connect() as conn:
        owned = {r[0] for r in conn.execute("SELECT id FROM contacts WHERE owner_id=?", (user["id"],))}
        if any(contact_id not in owned for contact_id in data.recipient_ids):
            raise HTTPException(400, "Choose trusted contacts from your account.")
        expires = now() + timedelta(minutes=data.duration_minutes)
        conn.execute("INSERT INTO tracking_sessions VALUES(?,?,?,?,?,?,?,?,?,?)",
                     (session_id, user["id"], json.dumps(data.recipient_ids), "active", data.destination, None, None, None, stamp(), stamp(expires)))
        conn.execute("INSERT INTO consent_events VALUES(?,?,?,?,?,?)", (uid(), user["id"], "track_me_session", 1, "Explicitly started; account-only; contact sharing disabled", stamp()))
    return {"id": session_id, "status": "active", "expires_at": stamp(expires), "external_sharing": False,
            "message": "Journey session is active in your account. Live contact sharing is not configured."}


@app.post("/api/tracking/{session_id}/location")
def update_tracking(session_id: str, data: LocationUpdate, user=Depends(current_user)):
    with db.connect() as conn:
        cur = conn.execute("UPDATE tracking_sessions SET last_latitude=?,last_longitude=?,location_at=? WHERE id=? AND owner_id=? AND status='active' AND expires_at>?",
                           (data.latitude, data.longitude, stamp(), session_id, user["id"], stamp()))
        if not cur.rowcount:
            raise HTTPException(404, "Active journey session not found or expired.")
    return {"id": session_id, "location_recorded": True, "external_sharing": False}


@app.get("/api/tracking/{session_id}")
def get_tracking(session_id: str, user=Depends(current_user)):
    with db.connect() as conn:
        row = conn.execute("SELECT id,status,destination,last_latitude,last_longitude,location_at,created_at,expires_at FROM tracking_sessions WHERE id=? AND owner_id=?", (session_id, user["id"])).fetchone()
    if not row:
        raise HTTPException(404, "Journey session not found.")
    result = dict(row)
    if result["status"] == "active" and result["expires_at"] <= stamp():
        with db.connect() as conn:
            conn.execute("UPDATE tracking_sessions SET status='expired',last_latitude=NULL,last_longitude=NULL,location_at=NULL WHERE id=? AND owner_id=?", (session_id, user["id"]))
        result.update({"status": "expired", "last_latitude": None, "last_longitude": None, "location_at": None})
    return {**result, "external_sharing": False}


@app.post("/api/tracking/{session_id}/stop")
@app.post("/api/tracking/{session_id}/revoke")
def stop_tracking(session_id: str, user=Depends(current_user)):
    with db.connect() as conn:
        cur = conn.execute("UPDATE tracking_sessions SET status='stopped',last_latitude=NULL,last_longitude=NULL,location_at=NULL WHERE id=? AND owner_id=? AND status='active'", (session_id, user["id"]))
        if not cur.rowcount:
            raise HTTPException(404, "Active journey session not found.")
    return {"id": session_id, "status": "stopped", "location_deleted": True}


@app.post("/api/checkins/start", status_code=201)
def start_checkins(data: CheckinInput, user=Depends(current_user)):
    journey_id, due = uid(), now() + timedelta(minutes=data.interval_minutes)
    with db.connect() as conn:
        conn.execute("INSERT INTO journeys(id,owner_id,interval_minutes,grace_minutes,status,destination,next_due_at,created_at) VALUES(?,?,?,?,?,?,?,?)",
                     (journey_id, user["id"], data.interval_minutes, data.grace_minutes, "active", data.destination, stamp(due), stamp()))
        conn.execute("INSERT INTO consent_events VALUES(?,?,?,?,?,?)", (uid(), user["id"], "tap_me_journey", 1, "Explicitly started; reminders while app open; no external escalation", stamp()))
    return {"id": journey_id, "status": "active", "next_due_at": stamp(due), "reminder_mode": "while_app_is_open", "remote_escalation": False}


@app.get("/api/checkins/{journey_id}")
def get_checkins(journey_id: str, user=Depends(current_user)):
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM journeys WHERE id=? AND owner_id=?", (journey_id, user["id"])).fetchone()
        events = conn.execute("SELECT response,created_at FROM checkin_events WHERE journey_id=? ORDER BY created_at DESC", (journey_id,)).fetchall()
    if not row:
        raise HTTPException(404, "Journey not found.")
    result = dict(row)
    if result["status"] == "active" and datetime.fromisoformat(result["next_due_at"]) + timedelta(minutes=result["grace_minutes"]) < now():
        result["status"] = "needs_attention"
        result["escalation"] = "local_status_only_no_contacts_notified"
    result["events"] = [dict(e) for e in events]
    return result


@app.post("/api/checkins/{journey_id}/respond")
def respond_checkin(journey_id: str, user=Depends(current_user)):
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM journeys WHERE id=? AND owner_id=? AND status='active'", (journey_id, user["id"])).fetchone()
        if not row:
            raise HTTPException(404, "Active journey not found.")
        due = now() + timedelta(minutes=row["interval_minutes"])
        conn.execute("INSERT INTO checkin_events VALUES(?,?,?,?)", (uid(), journey_id, "safe", stamp()))
        conn.execute("UPDATE journeys SET next_due_at=? WHERE id=?", (stamp(due), journey_id))
    return {"id": journey_id, "status": "active", "last_response": "safe", "next_due_at": stamp(due)}


@app.post("/api/checkins/{journey_id}/cancel")
def cancel_checkins(journey_id: str, user=Depends(current_user)):
    with db.connect() as conn:
        cur = conn.execute("UPDATE journeys SET status='cancelled',completed_at=? WHERE id=? AND owner_id=? AND status='active'", (stamp(), journey_id, user["id"]))
        if not cur.rowcount:
            raise HTTPException(404, "Active journey not found.")
    return {"id": journey_id, "status": "cancelled"}


def distance_km(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    radius = 6371
    d_lat, d_lon = math.radians(b_lat - a_lat), math.radians(b_lon - a_lon)
    val = math.sin(d_lat / 2) ** 2 + math.cos(math.radians(a_lat)) * math.cos(math.radians(b_lat)) * math.sin(d_lon / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(val), math.sqrt(1 - val))


@app.get("/api/places/categories")
def place_categories():
    return {"categories": [{"id": key, "label": label} for key, label in [("police", "Police"), ("hospital", "Hospital"), ("support", "Support organisation"), ("public_place", "Public place")]]}


def osm_nearby_places(latitude: float, longitude: float, radius_km: float, category: str | None) -> list[dict[str, Any]]:
    """Fetch a small, user-requested nearby-place query from OSM's public Overpass API."""
    radius_m = round(radius_km * 1000)
    center = f"{latitude:.6f},{longitude:.6f}"
    filters = {
        "police": ['["amenity"="police"]'],
        "hospital": ['["amenity"="hospital"]', '["amenity"="clinic"]', '["amenity"="doctors"]'],
        "public_place": ['["leisure"="park"]', '["amenity"="community_centre"]', '["amenity"="library"]'],
    }
    selected = [category] if category in filters else list(filters)
    clauses = [f"nwr(around:{radius_m},{center}){tag_filter};" for key in selected for tag_filter in filters[key]]
    query = f"[out:json][timeout:12];({' '.join(clauses)});out center tags qt 80;"
    request = Request(
        OVERPASS_URL,
        data=urlencode({"data": query}).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "BEFIKR-SafeSpot/0.1"},
        method="POST",
    )
    with urlopen(request, timeout=16) as response:
        payload = json.loads(response.read(2_000_001).decode("utf-8"))
    if not isinstance(payload, dict) or payload.get("remark"):
        raise ValueError("OpenStreetMap returned an incomplete nearby-place response")
    elements = payload.get("elements", [])
    results: list[dict[str, Any]] = []
    for element in elements:
        tags = element.get("tags") or {}
        point = element.get("center") or element
        lat, lon = point.get("lat"), point.get("lon")
        if lat is None or lon is None:
            continue
        amenity = tags.get("amenity", "")
        if amenity == "police":
            kind = "police"
            label = "Police station"
        elif amenity in {"hospital", "clinic", "doctors"}:
            kind = "hospital"
            label = {"hospital": "Hospital", "clinic": "Clinic", "doctors": "Doctor / clinic"}[amenity]
        else:
            kind = "public_place"
            label = "Park" if tags.get("leisure") == "park" else "Public place"
        street = " ".join(part for part in [tags.get("addr:street"), tags.get("addr:housenumber")] if part)
        locality = tags.get("addr:suburb") or tags.get("addr:neighbourhood") or tags.get("addr:city")
        address = tags.get("addr:full") or ", ".join(part for part in [street, locality] if part) or "Address not listed"
        results.append({
            "id": f"osm-{element.get('type')}-{element.get('id')}",
            "name": tags.get("name") or tags.get("name:en") or label,
            "category": kind,
            "category_label": label,
            "address": address,
            "phone": tags.get("phone") or tags.get("contact:phone") or "",
            "latitude": float(lat),
            "longitude": float(lon),
            "distance_km": round(distance_km(latitude, longitude, float(lat), float(lon)), 1),
            "source": "OpenStreetMap contributors",
            "source_kind": "openstreetmap",
            "verified_at": None,
        })
    return results


@app.get("/api/places/nearby")
def nearby_places(latitude: float = Query(ge=-90, le=90), longitude: float = Query(ge=-180, le=180), category: str | None = None, radius_km: float = Query(default=5, ge=0.1, le=10), user=Depends(current_user)):
    if category is not None and category not in PLACE_CATEGORIES:
        raise HTTPException(422, "Unsupported Safe Spot category")
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM places WHERE active=1" + (" AND category=?" if category else ""), ((category,) if category else ())).fetchall()
    results = []
    for row in rows:
        distance = distance_km(latitude, longitude, row["latitude"], row["longitude"])
        if distance <= radius_km:
            item = dict(row)
            item["distance_km"] = round(distance, 1)
            item["category_label"] = {"police": "Police", "hospital": "Hospital", "support": "Support organisation", "public_place": "Public place"}.get(item["category"], item["category"])
            item["source_kind"] = "managed_directory"
            results.append(item)
    results.sort(key=lambda item: item["distance_km"])
    osm_state = "available"
    osm_message = "Community-mapped places may be missing or out of date. They are not safety-verified."
    osm_results: list[dict[str, Any]] = []
    if category != "support":
        try:
            osm_results = osm_nearby_places(latitude, longitude, radius_km, category)
        except (URLError, TimeoutError, OSError, ValueError):
            osm_state = "unavailable"
            osm_message = "OpenStreetMap nearby search is temporarily unavailable. Try again later or use an external map."
    else:
        osm_message = "Support organisations are shown only from the operator-curated directory. No confidential shelter locations are searched."
    seen = {(item.get("source_kind"), item.get("id")) for item in results}
    results.extend(item for item in osm_results if (item["source_kind"], item["id"]) not in seen)
    results.sort(key=lambda item: item["distance_km"])
    source_state = "openstreetmap_unavailable" if osm_state == "unavailable" else "curated_directory_only" if category == "support" else "nearby_search_complete"
    return {
        "places": results[:100],
        "source_state": source_state,
        "managed_count": sum(item["source_kind"] == "managed_directory" for item in results),
        "openstreetmap_count": sum(item["source_kind"] == "openstreetmap" for item in results),
        "message": osm_message,
        "empty_message": "No mapped or directory places were returned. This is not evidence that the area is safe or that no services exist.",
        "attribution": "© OpenStreetMap contributors" if osm_state == "available" and category != "support" else None,
    }


VOICE_SCRIPTS = [
    {"id": "exit-conversation", "title": "Leave a conversation", "situation": "uncomfortable_conversation", "caller": "Friend", "voice": "female", "language": "English", "lines": ["Hey, I’m outside. Are you ready?", "No rush, I’ll wait near the entrance.", "Great. Come when you’re ready."]},
    {"id": "leave-gathering", "title": "Step away from a gathering", "situation": "social_gathering", "caller": "Mother", "voice": "female", "language": "Hinglish", "lines": ["Beta, ghar nikalne ka time ho gaya. Kahan ho?", "Theek hai, main tumhara wait kar rahi hoon.", "Haan, aaram se bahar aa jao."]},
    {"id": "leave-meeting", "title": "Leave a meeting", "situation": "meeting", "caller": "Father", "voice": "male", "language": "English", "lines": ["Hi, I need you to call me back when you can.", "It’s about the plan for this evening.", "Okay, talk soon."]},
    {"id": "check-in", "title": "Trusted person check-in", "situation": "travelling_alone", "caller": "Friend", "voice": "male", "language": "Hindi", "lines": ["बस पूछ रहा था, तुम ठीक हो?", "अगर चाहो तो मैं लाइन पर रुकता हूँ।", "ठीक है, आराम से बात करना।"]},
    {"id": "group-interruption", "title": "Friendly group interruption", "situation": "need_interruption", "caller": "Group call", "voice": "mixed", "language": "English", "lines": ["Hey! We’re all waiting for you.", "Should we save you a seat?", "Come join us whenever you’re ready."]},
]


@app.get("/api/voice/scripts")
def voice_scripts():
    return {"scripts": VOICE_SCRIPTS, "mode": "locally playable text; device speech synthesis availability varies", "real_call": False}


@app.get("/api/voice/scripts/{script_id}")
def voice_script(script_id: str):
    script = next((item for item in VOICE_SCRIPTS if item["id"] == script_id), None)
    if not script:
        raise HTTPException(404, "Script not found.")
    return script


@app.get("/api/admin/dashboard")
def admin_dashboard(user=Depends(admin_user)):
    with db.connect() as conn:
        counts = {row["status"]: row["n"] for row in conn.execute("SELECT status,COUNT(*) AS n FROM reports GROUP BY status")}
        total_users = conn.execute("SELECT COUNT(*) FROM users WHERE role='user'").fetchone()[0]
        appeals = conn.execute("SELECT COUNT(*) FROM appeals WHERE status='pending'").fetchone()[0]
        sos_count = conn.execute("SELECT COUNT(*) FROM sos_events WHERE created_at>=?", (stamp(now() - timedelta(days=30)),)).fetchone()[0]
    return {"total_users": total_users, "reports": counts, "pending_review": counts.get("pending_review", 0) + counts.get("submitted", 0),
            "pending_appeals": appeals, "sos_events_30d": sos_count, "safe_spots": "administrator_managed",
            "integrations": capabilities(), "note": "SOS totals are account events, not confirmed dispatched alerts."}


@app.get("/api/admin/reports")
def admin_reports(status: str | None = None, user=Depends(admin_user)):
    with db.connect() as conn:
        audit(conn, user["id"], "sensitive_reports_queue_viewed", "reports_queue", status or "all", "Narratives and approximate locations accessed by authorised staff")
        rows = conn.execute("SELECT r.*,u.email AS reporter_email FROM reports r JOIN users u ON u.id=r.owner_id" + (" WHERE r.status=?" if status in REPORT_STATUSES else "") + " ORDER BY r.created_at DESC LIMIT 200", ((status,) if status in REPORT_STATUSES else ())).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["history"] = []
        with db.connect() as conn:
            item["history"] = [dict(h) for h in conn.execute("SELECT old_status,new_status,reason,created_at FROM report_history WHERE report_id=? ORDER BY created_at", (row["id"],))]
            peers = []
            if row["latitude"] is not None and row["longitude"] is not None:
                peers = conn.execute("SELECT id,owner_id,created_at FROM reports WHERE id<>? AND category=? AND status<>'rejected' AND ROUND(latitude,2)=ROUND(?,2) AND ROUND(longitude,2)=ROUND(?,2)",
                                     (row["id"], row["category"], row["latitude"], row["longitude"])).fetchall()
        submitted = datetime.fromisoformat(row["created_at"])
        if submitted.tzinfo is None:
            submitted = submitted.replace(tzinfo=timezone.utc)
        nearby_reporters = set()
        for peer in peers:
            peer_created = datetime.fromisoformat(peer["created_at"])
            if peer_created.tzinfo is None:
                peer_created = peer_created.replace(tzinfo=timezone.utc)
            if abs((submitted - peer_created).total_seconds()) <= 86400:
                nearby_reporters.add(peer["owner_id"])
        item["nearby_similar_reporters"] = len(nearby_reporters)
        result.append(item)
    return result


@app.patch("/api/admin/reports/{report_id}/status")
def moderate_report(report_id: str, data: ModerationInput, user=Depends(admin_user)):
    with db.connect() as conn:
        report = conn.execute("SELECT status FROM reports WHERE id=?", (report_id,)).fetchone()
        if not report:
            raise HTTPException(404, "Report not found.")
        transitions = {
            "submitted": {"pending_review", "under_review"},
            "pending_review": {"under_review"},
            "under_review": {"corroborated", "validated", "rejected"},
            "corroborated": {"under_review", "validated", "rejected"},
            "validated": {"under_review", "rejected"},
            "rejected": {"under_review"},
        }
        if data.status != report["status"] and data.status not in transitions.get(report["status"], set()):
            raise HTTPException(409, f"Cannot change a report from {report['status']} to {data.status} in one step.")
        if report["status"] == "validated" and data.status != "validated" and not data.reason.strip():
            raise HTTPException(400, "A reason is required to change a validated report.")
        moment = stamp()
        conn.execute("UPDATE reports SET status=?,internal_reason=?,updated_at=? WHERE id=?", (data.status, data.reason.strip(), moment, report_id))
        conn.execute("INSERT INTO report_history VALUES(?,?,?,?,?,?,?)", (uid(), report_id, user["id"], report["status"], data.status, data.reason.strip(), moment))
        audit(conn, user["id"], "report_status_changed", "report", report_id, data.status)
        return {"id": report_id, "previous_status": report["status"], "status": data.status}


@app.get("/api/admin/appeals")
def admin_appeals(user=Depends(admin_user)):
    with db.connect() as conn:
        return [dict(row) for row in conn.execute("SELECT id,report_id,message,status,created_at FROM appeals WHERE status='pending' ORDER BY created_at")]


@app.patch("/api/admin/appeals/{appeal_id}")
def review_appeal(appeal_id: str, decision: str = Query(pattern="^(upheld|reopen)$"), user=Depends(admin_user)):
    with db.connect() as conn:
        appeal = conn.execute("SELECT report_id FROM appeals WHERE id=? AND status='pending'", (appeal_id,)).fetchone()
        if not appeal:
            raise HTTPException(404, "Pending appeal not found.")
        conn.execute("UPDATE appeals SET status=? WHERE id=?", (decision, appeal_id))
        if decision == "reopen":
            report = conn.execute("SELECT status FROM reports WHERE id=?", (appeal["report_id"],)).fetchone()
            conn.execute("UPDATE reports SET status='under_review',updated_at=? WHERE id=?", (stamp(), appeal["report_id"]))
            conn.execute("INSERT INTO report_history VALUES(?,?,?,?,?,?,?)", (uid(), appeal["report_id"], user["id"], report["status"], "under_review", "Reopened after appeal", stamp()))
        audit(conn, user["id"], "appeal_reviewed", "appeal", appeal_id, decision)
    return {"id": appeal_id, "status": decision, "report_status": "under_review" if decision == "reopen" else "rejected"}


@app.get("/api/admin/places")
def admin_places(user=Depends(admin_user)):
    with db.connect() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM places ORDER BY updated_at DESC")]


@app.post("/api/admin/places", status_code=201)
def create_place(data: PlaceInput, user=Depends(admin_user)):
    place_id, moment = uid(), stamp()
    with db.connect() as conn:
        conn.execute("INSERT INTO places VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (place_id, data.name.strip(), data.category, data.address.strip(), data.latitude, data.longitude, data.phone.strip(), data.source.strip(), data.verified_at, int(data.active), moment, moment))
        audit(conn, user["id"], "place_created", "place", place_id)
    return {"id": place_id, **data.model_dump()}


@app.patch("/api/admin/places/{place_id}")
def update_place(place_id: str, data: PlaceInput, user=Depends(admin_user)):
    with db.connect() as conn:
        cur = conn.execute("UPDATE places SET name=?,category=?,address=?,latitude=?,longitude=?,phone=?,source=?,verified_at=?,active=?,updated_at=? WHERE id=?",
                           (data.name.strip(), data.category, data.address.strip(), data.latitude, data.longitude, data.phone.strip(), data.source.strip(), data.verified_at, int(data.active), stamp(), place_id))
        if not cur.rowcount:
            raise HTTPException(404, "Safe Spot not found.")
        audit(conn, user["id"], "place_updated", "place", place_id)
    return {"id": place_id, **data.model_dump()}


@app.get("/api/admin/audit-logs")
def admin_audit_logs(limit: int = Query(default=100, ge=1, le=500), user=Depends(admin_user)):
    with db.connect() as conn:
        return [dict(row) for row in conn.execute("SELECT id,actor_id,action,target_type,target_id,detail,created_at FROM audit_logs ORDER BY created_at DESC LIMIT ?", (limit,))]


if os.path.isdir(WEB_DIR):
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")

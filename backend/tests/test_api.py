"""Deterministic service/API-function tests without opening a network socket."""

import os
import unittest
from pathlib import Path
import uuid

from fastapi import HTTPException

from app import db, main


class ApiWorkflowTests(unittest.TestCase):
    def setUp(self):
        db.DATA_PATH = Path(__file__).resolve().parent / ".test_data"
        db.DATA_PATH.mkdir(exist_ok=True)
        db.DB_PATH = db.DATA_PATH / f"test-{uuid.uuid4()}.db"
        os.environ["BEFIKR_ADMIN_EMAIL"] = "moderator@example.test"
        os.environ["BEFIKR_ADMIN_PASSWORD"] = "development-admin-password"
        main.startup()
        with db.connect() as connection:
            self.admin = dict(connection.execute("SELECT id,name,email,role FROM users WHERE email=?", ("moderator@example.test",)).fetchone())

    def tearDown(self):
        for suffix in ("", "-wal", "-shm"):
            path = Path(str(db.DB_PATH) + suffix)
            if path.exists():
                path.unlink()
        try:
            db.DATA_PATH.rmdir()
        except OSError:
            pass

    def register(self, suffix="one"):
        return main.register(main.RegisterInput(name=suffix.title(), email=f"{suffix}@example.test", password="safe-password-123"))

    @staticmethod
    def user_from(account):
        return account["user"]

    def test_report_is_private_and_admin_pipeline_aggregates_only_validated_reports(self):
        reports = []
        for number in range(3):
            account = self.register(f"reporter{number}")
            user = self.user_from(account)
            created = main.create_report(main.ReportInput(category="poor lighting", description="Several lamps are not working on this block.", latitude=12.9716, longitude=77.5946), user)
            reports.append(created["id"])
            own = main.list_reports(user)[0]
            self.assertNotIn("latitude", own)

        review_queue = main.admin_reports(None, self.admin)
        self.assertEqual({row["nearby_similar_reporters"] for row in review_queue}, {2})

        for report_id in reports:
            main.moderate_report(report_id, main.ModerationInput(status="under_review", reason="Initial review."), self.admin)
            main.moderate_report(report_id, main.ModerationInput(status="corroborated", reason="Independent corroboration recorded."), self.admin)
            changed = main.moderate_report(report_id, main.ModerationInput(status="validated", reason="Reviewed test report."), self.admin)
            self.assertEqual(changed["status"], "validated")

        result = main.route_risk(main.RouteRiskInput(segments=[main.SegmentInput(length_km=1, latitude=12.9716, longitude=77.5946)]), self.admin)
        self.assertTrue(result["segments"][0]["aggregated_validated_reports"])
        self.assertNotIn("description", str(result))
        self.assertNotIn("report_id", str(result))

    def test_sos_state_is_honest_and_cancellable(self):
        user = self.user_from(self.register())
        created = main.create_sos(main.SosInput(latitude=12.9, longitude=77.5), user)
        self.assertEqual(created["delivery_state"], "not_configured")
        cancelled = main.cancel_sos(created["id"], user)
        self.assertEqual(cancelled["status"], "cancelled")

    def test_logout_revokes_session(self):
        account = self.register()
        user = self.user_from(account)
        main.logout(user, f"Bearer {account['access_token']}")
        with self.assertRaises(HTTPException) as error:
            main.decode_token(account["access_token"])
        self.assertEqual(error.exception.status_code, 401)

    def test_role_gate_rejects_regular_users(self):
        regular_user = self.user_from(self.register())
        with self.assertRaises(HTTPException) as error:
            main.admin_user(regular_user)
        self.assertEqual(error.exception.status_code, 403)

    def test_unconfigured_integrations_are_explicit(self):
        state = main.capabilities()
        self.assertFalse(state["tracking"]["external_sharing"])
        self.assertEqual(state["notifications"]["state"], "not_configured")
        self.assertTrue(main.voice_scripts()["scripts"])
        paths = {route.path for route in main.app.routes}
        self.assertIn("/api/routes/risk", paths)
        self.assertIn("/api/admin/reports/{report_id}/status", paths)

    def test_mapping_fallback_never_claims_a_real_route(self):
        user = self.user_from(self.register())
        result = main.route_alternatives(main.RouteInput(origin="Start", destination="Finish"), user)
        self.assertEqual(result["provider_state"], "demo_only")
        self.assertTrue(all(not option["navigable"] and option["risk_score"] is None for option in result["routes"]))

    def test_tap_me_records_checkin_and_returns_to_active_state(self):
        user = self.user_from(self.register())
        journey = main.start_checkins(main.CheckinInput(interval_minutes=5, grace_minutes=5), user)
        response = main.respond_checkin(journey["id"], user)
        self.assertEqual(response["status"], "active")
        status = main.get_checkins(journey["id"], user)
        self.assertEqual(status["events"][0]["response"], "safe")

    def test_track_me_stores_location_until_user_stops(self):
        user = self.user_from(self.register())
        session = main.start_tracking(main.TrackingInput(destination="Home", duration_minutes=30), user)
        main.update_tracking(session["id"], main.LocationUpdate(latitude=12.9, longitude=77.5), user)
        current = main.get_tracking(session["id"], user)
        self.assertEqual(current["last_latitude"], 12.9)
        self.assertFalse(current["external_sharing"])
        stopped = main.stop_tracking(session["id"], user)
        self.assertEqual(stopped["status"], "stopped")
        self.assertTrue(stopped["location_deleted"])

    def test_appeal_reopen_records_audit_and_returns_report_to_review(self):
        user = self.user_from(self.register())
        report = main.create_report(main.ReportInput(category="poor lighting", description="Several lamps are not working on this block."), user)
        main.moderate_report(report["id"], main.ModerationInput(status="under_review", reason="Initial review."), self.admin)
        main.moderate_report(report["id"], main.ModerationInput(status="rejected", reason="Insufficient detail."), self.admin)
        appeal = main.appeal_report(report["id"], main.AppealInput(message="I can provide more detail for an independent review."), user)
        result = main.review_appeal(appeal["id"], "reopen", self.admin)
        self.assertEqual(result["report_status"], "under_review")
        with db.connect() as connection:
            status = connection.execute("SELECT status FROM reports WHERE id=?", (report["id"],)).fetchone()[0]
            audit_count = connection.execute("SELECT COUNT(*) FROM audit_logs WHERE target_id=?", (appeal["id"],)).fetchone()[0]
        self.assertEqual(status, "under_review")
        self.assertEqual(audit_count, 1)

    def test_moderation_requires_intermediate_review_states(self):
        user = self.user_from(self.register())
        report = main.create_report(main.ReportInput(category="other", description="Please review this environmental concern."), user)
        with self.assertRaises(HTTPException) as error:
            main.moderate_report(report["id"], main.ModerationInput(status="validated", reason="Directly set."), self.admin)
        self.assertEqual(error.exception.status_code, 409)

    def test_admin_place_listing_requires_source_and_is_searchable(self):
        admin = self.admin
        place = main.create_place(main.PlaceInput(name="Test support venue", category="support", address="Sample address",
                                                   latitude=12.97, longitude=77.59, source="Unit-test directory",
                                                   verified_at="2026-11-10T00:00:00Z"), admin)
        result = main.nearby_places(latitude=12.97, longitude=77.59, category="support", radius_km=1, user=self.user_from(self.register()))
        self.assertEqual(result["places"][0]["id"], place["id"])


if __name__ == "__main__":
    unittest.main()

"""Phase 1: the readiness probe proves the database answers and the schema is at the migration head."""


def test_ready_reports_a_migrated_database(api):
    response = api.get("/api/ready")
    assert response.status == 200
    body = response.json()
    assert (body["status"], body["database"]) == ("ready", "ok")
    assert body["migration"]
    assert body["timezone"] == "America/New_York"  # clients format and parse times in the server's zone


def test_the_server_runs_in_the_time_zone_the_tests_assume(api):
    # scripts/verify.py starts the server in America/New_York so the calendar tests exercise real
    # daylight-saving arithmetic. If this fails, the server was started with a different APP_TIMEZONE.
    assert api.get("/api/calendar/month?year=2031&month=1").json()["timezone"] == "America/New_York"

"""Phase 0: the server answers, echoes request IDs, and keeps OpenAPI under /api."""


def test_health_returns_ok(api):
    response = api.get("/api/health")
    assert response.status == 200
    assert response.json() == {"status": "ok"}


def test_request_id_is_echoed(api):
    response = api.get("/api/health", headers={"X-Request-ID": "e2e-fixed-id"})
    assert response.headers["x-request-id"] == "e2e-fixed-id"


def test_openapi_lives_under_the_api_prefix(api):
    schema = api.get("/api/openapi.json").json()
    assert "/api/health" in schema["paths"]

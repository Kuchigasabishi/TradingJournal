import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def make_client(**overrides) -> TestClient:
    options = {"app_env": "test", "database_url": "sqlite://", "auto_migrate": False, **overrides}
    return TestClient(create_app(Settings(_env_file=None, **options)))


def http_records(caplog):
    caplog.set_level(logging.INFO, logger="app.http")
    return lambda: [r for r in caplog.records if r.name == "app.http"]


def test_health_is_ok_and_logged_with_a_request_id(caplog):
    records = http_records(caplog)
    response = make_client().get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    record = records()[-1]
    assert record.request_id == response.headers["x-request-id"]
    assert (record.method, record.path, record.status, record.levelno) == ("GET", "/api/health", 200, logging.INFO)
    assert record.duration_ms >= 0


def test_a_safe_inbound_request_id_is_reused():
    response = make_client().get("/api/health", headers={"X-Request-ID": "e2e-1.abc_X"})
    assert response.headers["x-request-id"] == "e2e-1.abc_X"


def test_an_unsafe_inbound_request_id_is_replaced():
    response = make_client().get("/api/health", headers={"X-Request-ID": "bad id with spaces"})
    assert response.headers["x-request-id"] != "bad id with spaces"
    assert len(response.headers["x-request-id"]) == 12


def test_unknown_path_is_a_warning(caplog):
    records = http_records(caplog)
    assert make_client().get("/nope").status_code == 404
    assert records()[-1].levelno == logging.WARNING


def test_unhandled_exception_is_logged_as_an_error_with_status_500(caplog):
    records = http_records(caplog)
    app = make_client().app

    @app.get("/boom")
    def boom():
        raise RuntimeError("kaboom")

    response = TestClient(app, raise_server_exceptions=False).get("/boom")
    assert response.status_code == 500
    record = records()[-1]
    assert (record.status, record.levelno) == (500, logging.ERROR)


def test_openapi_lives_under_the_api_prefix():
    client = make_client()
    schema = client.get("/api/openapi.json")
    assert schema.status_code == 200
    assert "/api/health" in schema.json()["paths"] and "/api/trades" in schema.json()["paths"]
    assert client.get("/openapi.json").status_code == 404
    assert client.get("/docs").status_code == 404


def test_the_docs_page_is_self_contained():
    client = make_client()
    page = client.get("/api/docs")
    assert page.status_code == 200
    assert "/api/docs-assets/swagger-ui-bundle.js" in page.text and "/api/openapi.json" in page.text
    assert "http://" not in page.text and "https://" not in page.text  # nothing is fetched from a CDN
    for asset in ("swagger-ui-bundle.js", "swagger-ui.css"):
        response = client.get(f"/api/docs-assets/{asset}")
        assert response.status_code == 200 and len(response.content) > 10_000


def test_static_dir_is_served_and_the_api_still_wins(tmp_path):
    (tmp_path / "index.html").write_text("<h1>stub page</h1>", encoding="utf-8")
    client = make_client(static_dir=tmp_path)
    assert "stub page" in client.get("/").text
    assert client.get("/api/health").json() == {"status": "ok"}
    assert client.get("/api/docs").status_code == 200


@pytest.fixture
def web(tmp_path):
    (tmp_path / "index.html").write_text("<div id='root'>the app</div>", encoding="utf-8")
    (tmp_path / "_expo").mkdir()
    (tmp_path / "_expo" / "app.js").write_text("console.log('app')", encoding="utf-8")
    return make_client(static_dir=tmp_path)


@pytest.mark.parametrize("path", ["/", "/trades", "/trades/12", "/day/2035-03-10", "/calendar"])
def test_client_side_routes_load_the_app(web, path):
    response = web.get(path)
    assert response.status_code == 200 and "the app" in response.text


def test_real_assets_are_served_and_missing_ones_stay_404(web):
    assert web.get("/_expo/app.js").text == "console.log('app')"
    assert web.get("/_expo/gone.js").status_code == 404  # HTML in place of a script would only hide the bug


def test_unknown_api_paths_are_json_404_not_the_app(web):
    for call in (web.get, web.post, web.delete):
        response = call("/api/nope")
        assert response.status_code == 404 and response.json() == {"detail": "Not Found"}
    assert web.get("/api/trades/").status_code == 404  # no trailing-slash redirect games either


def test_dev_mode_allows_the_expo_dev_server_origin():
    client = make_client(app_env="dev")
    preflight = client.options(
        "/api/trades",
        headers={"Origin": "http://localhost:8081", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type,x-request-id"},
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "http://localhost:8081"
    simple = client.get("/api/health", headers={"Origin": "http://localhost:8081"})
    assert simple.headers["access-control-allow-origin"] == "http://localhost:8081"
    assert "x-request-id" in simple.headers["access-control-expose-headers"].lower()


def test_other_origins_get_no_cors_headers_in_dev():
    response = make_client(app_env="dev").get("/api/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in response.headers


def test_there_is_no_cors_outside_dev():
    for env in ("test", "prod"):
        response = make_client(app_env=env).get("/api/health", headers={"Origin": "http://localhost:8081"})
        assert "access-control-allow-origin" not in response.headers


def test_missing_static_dir_is_logged_and_does_not_crash(caplog):
    client = make_client(static_dir=Path("Z:/definitely/not/here"))
    assert client.get("/api/health").status_code == 200
    assert any(r.getMessage() == "static_dir_missing" for r in caplog.records)

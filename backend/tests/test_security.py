"""Response headers and the request size limit."""
import base64
import hashlib
import re

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.security import APP_CSP, csp_for_page_with_inline_script
from app.main import create_app


@pytest.fixture
def web_client(tmp_path, settings, engine):
    (tmp_path / "index.html").write_text("<!doctype html><title>app</title>")
    web = Settings(**{**settings.model_dump(), "static_dir": tmp_path}, _env_file=None)
    return TestClient(create_app(web, engine))


def test_every_answer_carries_the_common_headers(client):
    for response in (client.get("/api/health"), client.get("/api/nothing-here"), client.get("/api/trades")):
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert "camera=()" in response.headers["permissions-policy"]
        assert response.headers["cross-origin-opener-policy"] == "same-origin"
        assert response.headers["cross-origin-resource-policy"] == "same-origin"


def test_the_api_is_never_cached_but_static_assets_are_left_alone(client):
    assert client.get("/api/trades").headers["cache-control"] == "no-store"
    asset = client.get("/api/docs-assets/swagger-ui.css")
    assert asset.status_code == 200 and "no-store" not in asset.headers.get("cache-control", "")


def test_html_carries_a_policy_that_allows_this_origin_and_nothing_else(web_client):
    page = web_client.get("/")
    assert page.headers["content-security-policy"] == APP_CSP
    policy = dict(part.strip().split(" ", 1) for part in APP_CSP.split(";"))
    assert policy["default-src"] == "'self'" and policy["script-src"] == "'self'" and policy["frame-ancestors"] == "'none'"
    assert policy["object-src"] == "'none'" and policy["connect-src"] == "'self'"
    assert "content-security-policy" not in web_client.get("/api/health").headers  # JSON has nothing to execute


def test_the_docs_page_allows_its_one_inline_script_by_hash(client):
    page = client.get("/api/docs")
    inline = re.findall(r"<script>(.*?)</script>", page.text, re.DOTALL)
    assert len(inline) == 1, "Swagger UI starts with exactly one inline script"
    digest = base64.b64encode(hashlib.sha256(inline[0].encode()).digest()).decode()
    policy = page.headers["content-security-policy"]
    assert f"script-src 'self' 'sha256-{digest}'" in policy
    assert "unsafe-inline" not in policy.split("style-src")[0]  # scripts never get the blanket allowance


def test_an_inline_script_is_hashed_and_nothing_else_is_loosened():
    policy = csp_for_page_with_inline_script("<script>alert(1)</script><script src='/x.js'></script>")
    assert policy.count("sha256-") == 1
    assert policy.replace(" 'sha256-" + policy.split("sha256-")[1].split("'")[0] + "'", "") == APP_CSP


def test_a_body_over_the_limit_is_refused_before_it_is_read(settings, engine):
    small = TestClient(create_app(Settings(**{**settings.model_dump(), "max_request_bytes": 2048}, _env_file=None), engine))
    refused = small.post("/api/notes", content=b"x" * 5000, headers={"content-type": "application/json"})
    assert refused.status_code == 413
    assert refused.json() == {"detail": "The request body is larger than this server accepts."}
    assert refused.headers["x-request-id"], "the request logger saw it, like any other request"
    assert small.post("/api/notes", json={"day": "2044-05-11", "body": "short"}).status_code == 201  # a normal request still works


def test_a_chunked_body_is_counted_as_it_arrives(settings, engine):
    small = TestClient(create_app(Settings(**{**settings.model_dump(), "max_request_bytes": 2048}, _env_file=None), engine))

    def chunks():
        for _ in range(10):
            yield b"y" * 500  # no Content-Length: the size is only known by counting

    refused = small.post("/api/notes", content=chunks(), headers={"content-type": "application/json"})
    assert refused.status_code == 413


def test_the_limit_has_a_floor_so_it_cannot_lock_the_journal_out():
    with pytest.raises(ValueError):
        Settings(max_request_bytes=10, _env_file=None)
    assert Settings(_env_file=None).max_request_bytes == 1_048_576

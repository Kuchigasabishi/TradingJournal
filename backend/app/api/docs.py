"""Swagger UI served from vendored assets, so /api/docs works offline and verification never leaves the machine."""
from pathlib import Path

from fastapi import APIRouter
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse

from app.core.security import csp_for_page_with_inline_script

SWAGGER_DIR = Path(__file__).resolve().parents[1] / "static" / "swagger"
ASSETS_URL = "/api/docs-assets"

router = APIRouter()


@router.get("/api/docs", include_in_schema=False)
def swagger_ui() -> HTMLResponse:
    page = get_swagger_ui_html(
        openapi_url="/api/openapi.json",
        title="Trading Journal API",
        swagger_js_url=f"{ASSETS_URL}/swagger-ui-bundle.js",
        swagger_css_url=f"{ASSETS_URL}/swagger-ui.css",
        swagger_favicon_url="data:,",
    )
    # The page starts Swagger UI with one inline script. The policy allows exactly that script, by its hash.
    page.headers["content-security-policy"] = csp_for_page_with_inline_script(page.body.decode())
    return page

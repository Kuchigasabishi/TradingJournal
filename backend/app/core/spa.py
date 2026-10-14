"""Static hosting for the exported single-page web app."""
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope


class SpaStaticFiles(StaticFiles):
    """Serves the web build and answers client-side routes with index.html.

    Opening /trades/12 directly, or reloading on it, must load the app, which then routes on the
    client. A path whose last segment has a file extension is a real asset request, though, so a
    missing one stays a 404: answering a gone .js file with HTML would only hide the problem behind
    a confusing syntax error in the browser.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or "." in path.rsplit("/", 1)[-1]:
                raise
            return await super().get_response("index.html", scope)

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import IntegrityError
from sqlalchemy import text
from starlette.exceptions import HTTPException
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from bob import __version__, migrate, services
from bob.api import routers
from bob.config import Settings, load_settings
from bob.db import make_engine, make_sessionmaker
from bob.ratelimit import AttemptLimiter
from bob.security import SameOriginWrites, SecurityHeaders

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
SWAGGER_DIR = Path(__file__).resolve().parent / "static" / "swagger-ui"
SESSION_DAYS = 14


class WebFiles(StaticFiles):
    """Serves web/, whose 404.html answers unknown page addresses; unknown API paths keep the JSON 404."""

    async def get_response(self, path: str, scope):
        # Starlette hands over an os.path.normpath() result, so the separator is the platform's.
        if Path(path).parts[:1] == ("api",):
            raise HTTPException(status_code=404)
        if path in (".", "index.html"):
            # The version in the script and style links makes a browser drop files cached from an older release.
            page = (WEB_DIR / "index.html").read_text(encoding="utf-8").replace("__BOB_VERSION__", __version__)
            return HTMLResponse(page, headers={"Cache-Control": "no-cache"})
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    engine = make_engine(settings.database_url)
    if settings.auto_migrate:
        migrate.upgrade(engine)
    sessionmaker = make_sessionmaker(engine)
    with sessionmaker() as db:
        services.sync_builtin_mappings(db)
        if settings.seed_demo:
            from bob.seed import seed_demo

            seed_demo(db, settings)

    app = FastAPI(title="BOB: Biological Omnimodal Bank", version=__version__, docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = sessionmaker
    app.state.limiter = AttemptLimiter()

    app.add_middleware(SameOriginWrites)
    app.add_middleware(SecurityHeaders)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie="bob_session",
        same_site="lax",
        https_only=settings.secure_cookies,
        max_age=SESSION_DAYS * 24 * 3600,
    )
    # A Host allowlist stops DNS rebinding, where a hostile page reaches a local BOB under its own name.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts))
    if settings.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_credentials=False,
                           allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type"])
    for router in routers:
        app.include_router(router)

    @app.exception_handler(IntegrityError)
    async def _conflict(_request, _exc):
        # Two requests racing past the same uniqueness check, such as a double-clicked star.
        return JSONResponse({"detail": "That conflicts with a change made at the same moment. Please try again."}, status_code=409)

    @app.get("/health")
    def health():
        return {"status": "ok", "version": __version__, "mode": settings.mode}

    @app.get("/livez", include_in_schema=False)
    def liveness():
        return {"status": "ok", "version": __version__}

    @app.get("/readyz", include_in_schema=False)
    def readiness():
        problems = []
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except Exception:
            problems.append("database unavailable")
        if not settings.artifact_dir.is_dir() or not os.access(settings.artifact_dir, os.W_OK):
            problems.append("artifact storage is not writable")
        if not settings.auto_migrate and not migrate.is_current(engine):
            problems.append("database migrations are not current")
        if problems:
            return JSONResponse({"status": "not ready", "problems": problems}, status_code=503)
        return {"status": "ready", "version": __version__, "mode": settings.mode}

    app.mount("/docs-static", StaticFiles(directory=SWAGGER_DIR), name="docs-static")

    @app.get("/docs", include_in_schema=False)
    def docs():
        return get_swagger_ui_html(
            openapi_url=app.openapi_url,
            title=app.title + " API",
            swagger_js_url="/docs-static/swagger-ui-bundle.js",
            swagger_css_url="/docs-static/swagger-ui.css",
            swagger_favicon_url="/docs-static/favicon-32x32.png",
            # The default validator badge fetches from validator.swagger.io.
            swagger_ui_parameters={"validatorUrl": None},
        )

    if settings.mode == "full" and WEB_DIR.exists():
        app.mount("/", WebFiles(directory=WEB_DIR, html=True), name="web")
    return app

"""Application factory and ASGI entrypoint."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.v1 import auth as auth_routes
from app.api.v1 import brokers as broker_routes
from app.api.v1 import clusters as cluster_routes
from app.api.v1 import groups as group_routes
from app.api.v1 import health as health_routes
from app.api.v1 import meta as meta_routes
from app.api.v1 import topics as topic_routes
from app.auth.rbac import AuthorizationError, ReadOnlyError
from app.auth.sessions import SessionCodec
from app.bootstrap import ensure_first_admin
from app.clusters.loader import ClusterConfigError
from app.clusters.registry import ClusterRegistry, UnknownClusterError
from app.config import Settings, load_settings
from app.kafka.gates import GateRegistry
from app.logging import configure_logging, get_logger
from app.store.session import create_db_engine, init_db

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings

    engine = create_db_engine(settings.database_url)
    init_db(engine)
    app.state.engine = engine

    ensure_first_admin(engine, settings)

    try:
        registry = ClusterRegistry.from_file(settings.clusters_file)
    except ClusterConfigError as exc:
        # Misconfiguration must fail loudly at startup, not on first request.
        log.error("cluster_config_invalid", error=str(exc))
        raise
    app.state.registry = registry

    app.state.gates = GateRegistry(
        registry,
        timeout_seconds=settings.admin_timeout_seconds,
        cache_ttl_seconds=settings.admin_cache_ttl_seconds,
        pool_size=settings.admin_pool_size,
    )

    app.state.session_codec = SessionCodec(
        secret=settings.session_secret,
        max_age_seconds=settings.session_max_age_seconds,
    )

    if settings.is_no_auth:
        log.warning(
            "authentication_disabled",
            detail=(
                "AUTH_MODE=none: every visitor has full admin rights. "
                "Never use this outside local development."
            ),
        )

    log.info(
        "startup_complete",
        version=__version__,
        auth_mode=str(settings.auth_mode),
        read_only=settings.read_only,
        clusters=len(registry),
        theme=settings.theme,
    )

    yield

    app.state.gates.close()
    engine.dispose()
    log.info("shutdown_complete")


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(UnknownClusterError)
    async def _unknown_cluster(_request: Request, exc: UnknownClusterError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ReadOnlyError)
    async def _read_only(_request: Request, exc: ReadOnlyError) -> JSONResponse:
        return JSONResponse(
            status_code=403,
            content={"detail": exc.message, "reason": "read_only"},
        )

    @app.exception_handler(AuthorizationError)
    async def _forbidden(_request: Request, exc: AuthorizationError) -> JSONResponse:
        return JSONResponse(
            status_code=403,
            content={
                "detail": exc.message,
                "required_role": str(exc.required_role) if exc.required_role else None,
            },
        )


def _mount_frontend(app: FastAPI, settings: Settings) -> None:
    """Serve the built SPA, plus the active theme's brand assets.

    Missing static files are not an error: running the backend alone against a
    Vite dev server is the normal development loop.
    """
    theme_dir = settings.theme_dir
    if theme_dir.is_dir():
        app.mount("/brand", StaticFiles(directory=theme_dir), name="brand")

    static_dir = settings.static_dir
    if not static_dir.is_dir():
        log.info("frontend_bundle_absent", detail="serving API only", path=str(static_dir))
        return

    assets = static_dir / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    index = static_dir / "index.html"

    # response_model=None is required: the return annotation is a union of two
    # Response subclasses, and without this FastAPI tries to build a Pydantic
    # response model from it and refuses to start.
    @app.get("/{full_path:path}", include_in_schema=False, response_model=None)
    async def spa(full_path: str) -> FileResponse | JSONResponse:
        # Anything under /api that reaches here is a genuine 404, not a route
        # for the SPA to handle.
        if full_path.startswith(("api/", "ws/")):
            return JSONResponse(status_code=404, content={"detail": "not found"})

        candidate = (static_dir / full_path).resolve()
        # Refuse to serve anything outside the bundle, so a crafted path like
        # ../../etc/passwd cannot escape.
        if full_path and candidate.is_file() and candidate.is_relative_to(static_dir.resolve()):
            return FileResponse(candidate)
        return FileResponse(index)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    configure_logging(settings)

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description="A self-hosted web console for operating any Apache Kafka cluster.",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
        root_path=settings.root_path,
        lifespan=lifespan,
    )
    app.state.settings = settings

    # Probes live at the root so container healthchecks stay simple.
    app.include_router(health_routes.router)

    v1 = APIRouter(prefix="/api/v1")
    v1.include_router(meta_routes.router)
    v1.include_router(auth_routes.router)
    v1.include_router(cluster_routes.router)
    v1.include_router(broker_routes.router)
    v1.include_router(topic_routes.router)
    v1.include_router(group_routes.router)
    app.include_router(v1)

    _register_exception_handlers(app)
    _mount_frontend(app, settings)

    return app


# Note: no module-level `app = create_app()`. Building the app at import time
# would make `import app.main` fail whenever the environment is incomplete,
# which breaks tests, ruff, and mypy. Serve with the factory instead:
#
#     uvicorn app.main:create_app --factory

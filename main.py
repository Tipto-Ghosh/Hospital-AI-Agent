from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.config import get_settings
from app.logger import logging

settings = get_settings()

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    startup_start = time.monotonic()

    from app.db.base import close_db, init_db
    try:
        await init_db()
        logging.info("✓ Database connection verified.")
    except RuntimeError as exc:
        logging.critical(f"✗ Database startup check failed: {exc}")
        raise

    redis_client = None
    try:
        from app.api.dependencies import get_redis_pool
        redis_client = await get_redis_pool()
        await redis_client.ping()
        logging.info("✓ Redis connection verified.")
    except Exception as exc:
        logging.warning(
            f"⚠ Redis ping failed: {exc} — session features will be unavailable."
        )

    _configure_observability()

    elapsed = time.monotonic() - startup_start
    logging.info(
        f"✓ {settings.HOSPITAL_NAME} is ready. Startup completed in {elapsed:.2f}s."
    )

    yield

    logging.info(f"Shutting down {settings.HOSPITAL_NAME} ...")
    await close_db()
    logging.info("✓ Database pool closed.")

    if redis_client is not None:
        try:
            await redis_client.aclose()
            logging.info("✓ Redis pool closed.")
        except Exception as exc:
            logging.warning(f"Redis close error (non-fatal): {exc}")

    logging.info("Shutdown complete.")


def _configure_observability() -> None:
    obs = settings.obs

    if obs.langsmith_enabled:
        try:
            import os
            os.environ["LANGCHAIN_TRACING_V2"] = "true"
            os.environ["LANGCHAIN_ENDPOINT"]   = str(obs.LANGSMITH_ENDPOINT)
            os.environ["LANGCHAIN_API_KEY"]    = obs.LANGSMITH_API_KEY or ""
            os.environ["LANGCHAIN_PROJECT"]    = obs.LANGSMITH_PROJECT
            logging.info(f"✓ LangSmith tracing enabled (project={obs.LANGSMITH_PROJECT!r}).")
        except Exception as exc:
            logging.warning(f"LangSmith init failed (non-fatal): {exc}")

    if obs.langfuse_enabled:
        try:
            from langfuse.langchain import CallbackHandler  # noqa: F401
            logging.info("✓ Langfuse tracing enabled.")
        except ImportError:
            logging.warning(
                "Langfuse keys set but langfuse package not installed. "
                "Run: pip install langfuse"
            )
        except Exception as exc:
            logging.warning(f"Langfuse init failed (non-fatal): {exc}")


class CorrelationIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = (
            request.headers.get("X-Request-ID") or str(uuid.uuid4())
        )
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class StructuredLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in ("/api/v1/health", "/health"):
            return await call_next(request)

        start = time.monotonic()
        response = await call_next(request)
        duration_ms = round((time.monotonic() - start) * 1000, 1)

        logging.info(
            f"HTTP {request.method} {request.url.path} → {response.status_code}  {duration_ms:.1f}ms  "
            f"req_id={getattr(request.state, 'request_id', '-')}  "
            f"ip={request.client.host if request.client else '-'}"
        )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    EXEMPT_PATHS = {"/api/v1/health", "/health", "/api/v1/emergency", "/api/v1/metrics"}

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self._buckets: dict[str, tuple[int, float]] = {}
        self._limit = settings.security.RATE_LIMIT_PER_MINUTE

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in self.EXEMPT_PATHS:
            return await call_next(request)

        ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        count, window_start = self._buckets.get(ip, (0, now))

        if now - window_start >= 60:
            count = 0
            window_start = now

        count += 1
        self._buckets[ip] = (count, window_start)

        if count > self._limit:
            return JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limit_exceeded",
                    "message": (
                        f"Too many requests. Limit: {self._limit} per minute. "
                        "Please wait before sending another message."
                    ),
                    "request_id": getattr(request.state, "request_id", None),
                },
                headers={"Retry-After": "60"},
            )

        return await call_next(request)


async def _validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": "validation_error",
            "message": "Request validation failed.",
            "detail": exc.errors(),
            "request_id": getattr(request.state, "request_id", None),
        },
    )


async def _http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": _status_to_error_code(exc.status_code),
            "message": exc.detail,
            "request_id": getattr(request.state, "request_id", None),
        },
    )


async def _unhandled_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    logging.exception(
        f"Unhandled exception for {request.method} {request.url.path} (req_id={request_id})"
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_server_error",
            "message": (
                "An unexpected error occurred. Our team has been notified. "
                f"Reference: {request_id}"
            ),
            "request_id": request_id,
        },
    )


def _status_to_error_code(status: int) -> str:
    return {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        405: "method_not_allowed",
        409: "conflict",
        422: "validation_error",
        429: "rate_limit_exceeded",
        500: "internal_server_error",
        503: "service_unavailable",
    }.get(status, "error")


def _setup_prometheus(app: FastAPI) -> None:
    try:
        from prometheus_fastapi_instrumentator import Instrumentator
        Instrumentator(
            should_group_status_codes=True,
            should_ignore_untemplated=True,
            should_respect_env_var=True,
            should_instrument_requests_inprogress=True,
            excluded_handlers=["/api/v1/health", "/api/v1/metrics"],
        ).instrument(app).expose(app, endpoint="/api/v1/metrics")
        logging.info("✓ Prometheus metrics enabled at /api/v1/metrics")
    except ImportError:
        from fastapi.routing import APIRouter
        metrics_router = APIRouter()

        @metrics_router.get("/api/v1/metrics", include_in_schema=False)
        async def metrics_stub() -> JSONResponse:
            return JSONResponse(
                {"info": "prometheus-fastapi-instrumentator not installed."},
                status_code=200,
            )

        app.include_router(metrics_router)
        logging.warning(
            "prometheus-fastapi-instrumentator not installed — "
            "metrics endpoint returns a stub. Run: pip install prometheus-fastapi-instrumentator"
        )


def _register_routers(app: FastAPI) -> None:
    from fastapi.routing import APIRouter

    health_router = APIRouter(tags=["System"])

    @health_router.get("/api/v1/health", summary="System health check")
    async def health() -> dict:
        return {
            "status": "healthy",
            "hospital": settings.HOSPITAL_NAME,
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT,
        }

    app.include_router(health_router)

    _try_include(app, "app.api.routes.chat",          "/api/v1",    ["Chat"])
    _try_include(app, "app.api.routes.appointments",  "/api/v1",    ["Appointments"])
    _try_include(app, "app.api.routes.doctors",       "/api/v1",    ["Doctors"])
    _try_include(app, "app.api.routes.auth",          "/api/v1",    ["Authentication"])
    _try_include(app, "app.api.routes.admin",         "/admin/v1",  ["Admin"])


def _try_include(
    app: FastAPI,
    module_path: str,
    prefix: str,
    tags: list[str],
) -> None:
    try:
        import importlib
        module = importlib.import_module(module_path)
        router = getattr(module, "router")
        app.include_router(router, prefix=prefix, tags=tags)
        logging.debug(f"Router mounted: {module_path} → {prefix}")
    except ModuleNotFoundError:
        logging.debug(
            f"Router {module_path} not yet implemented — skipping (expected during Phase 1)."
        )
    except AttributeError:
        logging.warning(
            f"Module {module_path} has no 'router' attribute — skipping."
        )


def create_app() -> FastAPI:
    app = FastAPI(
        title=f"{settings.HOSPITAL_NAME} — AI Assistant API",
        description=(
            "Multi-agent hospital AI system. "
            "Handles appointment booking, patient records, billing, "
            "medication information, and emergency triage."
        ),
        version=settings.APP_VERSION,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        openapi_url="/openapi.json" if not settings.is_production else None,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.security.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(StructuredLoggingMiddleware)
    app.add_middleware(CorrelationIDMiddleware)

    app.add_exception_handler(RequestValidationError, _validation_exception_handler)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(Exception, _unhandled_exception_handler)

    _setup_prometheus(app)

    _register_routers(app)

    logging.info(
        f"FastAPI app created | env={settings.ENVIRONMENT} | "
        f"docs={'enabled' if not settings.is_production else 'disabled (production)'}"
    )

    return app


app = create_app()
from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core import security
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger, request_id_var
from app.routers import auth, imports, market, portfolio, reports, status, users, watchlist

settings = get_settings()
configure_logging(settings.log_level)
log = get_logger("foliolens")
settings.validate()  # fail fast on missing/weak secrets

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from app.db.session import SessionLocal
    from app.routers.imports import purge_expired_uploads

    with SessionLocal() as db:
        try:
            purged = purge_expired_uploads(db)
            if purged:
                log.info(f"purged {purged} expired CSV uploads")
        except Exception:  # noqa: BLE001 - tables may not exist before the first migration
            log.warning("could not purge expired uploads (run `alembic upgrade head`)")
    yield


app = FastAPI(
    title="FolioLens API",
    version="2.0.0",
    description="Portfolio health analysis with live market data, news and evidence-based decision-support signals. "
                "Authenticate with POST /api/auth/login (cookie session) or an `Authorization: Bearer` access token.",
    lifespan=lifespan,
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None,
    openapi_url=None if settings.is_production else "/openapi.json",
)


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
    if not rid.isalnum() or len(rid) > 64:
        rid = uuid.uuid4().hex[:16]
    request_id_var.set(rid)
    start = time.perf_counter()

    if settings.force_https and request.headers.get("x-forwarded-proto", request.url.scheme) != "https":
        if request.method in ("GET", "HEAD"):
            return RedirectResponse(str(request.url.replace(scheme="https")), status_code=308)
        return JSONResponse({"detail": "HTTPS is required."}, status_code=403)

    # CSRF (double-submit cookie) for cookie-authenticated state-changing requests.
    if (request.method in UNSAFE_METHODS and request.url.path.startswith("/api/")
            and not request.headers.get("Authorization", "").lower().startswith("bearer ")):
        if not security.csrf_matches(request.cookies.get(security.CSRF_COOKIE), request.headers.get(security.CSRF_HEADER)):
            return JSONResponse({"detail": "Missing or invalid CSRF token. Reload the page and try again.",
                                 "request_id": rid}, status_code=403)

    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    if settings.force_https:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    log.info("request", extra={"method": request.method, "path": request.url.path, "status": response.status_code,
                               "duration_ms": round((time.perf_counter() - start) * 1000, 1),
                               "user_id": getattr(request.state, "user_id", None)})
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", security.CSRF_HEADER, "Authorization", "X-Request-ID"],
    expose_headers=["X-Request-ID", "Content-Disposition"],
)
if settings.trusted_hosts != ["*"]:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)


# ------------------------------------------------------------------ consistent, safe error bodies

@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    return JSONResponse({"detail": exc.detail, "request_id": request_id_var.get()}, status_code=exc.status_code,
                        headers=getattr(exc, "headers", None))


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    errors = [{"field": ".".join(str(p) for p in e.get("loc", [])[1:]), "message": e.get("msg")} for e in exc.errors()]
    first = errors[0] if errors else {"field": "", "message": "Invalid request"}
    msg = f"{first['field']}: {first['message']}" if first["field"] else first["message"]
    return JSONResponse({"detail": msg, "errors": errors, "request_id": request_id_var.get()}, status_code=422)


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception):
    # Logged with type + request id only; no stack trace or internals are sent to the client.
    log.error("unhandled error", exc_info=exc, extra={"path": request.url.path})
    return JSONResponse({"detail": "An unexpected error occurred. Please try again.",
                         "request_id": request_id_var.get()}, status_code=500)


for r in (auth.router, users.router, portfolio.router, imports.router, market.router, watchlist.router,
          reports.router, status.router):
    app.include_router(r)


@app.get("/", include_in_schema=False)
def root():
    return {"status": "ok", "service": "FolioLens API", "docs": None if settings.is_production else "/docs"}



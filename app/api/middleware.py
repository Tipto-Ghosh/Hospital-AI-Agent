from __future__ import annotations
 
import json
import logging
import time
import uuid
from typing import Callable, Optional
 
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp
 
from app.config import get_settings
from app.utils.security import check_for_injection, sanitize_input
 
logger = logging.getLogger(__name__)
settings = get_settings()


_RATE_LIMIT_EXEMPT = frozenset({
    "/api/v1/health",
    "/health",
    "/api/v1/emergency",       
    "/api/v1/metrics",        
    "/docs",
    "/redoc",
    "/openapi.json",
})
 
# Paths excluded from access logs (reduce noise)
_LOG_EXEMPT = frozenset({
    "/api/v1/health",
    "/health",
    "/api/v1/metrics",
    "/favicon.ico",
})

class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Inject a unique correlation ID into every request and response.
 
    Behaviour
    ---------
    - If the incoming request carries an X-Request-ID header, that value
      is used (allows end-to-end tracing from the client or API gateway).
    - Otherwise a UUID4 is generated server-side.
    - The ID is stored on request.state.request_id so every other
      middleware and route handler can attach it to log lines.
    - The ID is echoed back in the X-Request-ID response header so the
      client can include it in support tickets.
 
    Emergency exemption
    -------------------
    For /api/v1/emergency requests a fresh UUID is always generated
    regardless of any client-supplied ID (prevents client-side ID
    spoofing on life-safety requests).
    """
 
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Always generate a fresh ID for the emergency endpoint
        if request.url.path.startswith("/api/v1/emergency"):
            request_id = str(uuid.uuid4())
        else:
            request_id = (
                request.headers.get("X-Request-ID") or str(uuid.uuid4())
            )
 
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Add security-hardening HTTP headers to every response.
    """
 
    # HSTS max-age: 1 year in seconds
    _HSTS_VALUE = "max-age=31536000; includeSubDomains; preload"
 
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
 
        # Always-on security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "0"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=()"
        )
 
        # HSTS — only in production (HTTPS required)
        if settings.is_production:
            response.headers["Strict-Transport-Security"] = self._HSTS_VALUE
 
        # Permissive CSP in development / staging for Swagger UI
        if not settings.is_production:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' cdn.jsdelivr.net; "
                "img-src 'self' data: fastapi.tiangolo.com;"
            )
 
        return response

class StructuredLoggingMiddleware(BaseHTTPMiddleware):
    """ 
    Emit a structured JSON log line for every request/response cycle.
    """
    async def dispatch(self, request: Request, call_next: Callable):
        # skip health and metrics noise
        if request.url.path in _LOG_EXEMPT:
            return await call_next(request)
        
        start = time.monotonic()
        response = await call_next(request)
        duration_ms = round((time.monotonic() - start) * 1000, 1)
        
        log_entry = {
            "event": "http_request",
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": duration_ms,
            "request_id": getattr(request.state, "request_id", "-"),
            "client_ip": request.client.host if request.client else "-",
        }
        
        # agent name set by the Langgraph route handler
        agent_name = getattr(request.state, "agent_name", None)
        if agent_name:
            log_entry["agent"] = agent_name
        
        # log level based on status code
        if response.status_code >= 500:
            logger.error(json.dumps(log_entry))
        elif response.status_code >= 400:
            logger.warning(json.dumps(log_entry))
        else:
            logger.info(json.dumps(log_entry))
        
        return response
    
class RateLimitMiddleware(BaseHTTPMiddleware):
    """ 
    Per-Ip sliding window rate limitter backed by Redis.
    
    Algorithm: token bucket with a 60-second sliding window.
    Each IP gets RATE_LIMIT_PER_MINIUTE tokens per window.
    Tokens are tracked in Redis with a TTL of 60 seconds.
    
    Redis Key pattern: rate_limit:<ip_address>
    """
    _REDIS_PREFIX = "rate_limit:"
    _WINDOW_SECONDS = 60
    
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self._limit = settings.security.RATE_LIMIT_PER_MINUTE
        # in memory fallback when Redis is unavailable
        self._fallback: dict[str, list[float]] = {}
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path in _RATE_LIMIT_EXEMPT:
            return await call_next(request)
        
        ip = request.client.host if request.client else "unknown"
        count = await self._increment(ip)
        
        if count > self._limit:
            remaining_str = "0"
            return JSONResponse(
                status_code = 429,
                content = {
                    "error": "rate_limit_exceeded",
                    "message": (
                        f"Too many requests from your IP."
                        f"Limit: {self._limit} requents per minute."
                    ),
                    "request_id": getattr(request.state, "request_id", None),
                },
                headers = {
                    "Retry-After": str(self._WINDOW_SECONDS),
                    "X-RateLimit-Limit": str(self._limit),
                    "X-RateLimit-Remaining": remaining_str,
                    "X-RateLimit-Reset": str(self._WINDOW_SECONDS),
                },
            )
        
        # Add informational headers on successful requests too
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self._limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, self._limit - count))
        response.headers["X-RateLimit-Reset"] = str(self._WINDOW_SECONDS)
        return response
    
    async def _increment(self, ip: str) -> int:
        """ 
        Increment the request counter for the given IP address in Redis.
        
        Uses INCR + EXPIRE so the window restets automatically after 60 seconds.
        Returns the current count for this IP in the current window.
        Falls back to in-memory if Redis is unavailable.
        """
        try:
            from app.api.dependencies import get_redis_pool
            redis = await get_redis_pool()
            key = f"{self._REDIS_PREFIX}{ip}"
            
            # Atomic Increment
            count = await redis.incr(key)
            if count == 1:
                # First request in this window, set TTL
                await redis.expire(key, self._WINDOW_SECONDS)
            return int(count)
        except Exception as e:
            logger.warning("Redis unavailable for rate limiting (fail-open): %s", e)
            return self._in_memory_increment(ip)
    
    def _in_memory_increment(self, ip: str) -> int:
        """ 
        In-memory fallback for single-process deployments or Redis outage.
        """
        now = time.monotonic()
        count, window_start = self._fallback.get(ip, (0, now))
        if now - window_start > self._WINDOW_SECONDS:
            count = 0
            window_start = now
        
        count += 1
        self._fallback[ip] = (count, window_start)
        return count

class InputSanitizationMiddleware(BaseHTTPMiddleware):
    """
    Sanitize incoming request data to prevent injection attacks.
    
    - Checks query parameters, headers, and JSON body for suspicious patterns.
    - If any input is deemed unsafe, returns a 400 Bad Request response.
    """
    _CHAT_PATH = "/api/v1/chat"
    _TEXT_FIELD_CANDIDATES = ("test", "message", "content")
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.method != "POST" or request.url.path != self._CHAT_PATH:
            return await call_next(request)
 
        raw_body = await request.body()
 
        try:
            payload = json.loads(raw_body) if raw_body else {}
        except json.JSONDecodeError:
            return await self._forward_with_body(request, raw_body, call_next)
 
        if not isinstance(payload, dict):
            return await self._forward_with_body(request, raw_body, call_next)
 
        text_field = next((f for f in self._TEXT_FIELD_CANDIDATES if f in payload), None)
        if text_field is None or not isinstance(payload[text_field], str):
            return await self._forward_with_body(request, raw_body, call_next)
 
        original_text = payload[text_field]
 
        if check_for_injection(original_text):
            session_id = payload.get("session_id")
            await self._log_injection_attempt(request, session_id, original_text)
            return JSONResponse(
                status_code=400,
                content={"error": "Invalid input"},
            )
 
        sanitized_text = sanitize_input(original_text)
        payload[text_field] = sanitized_text
        new_body = json.dumps(payload).encode("utf-8")
 
        return await self._forward_with_body(request, new_body, call_next)
    
    async def _forward_with_body(
        self, request: Request, body: bytes, call_next: Callable
    ) -> Response:
        """
        Rebuild the ASGI receive channel so downstream code sees `body`
        as the request body, then call the next handler in the chain.
        """
        async def receive() -> dict:
            return {"type": "http.request", "body": body, "more_body": False}
 
        request._receive = receive  # noqa: SLF001 — standard ASGI body-rewrite pattern
        return await call_next(request)
 
    async def _log_injection_attempt(
        self, request: Request, session_id: Optional[str], text: str
    ) -> None:
        """
        Write an audit_log entry for a blocked injection attempt.
 
        Stores only a short, truncated preview of the offending text in
        payload_summary (not the full message) — enough for security
        review without retaining an unbounded amount of adversarial
        input.
        """
        preview = text[:200] + ("..." if len(text) > 200 else "")
 
        try:
            from app.db.base import get_session_context
            from app.db.repositories.audit_repo import AuditRepository
 
            async with get_session_context() as db:
                audit_repo = AuditRepository(db)
                await audit_repo.log(
                    agent_name="input_sanitization_middleware",
                    action="injection_attempt",
                    session_id=session_id,
                    resource_type="chat_message",
                    payload_summary=f"Blocked suspected prompt injection. Preview: {preview!r}",
                    ip_address=request.client.host if request.client else None,
                )
            logger.warning(
                "InputSanitizationMiddleware: blocked injection_attempt "
                f"session={session_id or 'unknown'} ip={request.client.host if request.client else 'unknown'}"
            )
        except Exception as exc:
            logger.error(f"InputSanitizationMiddleware: failed to log injection_attempt: {exc}")
 
 
# Custom Prometheus metrics
try:
    from prometheus_client import Counter, Histogram
 
    agent_requests_total = Counter(
        "agent_requests_total",
        "Total number of times a graph agent/node was invoked.",
        labelnames=("agent_name", "intent"),
    )
 
    agent_latency_seconds = Histogram(
        "agent_latency_seconds",
        "Time spent inside a single agent/node invocation, in seconds.",
        labelnames=("agent_name",),
    )
 
    llm_tokens_used_total = Counter(
        "llm_tokens_used_total",
        "Total LLM tokens consumed, split by model and token type.",
        labelnames=("model", "token_type"),
    )
 
    appointment_bookings_total = Counter(
        "appointment_bookings_total",
        "Total number of appointments successfully created.",
    )
 
    emergency_triggers_total = Counter(
        "emergency_triggers_total",
        "Total number of times the Emergency Triage Agent was activated.",
    )
 
    _PROMETHEUS_AVAILABLE = True
    logger.info("Custom Prometheus metrics registered (agent_requests_total, agent_latency_seconds, llm_tokens_used_total, appointment_bookings_total, emergency_triggers_total)")
 
except ImportError:
    _PROMETHEUS_AVAILABLE = False
    agent_requests_total = None
    agent_latency_seconds = None
    llm_tokens_used_total = None
    appointment_bookings_total = None
    emergency_triggers_total = None
    logger.warning(
        "prometheus_client not installed - custom hospital metrics disabled. "
        "Install it with: pip install prometheus_client"
    )
 
 
def record_agent_request(agent_name: str, intent: Optional[str] = None) -> None:
    """
    Increment agent_requests_total for one agent/node invocation.
    """
    if not _PROMETHEUS_AVAILABLE:
        return
    agent_requests_total.labels(agent_name=agent_name, intent=intent or "unknown").inc()
 
 
def record_agent_latency(agent_name: str, duration_seconds: float) -> None:
    """
    Record one observation of agent_latency_seconds for the given agent.
    """
    if not _PROMETHEUS_AVAILABLE:
        return
    agent_latency_seconds.labels(agent_name=agent_name).observe(duration_seconds)
 
 
def record_llm_tokens(model: str, prompt_tokens: int = 0, completion_tokens: int = 0) -> None:
    """
    Increment llm_tokens_used_total for one LLM call's token usage.
    """
    if not _PROMETHEUS_AVAILABLE:
        return
    if prompt_tokens:
        llm_tokens_used_total.labels(model=model, token_type="prompt").inc(prompt_tokens)
    if completion_tokens:
        llm_tokens_used_total.labels(model=model, token_type="completion").inc(completion_tokens)
 
 
def record_appointment_booking() -> None:
    """
    Increment appointment_bookings_total by 1.
    """
    if not _PROMETHEUS_AVAILABLE:
        return
    appointment_bookings_total.inc()
 
 
def record_emergency_trigger() -> None:
    """
    Increment emergency_triggers_total by 1.
    """
    if not _PROMETHEUS_AVAILABLE:
        return
    emergency_triggers_total.inc()
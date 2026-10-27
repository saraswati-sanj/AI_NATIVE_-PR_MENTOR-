"""FastAPI app: CORS, rate limiting, POST /review and GET /health (DESIGN.md section 7).

Note: this module deliberately does NOT use `from __future__ import annotations`.
slowapi's @limiter.limit wrapper cannot carry this module's globals, so string
annotations would be resolved against slowapi's namespace instead. FastAPI would
then fail to resolve ReviewRequest and silently treat the body as a query
parameter, rejecting every request with a validation error.
"""

import logging
import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from .models import ReviewRequest, ReviewResponse
from .pipeline import run_review

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# DESIGN.md section 4: validation limits.
MAX_LINES = 300
MAX_BYTES = 20 * 1024

_RATE_LIMIT = "10/minute"

# CORS is restricted to the frontend origin (DESIGN.md section 12). The default
# is the Vite dev server, so local development works without any env setup.
_DEFAULT_ORIGIN = "http://localhost:5173"
_frontend_origin = os.environ.get("FRONTEND_ORIGIN", "").strip() or _DEFAULT_ORIGIN
if not os.environ.get("FRONTEND_ORIGIN", "").strip():
    log.warning("FRONTEND_ORIGIN is not set; allowing only %s", _DEFAULT_ORIGIN)

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="PR Mentor AI", version="1.0.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[_frontend_origin],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


def _validate(text: str) -> None:
    """Reject empty and oversized input before any work is done."""
    if not text.strip():
        raise HTTPException(
            status_code=400,
            detail="Paste some Python code or a unified diff to review.",
        )

    size = len(text.encode("utf-8"))
    if size > MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Input is {size / 1024:.1f} KB, over the {MAX_BYTES // 1024} KB limit. "
                "Review a smaller part of the change."
            ),
        )

    lines = len(text.splitlines())
    if lines > MAX_LINES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Input is {lines} lines, over the {MAX_LINES} line limit. "
                "Review a smaller part of the change."
            ),
        )


@app.post("/review", response_model=ReviewResponse)
@limiter.limit(_RATE_LIMIT)
def review(request: Request, body: ReviewRequest) -> ReviewResponse:
    """Run the full review pipeline.

    Defined with `def` rather than `async def` on purpose: the pipeline blocks
    on subprocesses and an HTTP call, so FastAPI runs it in its threadpool
    instead of stalling the event loop for every other request.
    """
    _validate(body.input)
    try:
        return run_review(body.input, body.mode)
    except ValueError as exc:
        # The parser rejects input it cannot handle, e.g. a multi-file diff.
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check for the deployment platform."""
    return {"status": "ok"}


@app.exception_handler(RequestValidationError)
async def _on_invalid_body(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Return 400 for a malformed body, as section 7 specifies, not FastAPI's 422."""
    # Logged in full: the client gets a generic message, but a silently
    # swallowed validation error is almost impossible to debug.
    log.warning("Rejected malformed request body: %s", exc.errors())
    return JSONResponse(
        status_code=400,
        content={
            "detail": 'Body must be {"input": "<code or diff>", '
            '"mode": "auto" | "snippet" | "diff"}.'
        },
    )


@app.exception_handler(Exception)
async def _on_unexpected(request: Request, exc: Exception) -> JSONResponse:
    """Never leak a traceback to the client; log it and return a plain 500."""
    log.exception("Unhandled error while reviewing")
    return JSONResponse(
        status_code=500,
        content={"detail": "Something went wrong while reviewing. Please try again."},
    )

"""RFC 9457 problem details.

Every error this API returns is `application/problem+json` with a bilingual
message, per docs/api_contract.md section 1: "an error a Bangladeshi student
cannot read is a dead end." Bangla strings below are written as natural
sentences, not transliterated English.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict
from starlette.responses import JSONResponse

log = logging.getLogger(__name__)

PROBLEM_BASE = "https://digonto.ahbab.dev/errors"
PROBLEM_MEDIA_TYPE = "application/problem+json"


class ProblemDetail(BaseModel):
    """The wire shape. `model_config` allows extra top-level members, which
    RFC 9457 permits (e.g. a validation error's field-level `errors` list)."""

    model_config = ConfigDict(extra="allow")

    type: str
    title: str
    status: int
    detail_en: str
    detail_bn: str
    instance: str | None = None
    trace_id: str | None = None


class AppError(Exception):
    """Base for every error this API raises deliberately.

    Subclasses set `status_code`, `type_slug`, and `title` as class attributes
    and supply default bilingual copy; callers may override either message
    (a moderator's ban reason, a specific field error) via the constructor.
    """

    status_code: int = 500
    type_slug: str = "internal-error"
    title: str = "Internal error"

    def __init__(
        self,
        detail_en: str,
        detail_bn: str,
        *,
        instance: str | None = None,
        headers: dict[str, str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.detail_en = detail_en
        self.detail_bn = detail_bn
        self.instance = instance
        self.headers = headers or {}
        self.extra = extra
        super().__init__(detail_en)

    def to_problem(self, *, instance: str | None = None, trace_id: str | None = None) -> ProblemDetail:
        fields: dict[str, Any] = {
            "type": f"{PROBLEM_BASE}/{self.type_slug}",
            "title": self.title,
            "status": self.status_code,
            "detail_en": self.detail_en,
            "detail_bn": self.detail_bn,
            "instance": instance or self.instance,
            "trace_id": trace_id,
        }
        if self.extra:
            fields.update(self.extra)
        return ProblemDetail(**fields)


class NotFound(AppError):
    status_code = 404
    type_slug = "not-found"
    title = "Not found"

    def __init__(self, detail_en: str | None = None, detail_bn: str | None = None, **kw: Any) -> None:
        super().__init__(
            detail_en or "The requested resource was not found.",
            detail_bn or "অনুরোধ করা তথ্যটি খুঁজে পাওয়া যায়নি।",
            **kw,
        )


class Forbidden(AppError):
    status_code = 403
    type_slug = "forbidden"
    title = "Forbidden"

    def __init__(self, detail_en: str | None = None, detail_bn: str | None = None, **kw: Any) -> None:
        super().__init__(
            detail_en or "You do not have permission to do that.",
            detail_bn or "এই কাজটি করার অনুমতি আপনার নেই।",
            **kw,
        )


class Unauthorized(AppError):
    status_code = 401
    type_slug = "unauthorized"
    title = "Unauthorized"

    def __init__(self, detail_en: str | None = None, detail_bn: str | None = None, **kw: Any) -> None:
        super().__init__(
            detail_en or "Please sign in to continue.",
            detail_bn or "চালিয়ে যেতে সাইন ইন করুন।",
            **kw,
        )


class Conflict(AppError):
    status_code = 409
    type_slug = "conflict"
    title = "Conflict"

    def __init__(self, detail_en: str | None = None, detail_bn: str | None = None, **kw: Any) -> None:
        super().__init__(
            detail_en or "This already exists.",
            detail_bn or "এটি ইতিমধ্যে বিদ্যমান।",
            **kw,
        )


class RateLimited(AppError):
    status_code = 429
    type_slug = "rate-limited"
    title = "Too many requests"

    def __init__(
        self,
        detail_en: str | None = None,
        detail_bn: str | None = None,
        *,
        retry_after: int | None = None,
        **kw: Any,
    ) -> None:
        headers = kw.pop("headers", None) or {}
        if retry_after is not None:
            headers["Retry-After"] = str(retry_after)
        super().__init__(
            detail_en
            or "You are sending requests too quickly. The model is shared across "
            "every student, so please wait a moment and try again.",
            detail_bn
            or "আপনি অনেক দ্রুত অনুরোধ পাঠাচ্ছেন। মডেলটি সব শিক্ষার্থীর মধ্যে ভাগ করা, "
            "তাই একটু অপেক্ষা করে আবার চেষ্টা করুন।",
            headers=headers,
            **kw,
        )


class ValidationProblem(AppError):
    status_code = 422
    type_slug = "validation-failed"
    title = "Validation failed"

    def __init__(self, detail_en: str | None = None, detail_bn: str | None = None, **kw: Any) -> None:
        super().__init__(
            detail_en or "Some of the information you provided isn't valid.",
            detail_bn or "আপনার দেওয়া তথ্যের কিছু অংশ সঠিক নয়।",
            **kw,
        )


class PayloadTooLarge(AppError):
    status_code = 413
    type_slug = "payload-too-large"
    title = "Payload too large"

    def __init__(self, detail_en: str | None = None, detail_bn: str | None = None, **kw: Any) -> None:
        super().__init__(
            detail_en or "That file is larger than the allowed limit.",
            detail_bn or "ফাইলটি অনুমোদিত সীমার চেয়ে বড়।",
            **kw,
        )


class AccountBanned(AppError):
    """423, per docs/api_contract.md section 3: returned for both a ban and a
    suspension, carrying the moderator's own bilingual reason when there is
    one (users.status_reason_en/_bn)."""

    status_code = 423
    type_slug = "account-restricted"
    title = "Account restricted"

    def __init__(self, detail_en: str | None = None, detail_bn: str | None = None, **kw: Any) -> None:
        super().__init__(
            detail_en or "This account cannot sign in right now.",
            detail_bn or "এই মুহূর্তে এই অ্যাকাউন্ট দিয়ে সাইন ইন করা যাচ্ছে না।",
            **kw,
        )


class ModelUnavailable(AppError):
    status_code = 503
    type_slug = "model-unavailable"
    title = "Model unavailable"

    def __init__(self, detail_en: str | None = None, detail_bn: str | None = None, **kw: Any) -> None:
        super().__init__(
            detail_en or "The answering model is temporarily unavailable. Please try again shortly.",
            detail_bn or "উত্তর দেওয়ার মডেলটি সাময়িকভাবে অনুপলব্ধ। কিছুক্ষণ পর আবার চেষ্টা করুন।",
            **kw,
        )


def _trace_id(request: Request) -> str | None:
    return getattr(request.state, "trace_id", None)


def install_exception_handlers(app: FastAPI) -> None:
    """Register handlers so every error this API returns, deliberate or not,
    is rendered as application/problem+json."""

    @app.exception_handler(AppError)
    async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        problem = exc.to_problem(instance=str(request.url.path), trace_id=_trace_id(request))
        return JSONResponse(
            status_code=exc.status_code,
            content=problem.model_dump(exclude_none=True),
            media_type=PROBLEM_MEDIA_TYPE,
            headers=exc.headers or None,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        problem = ProblemDetail(
            type=f"{PROBLEM_BASE}/validation-failed",
            title="Validation failed",
            status=422,
            detail_en="Some of the information you provided isn't valid.",
            detail_bn="আপনার দেওয়া তথ্যের কিছু অংশ সঠিক নয়।",
            instance=str(request.url.path),
            trace_id=_trace_id(request),
            errors=exc.errors(),
        )
        return JSONResponse(
            status_code=422,
            content=problem.model_dump(exclude_none=True),
            media_type=PROBLEM_MEDIA_TYPE,
        )

    @app.exception_handler(Exception)
    async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        trace_id = _trace_id(request)
        log.exception("unhandled error trace_id=%s path=%s", trace_id, request.url.path)
        problem = ProblemDetail(
            type=f"{PROBLEM_BASE}/internal-error",
            title="Internal error",
            status=500,
            detail_en="Something went wrong on our side. Please try again.",
            detail_bn="আমাদের দিক থেকে একটি সমস্যা হয়েছে। আবার চেষ্টা করুন।",
            instance=str(request.url.path),
            trace_id=trace_id,
        )
        return JSONResponse(
            status_code=500,
            content=problem.model_dump(exclude_none=True),
            media_type=PROBLEM_MEDIA_TYPE,
        )

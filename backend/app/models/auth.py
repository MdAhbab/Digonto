"""Request and response bodies for `app.routers.auth`.

Section 3 of the API contract is explicit: plain email and password, no email
sending, no one-time codes, no magic links, because a judge must be inside the
product in under fifteen seconds. That rules out an OTP-issuance flow for
login, and it is also why `DeleteAccountRequest` below asks for the current
password rather than a mailed code: section 13 says deletion "requires a
fresh OTP confirmation", but nothing in this system can mail a code, so the
current password is the fresh confirmation that actually exists. See the
final report for this deliberate deviation.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.models.user import User


class SignupRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    email: str
    password: str = Field(min_length=8)
    display_name: str


class LoginRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    email: str
    password: str


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    current_password: str
    new_password: str = Field(min_length=8)


class ConsentsUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    improve_model: bool
    usage_analytics: bool


class DeleteAccountRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    current_password: str


class AuthResponse(BaseModel):
    """`201`/`200` body for signup and login. The refresh token itself never
    appears here; it is set as an HttpOnly cookie by the router.
    """

    model_config = ConfigDict(populate_by_name=True)

    access_token: str
    expires_in: int
    user: User


class ExportReceipt(BaseModel):
    """`GET /me/export` response.

    The contract describes email delivery of a signed archive link, but
    section 3 rules out any email-sending infrastructure existing in this
    system. The honest behaviour is to queue the export (emitting an event a
    future mailer worker can consume) and hand back a receipt rather than a
    fabricated download URL.
    """

    model_config = ConfigDict(populate_by_name=True)

    status: str
    requested_at: str


class DeleteReceipt(BaseModel):
    """What `DELETE /me` and `POST /me/deletion/cancel` tell the student.

    `scheduled_for` is the date the data is erased, and it is returned rather than
    left for the student to calculate. A promise to delete "within 30 days" that
    does not say which day is not something anyone can hold the service to.

    `status` is one of `scheduled`, `already_scheduled` (asking twice does not move
    the date), `cancelled`, or `not_scheduled`.
    """

    model_config = ConfigDict(populate_by_name=True)

    status: str
    requested_at: str | None = None
    scheduled_for: str | None = None
    cancelled_at: str | None = None
    window_days: int | None = None


class WithdrawReceipt(BaseModel):
    """What POST /me/consents/withdraw tells the student it actually did.

    The counts are returned rather than a bare acknowledgement so the
    student can see the scale of what was removed. `adapters_flagged` is the
    number of trained adapters that had already consumed at least one of the
    deleted samples and now await a reviewer decision.
    """

    model_config = ConfigDict(populate_by_name=True)

    status: str
    withdrawn_at: str
    samples_deleted: int
    adapters_flagged: int
    adapter_tags: list[str] = []

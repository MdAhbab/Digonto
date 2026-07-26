"""Authentication: signup, login, refresh, logout, session, password change.

docs/api_contract.md section 3. Wires straight to `AuthService`; the only
logic that lives here rather than in the service is the HTTP-specific part
the service cannot own: reading and setting the refresh cookie.

Deviation from the letter of section 3: there is no `/auth/request-code` or
`/auth/verify-code` pair. Section 3's own prose is explicit that this system
sends no email and has no OTP flow ("no email sending, no one-time codes, no
magic links"), and `AuthService` (authoritative, not modified here) exposes
no method for either endpoint. Implementing them would mean inventing a
service method, which the router brief for this build says not to do.
Section 14's rate-limit table and section 15's frontend-mapping table still
name `/auth/request-code`/`/auth/verify-code`; that is a leftover
inconsistency in the contract itself, flagged in the final report rather
than resolved by fabricating an OTP subsystem.
"""

from __future__ import annotations

from typing import Mapping

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict

from app.config import get_settings
from app.db.connection import Databases
from app.deps import RateLimit, get_bus, get_current_user, get_dbs
from app.errors import Unauthorized
from app.events.bus import EventBus
from app.models.auth import AuthResponse, ChangePasswordRequest, LoginRequest, SignupRequest
from app.models.user import User
from app.repositories.user_repo import UserRepo
from app.services.auth_service import AuthService

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
    dependencies=[Depends(RateLimit("auth_default", limit=120, window_s=60))],
)

_REFRESH_COOKIE = "digonto_refresh"


class RefreshResponse(BaseModel):
    """`POST /auth/refresh` has no dedicated model in app/models/auth.py;
    the contract only names the two fields it returns beyond the cookie."""

    model_config = ConfigDict(populate_by_name=True)

    access_token: str
    expires_in: int


def get_auth_service(dbs: Databases = Depends(get_dbs), bus: EventBus = Depends(get_bus)) -> AuthService:
    return AuthService(UserRepo(dbs.app), bus, get_settings())


def _cookie_path() -> str:
    return f"{get_settings().api_base_path}/auth"


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    settings = get_settings()
    # HttpOnly, Secure, SameSite=Strict per docs/api_contract.md section 3.
    # Secure=True means this cookie is only ever sent over TLS; a plain-http
    # local run needs a reverse proxy terminating TLS in front of it, which
    # is the deployment topology the contract assumes.
    response.set_cookie(
        key=_REFRESH_COOKIE,
        value=refresh_token,
        max_age=settings.jwt_refresh_ttl_days * 24 * 3600,
        path=_cookie_path(),
        httponly=True,
        secure=True,
        samesite="strict",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(key=_REFRESH_COOKIE, path=_cookie_path())


def _client_ip_hash(request: Request) -> str | None:
    # Stored alongside a refresh token purely as an audit signal (which
    # device/IP rotated this token last); never used for access control.
    import hashlib

    host = request.client.host if request.client else None
    return hashlib.sha256(host.encode("utf-8")).hexdigest() if host else None


@router.post("/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def signup(
    body: SignupRequest,
    request: Request,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthResponse:
    user, access_token, refresh_token, expires_in = await auth_service.signup(
        email=body.email,
        password=body.password,
        display_name=body.display_name,
        user_agent=request.headers.get("user-agent"),
        ip_hash=_client_ip_hash(request),
    )
    _set_refresh_cookie(response, refresh_token)
    return AuthResponse(access_token=access_token, expires_in=expires_in, user=User(**user))


@router.post("/login", response_model=AuthResponse)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthResponse:
    user, access_token, refresh_token, expires_in = await auth_service.login(
        email=body.email,
        password=body.password,
        user_agent=request.headers.get("user-agent"),
        ip_hash=_client_ip_hash(request),
    )
    _set_refresh_cookie(response, refresh_token)
    return AuthResponse(access_token=access_token, expires_in=expires_in, user=User(**user))


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(
    request: Request,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
) -> RefreshResponse:
    refresh_token = request.cookies.get(_REFRESH_COOKIE)
    if not refresh_token:
        raise Unauthorized(
            detail_en="No refresh session found. Please log in again.",
            detail_bn="কোনো রিফ্রেশ সেশন পাওয়া যায়নি। আবার লগইন করুন।",
        )
    access_token, new_refresh_token, expires_in = await auth_service.refresh(
        refresh_plain=refresh_token,
        user_agent=request.headers.get("user-agent"),
        ip_hash=_client_ip_hash(request),
    )
    _set_refresh_cookie(response, new_refresh_token)
    return RefreshResponse(access_token=access_token, expires_in=expires_in)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def logout(
    request: Request,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
) -> None:
    refresh_token = request.cookies.get(_REFRESH_COOKIE)
    if refresh_token:
        await auth_service.logout(refresh_token)
    _clear_refresh_cookie(response)


@router.get("/session", response_model=User)
async def get_session(
    user: Mapping = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
) -> User:
    session_user = await auth_service.get_session_user(user["id"])
    return User(**session_user)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def change_password(
    body: ChangePasswordRequest,
    user: Mapping = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
) -> None:
    await auth_service.change_password(user["id"], body.current_password, body.new_password)


# `PUT /me/consents`, `GET /me/export`, and `DELETE /me` are also served by
# `AuthService` (signup/login live here; those three live in me.py, next to
# the rest of the `/me/*` surface, importing `get_auth_service` from this
# module so the construction logic is not duplicated).

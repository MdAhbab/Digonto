"""The `User` shape shared by every auth and session endpoint.

Matches the frontend `User` interface in `docs/api_contract.md` section 3
field for field. Entirely snake_case: this is not one of the camelCase
surfaces.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

Role = Literal["student", "moderator", "admin"]
UserStatus = Literal["active", "suspended", "banned"]
LangPref = Literal["bn", "en"]
ThemePref = Literal["light", "dark", "system"]


class Consents(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    improve_model: bool
    usage_analytics: bool


class User(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    email: str
    display_name: str
    role: Role
    status: UserStatus
    lang_pref: LangPref
    theme_pref: ThemePref
    created_at: str
    profile_complete: bool
    consents: Consents

    # Set only while a deletion request is inside its 30-day window
    # (019_account_deletion_window.sql). Carried on every authenticated response so
    # the interface can show what is about to happen and offer to cancel it, rather
    # than the student having to remember they asked. Null is the ordinary case.
    deletion_scheduled_for: str | None = None

from datetime import datetime
from enum import StrEnum
from typing import Optional
from pydantic import BaseModel, Field


class UserRole(StrEnum):
    viewer = "viewer"
    researcher = "researcher"
    expert_contributor = "expert_contributor"
    curator = "curator"
    admin = "admin"
    company_owner = "company_owner"
    expedition_operator = "expedition_operator"


class UserProfile(BaseModel):
    user_id: str
    email: str
    display_name: Optional[str] = None
    role: UserRole = UserRole.researcher
    google_sub: Optional[str] = None
    invite_key_redeemed: Optional[str] = None  # hashed key ref
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_login: Optional[datetime] = None

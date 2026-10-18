"""Who may read an upload (and anything keyed by it, e.g. its environmental context)."""
from typing import Optional

from ..models.user import UserProfile, UserRole


def can_view_upload(upload_user_id: Optional[str], user: UserProfile) -> bool:
    """The owner, or an admin / company_owner."""
    return upload_user_id == user.user_id or user.role in (UserRole.admin, UserRole.company_owner)

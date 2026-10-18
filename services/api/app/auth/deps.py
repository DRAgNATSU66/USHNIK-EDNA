from typing import Annotated
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt as pyjwt
from ..models.user import UserProfile, UserRole
from .jwt import decode_access_token

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> UserProfile:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = decode_access_token(credentials.credentials)
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except pyjwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    # Offline Abyss credentials are signed with the same secret but are not API
    # access tokens: an offline license (type=offline_license, up to 90 days)
    # or an expedition session (mode=abyss_offline, 45 days) cannot be revoked,
    # so neither may authenticate API calls.
    if payload.get("type") == "offline_license" or payload.get("mode") == "abyss_offline":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Offline expedition credentials cannot be used as an API access token",
        )

    return UserProfile(
        user_id=payload["sub"],
        email=payload.get("email", ""),
        display_name=payload.get("name"),
        role=UserRole(payload.get("role", UserRole.researcher)),
    )


def require_role(*roles: UserRole):
    async def _check(user: Annotated[UserProfile, Depends(get_current_user)]) -> UserProfile:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return user
    return _check

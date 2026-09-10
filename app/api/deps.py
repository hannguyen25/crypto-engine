from typing import Dict, Any, Optional
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from app.core.rate_limiter import TokenBucketRateLimiter
from app.core.security import decode_access_token

# Tắt auto_error để chủ động bắt lỗi thiếu Authorization header và trả về 401
security = HTTPBearer(auto_error=False)
rate_limiter = TokenBucketRateLimiter(capacity=100, refill_rate=10.0)


async def get_current_user_id(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> str:
    # Nếu không có header Authorization hoặc format không phải Bearer
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    try:
        payload: Dict[str, Any] = decode_access_token(token)
        user_id: str | None = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing subject",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return str(user_id)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def check_rate_limit(
    request: Request,
    user_id: str = Depends(get_current_user_id),
) -> bool:
    await rate_limiter.check_rate_limit(user_id=user_id, request=request)
    return True


get_current_user = get_current_user_id
"""Single shared API key. Enough for a one-team console; swap for real auth later."""

from fastapi import Header, HTTPException, status

from corp.config import settings


async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """No-op when API_KEY is unset (local dev); otherwise the header must match."""
    if not settings.api_key:
        return
    if x_api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid X-Api-Key",
            headers={"WWW-Authenticate": "ApiKey"},
        )

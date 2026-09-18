"""No-DB tests for the shared API-key dependency."""

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from corp.api import auth


async def test_no_key_configured_is_noop():
    with patch.object(auth.settings, "api_key", ""):
        # Any header (or none) is accepted in local dev.
        assert await auth.require_api_key(None) is None
        assert await auth.require_api_key("whatever") is None


async def test_matching_key_passes():
    with patch.object(auth.settings, "api_key", "s3cret"):
        assert await auth.require_api_key("s3cret") is None


async def test_wrong_key_rejected():
    with patch.object(auth.settings, "api_key", "s3cret"):
        with pytest.raises(HTTPException) as exc:
            await auth.require_api_key("nope")
        assert exc.value.status_code == 401


async def test_missing_key_rejected():
    with patch.object(auth.settings, "api_key", "s3cret"):
        with pytest.raises(HTTPException) as exc:
            await auth.require_api_key(None)
        assert exc.value.status_code == 401


async def test_non_ascii_key_does_not_raise_type_error():
    """Starlette decodes headers as latin-1; non-ASCII chars must not cause
    a TypeError in hmac.compare_digest (which rejects mixed str with non-ASCII).
    The fix encodes both sides to bytes before comparing."""
    non_ascii_key = "clé-secrète"
    with patch.object(auth.settings, "api_key", non_ascii_key):
        # Matching non-ASCII key should pass.
        assert await auth.require_api_key(non_ascii_key) is None

        # Wrong non-ASCII key should be rejected, not blow up.
        with pytest.raises(HTTPException) as exc:
            await auth.require_api_key("wröng")
        assert exc.value.status_code == 401

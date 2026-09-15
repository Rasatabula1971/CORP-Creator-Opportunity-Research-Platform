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

"""No-DB tests for the FastAPI application factory's docs/schema exposure."""

from unittest.mock import patch

from fastapi.testclient import TestClient

from corp.api import app as app_module


def test_docs_open_when_no_api_key():
    with patch.object(app_module.settings, "api_key", ""):
        client = TestClient(app_module.create_app())
        assert client.get("/docs").status_code == 200
        assert client.get("/openapi.json").status_code == 200


def test_docs_disabled_when_api_key_configured():
    with patch.object(app_module.settings, "api_key", "s3cret"):
        client = TestClient(app_module.create_app())
        assert client.get("/docs").status_code == 404
        assert client.get("/redoc").status_code == 404
        assert client.get("/openapi.json").status_code == 404

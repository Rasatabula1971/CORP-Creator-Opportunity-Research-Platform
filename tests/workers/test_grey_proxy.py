"""Grey-source egress routing (ADR-0067)."""

import pytest

from corp.config import Settings
from corp.workers.adapters.registry import (
    AdapterConfigError,
    build_adapter,
    redact_proxy,
)

PROXY = "http://user:secret@proxy.example.net:8080"
GREY = ("amazon_reviews", "marketplace", "crowdfunding")


@pytest.mark.parametrize("platform", GREY)
def test_grey_adapter_gets_proxy(platform):
    adapter = build_adapter(platform, Settings(grey_proxy_url=PROXY))
    assert adapter._proxy == PROXY


@pytest.mark.parametrize("platform", GREY)
def test_grey_adapter_direct_without_proxy_by_default(platform):
    adapter = build_adapter(platform, Settings(grey_proxy_url=""))
    assert adapter._proxy is None


@pytest.mark.parametrize("platform", GREY)
def test_required_without_proxy_refuses(platform):
    cfg = Settings(grey_proxy_url="", grey_proxy_required=True)
    with pytest.raises(AdapterConfigError, match="GREY_PROXY_URL"):
        build_adapter(platform, cfg)


def test_required_does_not_block_official_sources():
    cfg = Settings(grey_proxy_url="", grey_proxy_required=True)
    build_adapter("reddit", cfg)
    build_adapter("hackernews", cfg)


def test_platform_not_listed_goes_direct():
    cfg = Settings(grey_proxy_url=PROXY, grey_proxy_platforms="marketplace")
    assert build_adapter("amazon_reviews", cfg)._proxy is None
    assert build_adapter("marketplace", cfg)._proxy == PROXY


def test_proxy_reaches_httpx_client():
    adapter = build_adapter("amazon_reviews", Settings(grey_proxy_url=PROXY))
    client = adapter._get_client()
    transport = client._transport_for_url(client._merge_url("https://www.amazon.com/"))
    assert transport is not client._transport  # a proxy mount was selected


def test_redact_proxy_strips_credentials():
    assert redact_proxy(PROXY) == "http://proxy.example.net:8080"
    assert "secret" not in redact_proxy(PROXY)

from datetime import UTC, datetime

from corp.core.models.evidence import AccessMethod, ComplianceStatus
from corp.workers.adapters.base import NormalizedContent


def test_normalized_content_creation():
    content = NormalizedContent(
        source_platform="youtube",
        content_type="comment",
        external_id="abc123",
        text="This is a comment",
        author="user1",
        timestamp=datetime.now(UTC),
        access_method=AccessMethod.OFFICIAL,
        compliance_status=ComplianceStatus.COMPLIANT,
    )
    assert content.source_platform == "youtube"
    assert content.access_method == AccessMethod.OFFICIAL


def test_normalized_content_minimal():
    content = NormalizedContent(
        source_platform="youtube",
        content_type="comment",
        external_id="abc123",
        text="Comment text",
        access_method=AccessMethod.OFFICIAL,
        compliance_status=ComplianceStatus.COMPLIANT,
    )
    assert content.author is None
    assert content.parent_id is None
    assert content.metadata == {}


def test_normalized_content_vendor_scrape():
    content = NormalizedContent(
        source_platform="tiktok",
        content_type="comment",
        external_id="tt_123",
        text="TikTok comment",
        access_method=AccessMethod.VENDOR_SCRAPE,
        compliance_status=ComplianceStatus.TOS_RISK,
    )
    assert content.access_method == AccessMethod.VENDOR_SCRAPE
    assert content.compliance_status == ComplianceStatus.TOS_RISK

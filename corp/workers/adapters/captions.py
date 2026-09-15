"""YouTube transcript fetch shared by the official-API and yt-dlp adapters."""

import logging

from corp.core.models.evidence import AccessMethod, ComplianceStatus
from corp.workers.adapters.base import NormalizedContent

logger = logging.getLogger(__name__)


def fetch_youtube_caption(
    video_id: str,
    access_method: AccessMethod,
    compliance_status: ComplianceStatus,
) -> NormalizedContent | None:
    """Return the transcript as a ``caption`` item, or None when unavailable.

    Blocking; call via ``asyncio.to_thread``. No API quota is used.
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        transcript = YouTubeTranscriptApi().fetch(video_id)
        text = " ".join(snippet.text for snippet in transcript)
    except Exception:
        logger.debug("No captions for video %s", video_id)
        return None

    return NormalizedContent(
        source_platform="youtube",
        content_type="caption",
        external_id=f"caption_{video_id}",
        text=text,
        parent_id=video_id,
        access_method=access_method,
        compliance_status=compliance_status,
    )

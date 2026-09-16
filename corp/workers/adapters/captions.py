"""YouTube transcript fetch shared by the official-API and yt-dlp adapters.

Fetches the transcript via ``youtube-transcript-api``, segments it into
paragraph-sized chunks by pause gaps, and returns both the flat text (for
evidence storage) and structured segments (for timestamp-aware extraction).
"""

import logging
from dataclasses import dataclass

from corp.core.models.evidence import AccessMethod, ComplianceStatus
from corp.workers.adapters.base import NormalizedContent

logger = logging.getLogger(__name__)

PAUSE_GAP_SECONDS = 2.0
MIN_SEGMENT_CHARS = 80
MAX_SEGMENT_CHARS = 1500
DEFAULT_LANGUAGES = ("en",)


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    text: str
    start: float
    end: float


def _segment_snippets(
    snippets: list[dict],
    pause_gap: float = PAUSE_GAP_SECONDS,
) -> list[TranscriptSegment]:
    """Group raw snippets into segments split at natural pauses.

    A new segment starts when the gap between the end of the previous snippet
    and the start of the current one exceeds ``pause_gap`` seconds.
    """
    if not snippets:
        return []

    segments: list[TranscriptSegment] = []
    buf_texts: list[str] = []
    buf_start = snippets[0]["start"]
    buf_end = buf_start

    for snip in snippets:
        snip_start = snip["start"]
        snip_end = snip_start + snip.get("duration", 0.0)
        gap = snip_start - buf_end

        if buf_texts and (
            gap > pause_gap
            or sum(len(t) for t in buf_texts) >= MAX_SEGMENT_CHARS
        ):
            text = " ".join(buf_texts).strip()
            if text:
                segments.append(TranscriptSegment(text=text, start=buf_start, end=buf_end))
            buf_texts = []
            buf_start = snip_start

        buf_texts.append(snip["text"])
        buf_end = max(buf_end, snip_end)

    if buf_texts:
        text = " ".join(buf_texts).strip()
        if text:
            segments.append(TranscriptSegment(text=text, start=buf_start, end=buf_end))

    if len(segments) > 1:
        merged: list[TranscriptSegment] = [segments[0]]
        for seg in segments[1:]:
            prev = merged[-1]
            if len(prev.text) < MIN_SEGMENT_CHARS:
                merged[-1] = TranscriptSegment(
                    text=f"{prev.text} {seg.text}",
                    start=prev.start,
                    end=seg.end,
                )
            else:
                merged.append(seg)
        segments = merged

    return segments


def fetch_youtube_caption(
    video_id: str,
    access_method: AccessMethod,
    compliance_status: ComplianceStatus,
    languages: tuple[str, ...] = DEFAULT_LANGUAGES,
) -> NormalizedContent | None:
    """Return the transcript as a ``caption`` item, or None when unavailable.

    Blocking; call via ``asyncio.to_thread``. No API quota is used.

    The returned ``NormalizedContent`` has:
    - ``text``: the full transcript as a flat joined string (backward-compatible).
    - ``metadata.segments``: list of ``{text, start, end}`` dicts for
      timestamp-aware extraction.
    - ``metadata.language``: the language code of the fetched transcript.
    - ``metadata.is_generated``: whether YouTube auto-generated the captions.
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        transcript = YouTubeTranscriptApi().fetch(video_id, languages=languages)
    except Exception:
        logger.debug("No captions for video %s", video_id)
        return None

    raw_data = transcript.to_raw_data()
    segments = _segment_snippets(raw_data)
    flat_text = " ".join(seg.text for seg in segments)
    if not flat_text.strip():
        return None

    return NormalizedContent(
        source_platform="youtube",
        content_type="caption",
        external_id=f"caption_{video_id}",
        text=flat_text,
        parent_id=video_id,
        access_method=access_method,
        compliance_status=compliance_status,
        metadata={
            "language": transcript.language_code,
            "is_generated": transcript.is_generated,
            "segment_count": len(segments),
            "duration": round(segments[-1].end, 1) if segments else 0.0,
            "segments": [
                {"text": s.text, "start": round(s.start, 1), "end": round(s.end, 1)}
                for s in segments
            ],
        },
    )

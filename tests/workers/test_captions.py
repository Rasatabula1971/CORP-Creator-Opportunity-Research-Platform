"""Tests for YouTube transcript segmentation and fetch."""

from corp.core.models.evidence import AccessMethod, ComplianceStatus
from corp.workers.adapters.captions import (
    TranscriptSegment,
    _segment_snippets,
)


def _snip(text: str, start: float, duration: float = 2.0) -> dict:
    return {"text": text, "start": start, "duration": duration}


# ── _segment_snippets ───────────────────────────────────────────────


def test_empty_snippets():
    assert _segment_snippets([]) == []


def test_single_snippet():
    segs = _segment_snippets([_snip("Hello world", 0.0)])
    assert len(segs) == 1
    assert segs[0].text == "Hello world"
    assert segs[0].start == 0.0


def test_continuous_snippets_stay_together():
    snippets = [
        _snip("Hello", 0.0, 1.5),
        _snip("world", 1.5, 1.5),
        _snip("how are you", 3.0, 2.0),
    ]
    segs = _segment_snippets(snippets, pause_gap=2.0)
    assert len(segs) == 1
    assert "Hello" in segs[0].text
    assert "how are you" in segs[0].text


def test_pause_gap_splits_segments():
    first = "First part of the discussion about audience problems and their detailed analysis"
    second = "Second part covers the commercial signals and how creators monetize their audience"
    snippets = [
        _snip(first, 0.0, 4.0),
        _snip("and further elaboration on the first topic with more context", 4.0, 3.0),
        _snip(second, 15.0, 4.0),
        _snip("plus additional notes on monetization strategies for creators", 19.0, 3.0),
    ]
    segs = _segment_snippets(snippets, pause_gap=2.0)
    assert len(segs) == 2
    assert "First part" in segs[0].text
    assert "Second part" in segs[1].text


def test_short_segments_get_merged():
    snippets = [
        _snip("Hi", 0.0, 0.5),
        _snip("OK now the real content starts here and goes on for a while with detail", 10.0, 5.0),
        _snip("and more detail about the topic at hand which is very interesting", 15.0, 5.0),
    ]
    segs = _segment_snippets(snippets, pause_gap=2.0)
    assert segs[0].start == 0.0
    assert "Hi" in segs[0].text


def test_max_segment_chars_forces_split():
    long_text = "word " * 200  # ~1000 chars
    snippets = [
        _snip(long_text, 0.0, 2.0),
        _snip(long_text, 2.0, 2.0),
        _snip(long_text, 4.0, 2.0),
    ]
    segs = _segment_snippets(snippets, pause_gap=5.0)
    assert len(segs) >= 2


def test_segment_timestamps_round_trip():
    snippets = [
        _snip("Intro material with enough words to exceed the minimum segment character threshold easily", 0.0, 3.0),
        _snip("Gap content also long enough to stand alone as a separate meaningful segment in the output", 8.0, 4.0),
    ]
    segs = _segment_snippets(snippets, pause_gap=2.0)
    assert len(segs) == 2
    assert segs[0].end == 3.0
    assert segs[1].start == 8.0
    assert segs[1].end == 12.0


# ── fetch_youtube_caption (mocked) ──────────────────────────────────


def _mock_fetched_transcript(snippets, language_code="en", is_generated=True):
    """Create a mock FetchedTranscript-like object."""
    from dataclasses import dataclass, field
    from typing import Any

    @dataclass
    class MockSnippet:
        text: str
        start: float
        duration: float

    @dataclass
    class MockTranscript:
        snippets: list
        video_id: str = "test_vid"
        language: str = "English"
        language_code: str = language_code
        is_generated: bool = is_generated

        def __iter__(self):
            return iter(self.snippets)

        def to_raw_data(self):
            return [{"text": s.text, "start": s.start, "duration": s.duration} for s in self.snippets]

    mock_snippets = [MockSnippet(**s) for s in snippets]
    return MockTranscript(snippets=mock_snippets)


async def test_fetch_caption_returns_segments_in_metadata():
    from unittest.mock import MagicMock, patch

    from corp.workers.adapters.captions import fetch_youtube_caption

    transcript = _mock_fetched_transcript([
        {"text": "Hello everyone", "start": 0.0, "duration": 2.0},
        {"text": "welcome to my channel", "start": 2.0, "duration": 3.0},
        {"text": "today we discuss problems", "start": 10.0, "duration": 3.0},
    ])

    with patch("youtube_transcript_api.YouTubeTranscriptApi") as mock_cls:
        mock_cls.return_value.fetch.return_value = transcript
        result = fetch_youtube_caption(
            "test_vid", AccessMethod.OFFICIAL, ComplianceStatus.COMPLIANT
        )

    assert result is not None
    assert result.content_type == "caption"
    assert result.external_id == "caption_test_vid"
    assert result.parent_id == "test_vid"
    assert "Hello everyone" in result.text
    assert "today we discuss" in result.text
    assert result.metadata["language"] == "en"
    assert result.metadata["is_generated"] is True
    assert result.metadata["segment_count"] >= 1
    assert isinstance(result.metadata["segments"], list)
    for seg in result.metadata["segments"]:
        assert "text" in seg
        assert "start" in seg
        assert "end" in seg


async def test_fetch_caption_returns_none_on_failure():
    from unittest.mock import patch

    from corp.workers.adapters.captions import fetch_youtube_caption

    with patch("youtube_transcript_api.YouTubeTranscriptApi") as mock_cls:
        mock_cls.return_value.fetch.side_effect = Exception("No transcript")
        result = fetch_youtube_caption(
            "no_vid", AccessMethod.OFFICIAL, ComplianceStatus.COMPLIANT
        )

    assert result is None


async def test_fetch_caption_returns_none_on_empty_transcript():
    from unittest.mock import patch

    from corp.workers.adapters.captions import fetch_youtube_caption

    transcript = _mock_fetched_transcript([])

    with patch("youtube_transcript_api.YouTubeTranscriptApi") as mock_cls:
        mock_cls.return_value.fetch.return_value = transcript
        result = fetch_youtube_caption(
            "empty_vid", AccessMethod.OFFICIAL, ComplianceStatus.COMPLIANT
        )

    assert result is None


async def test_fetch_caption_passes_language_preference():
    from unittest.mock import patch

    from corp.workers.adapters.captions import fetch_youtube_caption

    transcript = _mock_fetched_transcript(
        [{"text": "Bonjour", "start": 0.0, "duration": 2.0}],
        language_code="fr",
    )

    with patch("youtube_transcript_api.YouTubeTranscriptApi") as mock_cls:
        mock_cls.return_value.fetch.return_value = transcript
        result = fetch_youtube_caption(
            "fr_vid", AccessMethod.OFFICIAL, ComplianceStatus.COMPLIANT,
            languages=("fr", "en"),
        )
        mock_cls.return_value.fetch.assert_called_once_with(
            "fr_vid", languages=("fr", "en")
        )

    assert result is not None
    assert result.metadata["language"] == "fr"

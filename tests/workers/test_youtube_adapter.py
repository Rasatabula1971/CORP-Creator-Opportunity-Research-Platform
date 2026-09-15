"""Unit tests for the YouTube adapter — all API calls mocked."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from googleapiclient.errors import HttpError

from corp.workers.adapters.youtube import QuotaExceededError, YouTubeAdapter


def _make_adapter(**kwargs) -> YouTubeAdapter:
    with patch("corp.workers.adapters.youtube.build") as mock_build:
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        adapter = YouTubeAdapter(api_key="fake-key", **kwargs)
    adapter._service = mock_service
    return adapter


# ---- resolve_channel ----


async def test_resolve_channel_by_handle():
    adapter = _make_adapter()
    mock_req = MagicMock()
    mock_req.execute.return_value = {"items": [{"id": "UC123"}]}
    adapter._service.channels().list.return_value = mock_req

    channel_id = await adapter.resolve_channel("@mkbhd")
    assert channel_id == "UC123"


async def test_resolve_channel_fallback_to_username():
    adapter = _make_adapter()

    call_count = 0

    def list_side_effect(**kwargs):
        nonlocal call_count
        call_count += 1
        mock_req = MagicMock()
        if call_count == 1:
            mock_req.execute.return_value = {"items": []}
        else:
            mock_req.execute.return_value = {"items": [{"id": "UC456"}]}
        return mock_req

    adapter._service.channels().list.side_effect = list_side_effect

    channel_id = await adapter.resolve_channel("mkbhd")
    assert channel_id == "UC456"
    assert call_count == 2


async def test_resolve_channel_not_found():
    adapter = _make_adapter()
    mock_req = MagicMock()
    mock_req.execute.return_value = {"items": []}
    adapter._service.channels().list.return_value = mock_req

    with pytest.raises(ValueError, match="Channel not found"):
        await adapter.resolve_channel("nonexistent")


# ---- list_videos ----


def _playlist_items_response(video_ids: list[str]) -> dict:
    return {
        "items": [
            {
                "snippet": {
                    "resourceId": {"videoId": vid},
                    "title": f"Video {vid}",
                    "channelTitle": "TestChannel",
                    "publishedAt": "2026-01-15T10:00:00Z",
                    "description": f"Desc {vid}",
                    "channelId": "UC123",
                }
            }
            for vid in video_ids
        ]
    }


def _video_stats_response(video_ids: list[str]) -> dict:
    return {
        "items": [
            {
                "id": vid,
                "statistics": {
                    "viewCount": "1000",
                    "likeCount": "50",
                    "commentCount": "10",
                },
            }
            for vid in video_ids
        ]
    }


async def test_list_videos():
    adapter = _make_adapter()

    channels_req = MagicMock()
    channels_req.execute.return_value = {
        "items": [
            {"contentDetails": {"relatedPlaylists": {"uploads": "UU123"}}}
        ]
    }

    playlist_req = MagicMock()
    playlist_req.execute.return_value = _playlist_items_response(["v1", "v2"])

    stats_req = MagicMock()
    stats_req.execute.return_value = _video_stats_response(["v1", "v2"])

    adapter._service.channels().list.return_value = channels_req
    adapter._service.playlistItems().list.return_value = playlist_req
    adapter._service.videos().list.return_value = stats_req

    videos = await adapter.list_videos("UC123", max_results=10)

    assert len(videos) == 2
    assert videos[0].content_type == "video"
    assert videos[0].external_id == "v1"
    assert videos[0].source_platform == "youtube"
    assert videos[0].metadata["view_count"] == 1000
    assert videos[0].metadata["like_count"] == 50
    assert "youtube.com/watch" in videos[0].url


async def test_list_videos_empty_channel():
    adapter = _make_adapter()
    mock_req = MagicMock()
    mock_req.execute.return_value = {"items": []}
    adapter._service.channels().list.return_value = mock_req

    videos = await adapter.list_videos("UC_empty")
    assert videos == []


async def test_list_videos_published_after_filter():
    adapter = _make_adapter()

    channels_req = MagicMock()
    channels_req.execute.return_value = {
        "items": [
            {"contentDetails": {"relatedPlaylists": {"uploads": "UU123"}}}
        ]
    }
    adapter._service.channels().list.return_value = channels_req

    playlist_req = MagicMock()
    playlist_req.execute.return_value = {
        "items": [
            {
                "snippet": {
                    "resourceId": {"videoId": "new_vid"},
                    "title": "New",
                    "channelTitle": "C",
                    "publishedAt": "2026-06-01T00:00:00Z",
                    "description": "",
                    "channelId": "UC123",
                }
            },
            {
                "snippet": {
                    "resourceId": {"videoId": "old_vid"},
                    "title": "Old",
                    "channelTitle": "C",
                    "publishedAt": "2025-01-01T00:00:00Z",
                    "description": "",
                    "channelId": "UC123",
                }
            },
        ]
    }
    adapter._service.playlistItems().list.return_value = playlist_req

    stats_req = MagicMock()
    stats_req.execute.return_value = _video_stats_response(["new_vid"])
    adapter._service.videos().list.return_value = stats_req

    cutoff = datetime(2026, 1, 1, tzinfo=timezone.utc)
    videos = await adapter.list_videos("UC123", published_after=cutoff)

    assert len(videos) == 1
    assert videos[0].external_id == "new_vid"


# ---- get_comment_threads ----


def _comment_threads_response() -> dict:
    return {
        "items": [
            {
                "snippet": {
                    "topLevelComment": {
                        "id": "cmt_1",
                        "snippet": {
                            "textDisplay": "Great video!",
                            "authorDisplayName": "viewer1",
                            "publishedAt": "2026-02-01T12:00:00Z",
                            "likeCount": 5,
                        },
                    }
                },
                "replies": {
                    "comments": [
                        {
                            "id": "reply_1",
                            "snippet": {
                                "textDisplay": "Thanks!",
                                "authorDisplayName": "creator",
                                "publishedAt": "2026-02-01T13:00:00Z",
                                "likeCount": 1,
                            },
                        }
                    ]
                },
            }
        ]
    }


async def test_get_comment_threads():
    adapter = _make_adapter()
    mock_req = MagicMock()
    mock_req.execute.return_value = _comment_threads_response()
    adapter._service.commentThreads().list.return_value = mock_req

    comments = await adapter.get_comment_threads("v1")

    assert len(comments) == 2
    assert comments[0].content_type == "comment"
    assert comments[0].external_id == "cmt_1"
    assert comments[0].text == "Great video!"
    assert comments[0].parent_id == "v1"
    assert comments[1].content_type == "reply"
    assert comments[1].external_id == "reply_1"
    assert comments[1].parent_id == "cmt_1"


async def test_get_comment_threads_disabled():
    adapter = _make_adapter()
    resp = MagicMock()
    resp.status = 403
    error = HttpError(resp, b"comments disabled")
    mock_req = MagicMock()
    mock_req.execute.side_effect = error
    adapter._service.commentThreads().list.return_value = mock_req

    comments = await adapter.get_comment_threads("v_no_comments")
    assert comments == []


# ---- get_captions ----


async def test_get_captions():
    adapter = _make_adapter()

    mock_transcript = MagicMock()
    mock_transcript.language_code = "en"
    mock_transcript.is_generated = True
    mock_transcript.to_raw_data.return_value = [
        {"text": "Hello", "start": 0.0, "duration": 1.5},
        {"text": "world", "start": 1.5, "duration": 1.5},
    ]

    with patch(
        "youtube_transcript_api.YouTubeTranscriptApi"
    ) as mock_api_cls:
        mock_instance = MagicMock()
        mock_instance.fetch.return_value = mock_transcript
        mock_api_cls.return_value = mock_instance

        caption = await adapter.get_captions("v1")

    assert caption is not None
    assert caption.content_type == "caption"
    assert "Hello" in caption.text
    assert "world" in caption.text
    assert caption.parent_id == "v1"
    assert caption.metadata["language"] == "en"


async def test_get_captions_unavailable():
    adapter = _make_adapter()

    with patch(
        "youtube_transcript_api.YouTubeTranscriptApi"
    ) as mock_api_cls:
        mock_instance = MagicMock()
        mock_instance.fetch.side_effect = Exception("No transcript")
        mock_api_cls.return_value = mock_instance

        caption = await adapter.get_captions("v_no_captions")

    assert caption is None


# ---- quota tracking ----


async def test_quota_tracking():
    adapter = _make_adapter(daily_quota=100)
    mock_req = MagicMock()
    mock_req.execute.return_value = {"items": [{"id": "UC1"}]}
    adapter._service.channels().list.return_value = mock_req

    assert adapter.quota_used == 0
    await adapter.resolve_channel("test")
    assert adapter.quota_used >= 1


async def test_quota_exceeded():
    adapter = _make_adapter(daily_quota=1)
    mock_req = MagicMock()
    mock_req.execute.return_value = {"items": [{"id": "UC1"}]}
    adapter._service.channels().list.return_value = mock_req

    await adapter.resolve_channel("test")

    with pytest.raises(QuotaExceededError):
        await adapter.resolve_channel("test2")


# ---- collect (end-to-end with mocks) ----


async def test_collect_full_flow():
    adapter = _make_adapter(max_videos=1, max_comments_per_video=5)

    # resolve_channel
    chan_req = MagicMock()
    chan_req.execute.return_value = {"items": [{"id": "UC_TEST"}]}

    # list_videos - channels().list for uploads playlist
    content_req = MagicMock()
    content_req.execute.return_value = {
        "items": [
            {"contentDetails": {"relatedPlaylists": {"uploads": "UU_TEST"}}}
        ]
    }

    call_count = {"channels": 0}

    def channels_list(**kwargs):
        call_count["channels"] += 1
        if "forHandle" in kwargs:
            return chan_req
        return content_req

    adapter._service.channels().list.side_effect = channels_list

    # playlistItems
    pl_req = MagicMock()
    pl_req.execute.return_value = _playlist_items_response(["vid_1"])
    adapter._service.playlistItems().list.return_value = pl_req

    # video stats
    stats_req = MagicMock()
    stats_req.execute.return_value = _video_stats_response(["vid_1"])
    adapter._service.videos().list.return_value = stats_req

    # comments
    cmt_req = MagicMock()
    cmt_req.execute.return_value = _comment_threads_response()
    adapter._service.commentThreads().list.return_value = cmt_req

    # captions - not available
    with patch(
        "youtube_transcript_api.YouTubeTranscriptApi"
    ) as mock_api_cls:
        mock_instance = MagicMock()
        mock_instance.fetch.side_effect = Exception("nope")
        mock_api_cls.return_value = mock_instance

        results = await adapter.collect("@testchannel")

    # 1 video + 1 comment + 1 reply = 3 items (no caption)
    assert len(results) == 3
    types = [r.content_type for r in results]
    assert "video" in types
    assert "comment" in types
    assert "reply" in types

"""Tests for the Stack Exchange adapter — all HTTP calls mocked."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from corp.workers.adapters.stackexchange import StackExchangeAdapter


def _question(qid: int, title: str = "How to X?", tags: list | None = None) -> dict:
    return {
        "question_id": qid,
        "title": title,
        "body": f"<p>I want to know about {title}</p>",
        "tags": tags or ["python"],
        "owner": {"display_name": f"user{qid}"},
        "creation_date": 1726000000 + qid,
        "link": f"https://stackoverflow.com/questions/{qid}",
        "view_count": 100 * qid,
        "score": 5 * qid,
        "answer_count": 2,
        "is_answered": True,
    }


def _answer(aid: int, qid: int, accepted: bool = False) -> dict:
    return {
        "answer_id": aid,
        "question_id": qid,
        "body": f"<p>The answer to question {qid}</p>",
        "owner": {"display_name": f"answerer{aid}"},
        "creation_date": 1726000000 + aid + 1000,
        "score": 10,
        "is_accepted": accepted,
    }


def _make_response(items: list, has_more: bool = False, quota: int = 299) -> dict:
    return {
        "items": items,
        "has_more": has_more,
        "quota_remaining": quota,
    }


@pytest.fixture
def mock_client():
    client = AsyncMock(spec=httpx.AsyncClient)
    client.is_closed = False
    return client


def _mock_resp(data: dict, status: int = 200) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.json.return_value = data
    resp.raise_for_status = MagicMock()
    return resp


# ── Adapter properties ──────────────────────────────────────────────


def test_adapter_properties():
    adapter = StackExchangeAdapter()
    assert adapter.platform == "stackexchange"
    assert adapter.family.value == "niche"
    assert adapter.access_method.value == "official"
    assert adapter.compliance_status.value == "compliant"


# ── collect by tag ──────────────────────────────────────────────────


async def test_collect_by_tag(mock_client):
    adapter = StackExchangeAdapter(
        max_questions=3,
        include_answers=False,
        client=mock_client,
    )
    questions_resp = _mock_resp(_make_response([
        _question(1, "How to parse JSON?", ["python", "json"]),
        _question(2, "Best sorting algorithm?", ["python", "algorithms"]),
    ]))
    mock_client.get = AsyncMock(return_value=questions_resp)

    results = await adapter.collect("tag:python")

    assert len(results) == 2
    assert results[0].content_type == "question"
    assert results[0].external_id == "1"
    assert results[0].source_platform == "stackexchange"
    assert "parse JSON" in results[0].text
    assert results[0].metadata["tags"] == ["python", "json"]
    assert results[0].metadata["site"] == "stackoverflow"


async def test_collect_by_tag_semicolon(mock_client):
    adapter = StackExchangeAdapter(
        max_questions=5,
        include_answers=False,
        client=mock_client,
    )
    mock_client.get = AsyncMock(
        return_value=_mock_resp(_make_response([_question(1)]))
    )

    await adapter.collect("tag:python;django")

    call_args = mock_client.get.call_args
    params = call_args.kwargs.get("params") or call_args[1].get("params") or call_args[0][1]
    assert params["tagged"] == "python;django"


# ── collect by search ───────────────────────────────────────────────


async def test_collect_by_search(mock_client):
    adapter = StackExchangeAdapter(
        max_questions=5,
        include_answers=False,
        client=mock_client,
    )
    mock_client.get = AsyncMock(
        return_value=_mock_resp(_make_response([_question(1, "How to deploy Flask?")]))
    )

    results = await adapter.collect("deploy Flask")

    assert len(results) == 1
    assert "deploy Flask" in results[0].text

    call_args = mock_client.get.call_args
    params = call_args.kwargs.get("params") or call_args[1].get("params") or call_args[0][1]
    assert params["q"] == "deploy Flask"
    assert params["sort"] == "relevance"
    assert "intitle" not in params
    # Free-text search is only valid on /search/advanced, not /questions.
    assert "/search/advanced" in str(call_args)


# ── answers ─────────────────────────────────────────────────────────


async def test_collect_with_answers(mock_client):
    adapter = StackExchangeAdapter(
        max_questions=5,
        include_answers=True,
        client=mock_client,
    )

    call_count = 0

    async def mock_get(path, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _mock_resp(_make_response([_question(1), _question(2)]))
        return _mock_resp(_make_response([
            _answer(101, 1, accepted=True),
            _answer(102, 2),
        ]))

    mock_client.get = mock_get

    results = await adapter.collect("tag:python")

    questions = [r for r in results if r.content_type == "question"]
    answers = [r for r in results if r.content_type == "reply"]

    assert len(questions) == 2
    assert len(answers) == 2
    assert answers[0].parent_id == "1"
    assert answers[0].metadata["is_accepted"] is True
    assert answers[1].parent_id == "2"


async def test_malformed_question_and_answer_are_skipped_not_fatal(mock_client):
    """A single record missing its id (e.g. deleted content omitted under
    filter=withbody) must be skipped, not abort the batch with a KeyError."""
    adapter = StackExchangeAdapter(
        max_questions=5,
        include_answers=True,
        client=mock_client,
    )

    good_question = _question(1)
    bad_question = _question(2)
    del bad_question["question_id"]

    good_answer = _answer(101, 1)
    bad_answer = _answer(102, 1)
    del bad_answer["answer_id"]

    call_count = 0

    async def mock_get(path, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _mock_resp(_make_response([good_question, bad_question]))
        return _mock_resp(_make_response([good_answer, bad_answer]))

    mock_client.get = mock_get

    results = await adapter.collect("tag:python")

    questions = [r for r in results if r.content_type == "question"]
    answers = [r for r in results if r.content_type == "reply"]
    assert [q.external_id for q in questions] == ["1"]
    assert [a.external_id for a in answers] == ["101"]


# ── pagination ──────────────────────────────────────────────────────


async def test_pagination(mock_client):
    adapter = StackExchangeAdapter(
        max_questions=3,
        include_answers=False,
        client=mock_client,
    )

    call_count = 0

    async def mock_get(path, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _mock_resp(_make_response(
                [_question(1), _question(2)],
                has_more=True,
            ))
        return _mock_resp(_make_response([_question(3)]))

    mock_client.get = mock_get

    results = await adapter.collect("tag:python")

    assert len(results) == 3
    assert call_count == 2


# ── empty results ───────────────────────────────────────────────────


async def test_empty_results(mock_client):
    adapter = StackExchangeAdapter(
        max_questions=5,
        include_answers=False,
        client=mock_client,
    )
    mock_client.get = AsyncMock(return_value=_mock_resp(_make_response([])))

    results = await adapter.collect("tag:obscure-tag-nobody-uses")
    assert results == []


# ── quota tracking ──────────────────────────────────────────────────


async def test_quota_tracking(mock_client):
    adapter = StackExchangeAdapter(
        include_answers=False,
        client=mock_client,
    )
    mock_client.get = AsyncMock(
        return_value=_mock_resp(_make_response([_question(1)], quota=250))
    )

    await adapter.collect("tag:python")

    assert adapter.quota_remaining == 250
    assert adapter.request_count == 1


# ── API key passthrough ─────────────────────────────────────────────


async def test_api_key_included(mock_client):
    adapter = StackExchangeAdapter(
        api_key="test-key-123",
        include_answers=False,
        client=mock_client,
    )
    mock_client.get = AsyncMock(
        return_value=_mock_resp(_make_response([_question(1)]))
    )

    await adapter.collect("tag:python")

    call_args = mock_client.get.call_args
    params = call_args.kwargs.get("params") or call_args[1].get("params") or call_args[0][1]
    assert params["key"] == "test-key-123"


# ── custom site ─────────────────────────────────────────────────────


async def test_custom_site(mock_client):
    adapter = StackExchangeAdapter(
        site="serverfault",
        include_answers=False,
        client=mock_client,
    )
    mock_client.get = AsyncMock(
        return_value=_mock_resp(_make_response([_question(1)]))
    )

    results = await adapter.collect("tag:nginx")

    call_args = mock_client.get.call_args
    params = call_args.kwargs.get("params") or call_args[1].get("params") or call_args[0][1]
    assert params["site"] == "serverfault"
    assert results[0].metadata["site"] == "serverfault"


# ── timestamp conversion ────────────────────────────────────────────


async def test_timestamps(mock_client):
    adapter = StackExchangeAdapter(
        include_answers=False,
        client=mock_client,
    )
    mock_client.get = AsyncMock(
        return_value=_mock_resp(_make_response([_question(1)]))
    )

    results = await adapter.collect("tag:python")

    ts = results[0].timestamp
    assert ts is not None
    assert ts.tzinfo is not None
    assert isinstance(ts, datetime)


async def test_implements_problem_provider(monkeypatch):
    """CORP1 Stage 4/5, T2: Stack Exchange is ProblemProvider, delegating to collect()."""
    from corp.workers.providers.capabilities import ProblemProvider

    adapter = StackExchangeAdapter()
    assert isinstance(adapter, ProblemProvider)

    sentinel: list[object] = []
    calls: list[str] = []

    async def fake_collect(identifier: str) -> list[object]:
        calls.append(identifier)
        return sentinel

    monkeypatch.setattr(adapter, "collect", fake_collect)

    assert await adapter.fetch_problems("tag:python") is sentinel
    assert calls == ["tag:python"]

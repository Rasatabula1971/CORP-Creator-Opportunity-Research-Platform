"""Unit tests for the competitive discovery pipeline — no database."""

import pytest

from corp.core.models.competitive import Competitor
from corp.core.models.evidence import Evidence, EvidenceOrigin, EvidenceType
from corp.core.models.intelligence import ProblemCluster
from corp.workers.intelligence import competitive_pipeline
from corp.workers.intelligence.competitive_pipeline import (
    CompetitivePipeline,
    _http_url_or_none,
)
from corp.workers.providers.registry import LLMProvider


class FakeProvider(LLMProvider):
    def __init__(self, response) -> None:
        self._response = response

    @property
    def model_name(self) -> str:
        return "fake"

    async def generate_json(self, prompt, system=None, *, schema=None):
        return self._response


class FakeSession:
    def __init__(self) -> None:
        self.added: list = []
        self.flushes = 0

    def add(self, obj) -> None:
        self.added.append(obj)
        if isinstance(obj, Evidence) and obj.id is None:
            obj.id = "ev-1"

    async def flush(self) -> None:
        self.flushes += 1


def _pipeline(response) -> CompetitivePipeline:
    pipe = CompetitivePipeline(FakeProvider(response), FakeSession())  # type: ignore[arg-type]

    async def _texts(cluster_id: str) -> list[str]:
        return ["I keep using a spreadsheet for this"]

    pipe._get_representative_texts = _texts  # type: ignore[method-assign]
    return pipe


def _cluster() -> ProblemCluster:
    return ProblemCluster(id="c-1", label="tracking expenses", frequency=3)


@pytest.mark.parametrize(
    "response", [["Notion", "Excel"], "Notion", 42, None, {"competitors": "Notion"}]
)
async def test_discover_ignores_non_object_or_non_list_replies(response):
    pipe = _pipeline(response)
    await pipe._discover_competitors(_cluster(), [], "run-1")
    assert pipe._session.added == []  # type: ignore[attr-defined]


async def test_discover_writes_competitors_for_well_formed_reply():
    pipe = _pipeline(
        {
            "competitors": [
                {"name": "Notion", "url": "https://notion.so", "strength": "strong"},
                {"name": "notion", "url": "https://dup.example"},
                {"name": "Excel", "url": "javascript:alert(1)"},
                "not a dict",
            ]
        }
    )
    await pipe._discover_competitors(_cluster(), ["desc"], "run-1")
    added = pipe._session.added  # type: ignore[attr-defined]
    competitors = [c for c in added if isinstance(c, Competitor)]
    assert [c.name for c in competitors] == ["Notion", "Excel"]
    assert competitors[0].url == "https://notion.so"
    assert competitors[1].url is None  # non-http scheme dropped at write time
    evidence = [e for e in added if isinstance(e, Evidence)]
    assert len(evidence) == 1
    assert evidence[0].origin is EvidenceOrigin.INFERENCE
    assert evidence[0].evidence_type is EvidenceType.SOLUTION


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://example.com/x", "https://example.com/x"),
        ("HTTP://example.com", "HTTP://example.com"),
        ("  https://padded.example  ", "https://padded.example"),
        ("javascript:alert(1)", None),
        ("data:text/html,hi", None),
        ("example.com", None),
        ("", None),
        (None, None),
        (123, None),
    ],
)
def test_http_url_or_none(value, expected):
    assert _http_url_or_none(value) == expected


def test_http_url_or_none_truncates_to_column_width():
    assert len(_http_url_or_none("https://" + "a" * 600) or "") == 500


async def test_load_clusters_uses_active_clusters_only(monkeypatch):
    calls: list[tuple] = []
    active = [_cluster()]

    async def fake_active(session, creator_id):
        calls.append((session, creator_id))
        return active

    monkeypatch.setattr(competitive_pipeline, "active_clusters_for_creator", fake_active)
    session = FakeSession()
    pipe = CompetitivePipeline(FakeProvider({}), session)  # type: ignore[arg-type]
    assert await pipe._load_clusters("creator-1") is active
    assert calls == [(session, "creator-1")]

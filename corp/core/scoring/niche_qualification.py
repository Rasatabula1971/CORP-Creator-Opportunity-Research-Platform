"""Deterministic niche qualification scoring (Slice 12).

Pure scoring functions — no database, no I/O. The pipeline in
``corp.workers.intelligence.niche_qualification`` loads data, calls these
functions, and persists the results.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True, slots=True)
class NicheInput:
    evidence_count: int
    author_count: int
    is_broad_domain: bool
    creator_count_observed: int
    target_band_creator_count: int


@dataclass(frozen=True, slots=True)
class QualificationResult:
    qualification_score: float
    confidence: float
    research_completeness: float
    components: dict[str, float]


def load_rules(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Niche qualification rules file not found: {p}")
    with open(p) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Niche qualification rules file must be a YAML mapping: {p}")
    return data


def _log_score(value: int, cap: int) -> float:
    if value <= 0:
        return 0.0
    return min(1.0, math.log1p(value) / math.log1p(cap))


def score_evidence_depth(evidence_count: int, cap: int = 50) -> float:
    return _log_score(evidence_count, cap)


def score_author_diversity(author_count: int, cap: int = 30) -> float:
    return _log_score(author_count, cap)


def score_ecosystem_size(creator_count: int, cap: int = 50) -> float:
    return _log_score(creator_count, cap)


def score_target_band_density(
    target_band: int, total_creators: int,
) -> float:
    if total_creators <= 0:
        return 0.0
    return min(1.0, target_band / total_creators)


def score_specificity(is_broad_domain: bool) -> float:
    return 0.0 if is_broad_domain else 1.0


def compute_components(
    inp: NicheInput, rules: dict[str, Any],
) -> dict[str, float]:
    norms = rules.get("normalizers", {})
    return {
        "evidence_depth": score_evidence_depth(
            inp.evidence_count, norms.get("evidence_depth_cap", 50),
        ),
        "author_diversity": score_author_diversity(
            inp.author_count, norms.get("author_diversity_cap", 30),
        ),
        "ecosystem_size": score_ecosystem_size(
            inp.creator_count_observed, norms.get("ecosystem_size_cap", 50),
        ),
        "target_band_density": score_target_band_density(
            inp.target_band_creator_count, inp.creator_count_observed,
        ),
        "specificity": score_specificity(inp.is_broad_domain),
    }


def compute_qualification_score(
    components: dict[str, float], weights: dict[str, float],
) -> float:
    total_weight = sum(weights.get(k, 0.0) for k in components)
    if total_weight == 0:
        return 0.0
    return sum(
        components[k] * weights.get(k, 0.0) for k in components
    ) / total_weight


def compute_confidence(
    inp: NicheInput, rules: dict[str, Any],
) -> float:
    conf = rules.get("confidence", {})
    high = conf.get("high", {})
    medium = conf.get("medium", {})

    has_ecosystem = inp.creator_count_observed > 0

    if (
        inp.evidence_count >= high.get("min_evidence", 15)
        and inp.author_count >= high.get("min_authors", 8)
        and (not high.get("requires_ecosystem", True) or has_ecosystem)
    ):
        return 1.0

    if (
        inp.evidence_count >= medium.get("min_evidence", 5)
        and inp.author_count >= medium.get("min_authors", 3)
    ):
        return 0.6 if has_ecosystem else 0.5

    return 0.3 if has_ecosystem else 0.2


def compute_research_completeness(
    inp: NicheInput, is_verified: bool, rules: dict[str, Any],
) -> float:
    flags = {
        "has_evidence": inp.evidence_count > 0,
        "is_verified": is_verified,
        "has_ecosystem_data": inp.creator_count_observed > 0,
        "has_target_band_data": inp.target_band_creator_count > 0,
    }
    stage_names = rules.get("completeness_stages") or list(flags)
    stages = [flags[name] for name in stage_names if name in flags]
    if not stages:
        return 0.0
    return sum(stages) / len(stages)


def qualify(
    inp: NicheInput, is_verified: bool, rules: dict[str, Any],
) -> QualificationResult:
    weights = rules.get("weights", {})
    components = compute_components(inp, rules)
    score = compute_qualification_score(components, weights)
    confidence = compute_confidence(inp, rules)
    completeness = compute_research_completeness(inp, is_verified, rules)
    return QualificationResult(
        qualification_score=round(score, 4),
        confidence=round(confidence, 4),
        research_completeness=round(completeness, 4),
        components={k: round(v, 4) for k, v in components.items()},
    )

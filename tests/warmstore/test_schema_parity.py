"""Warm-store schema must never drift behind the Postgres models it mirrors.

mirror_observations/mirror_interactions/mirror_content_items build their row
dicts from every column on the live ORM model (see
corp.warmstore.sync.model_to_dict) and hand them straight to
``insert(table).values(**row)``. A column added to the Postgres model but
not to the matching warm-store Table in schema.py makes every mirror of that
model raise ``sqlalchemy.exc.CompileError: Unconsumed column names`` — caught
and logged by sync.py's try/except, so it fails silently in production and
only shows up as "the warm store is missing data" much later.

This test makes that drift a loud, immediate test failure instead.
"""

import pytest

from corp.core.models.content import AudienceInteraction, ContentItem
from corp.core.models.evidence import Evidence
from corp.core.models.intelligence import ProblemObservation
from corp.core.models.metrics import MetricsSnapshot
from corp.core.models.scoring import CreatorScore, OpportunityScore
from corp.warmstore.schema import (
    audience_interactions,
    content_items,
    creator_scores,
    evidence,
    metrics_snapshots,
    opportunity_scores,
    problem_observations,
)

# Every (ORM model, warm-store Table) pair that corp.warmstore.sync mirrors.
_MIRRORED_PAIRS = [
    (Evidence, evidence),
    (ProblemObservation, problem_observations),
    (ContentItem, content_items),
    (AudienceInteraction, audience_interactions),
    (MetricsSnapshot, metrics_snapshots),
    (CreatorScore, creator_scores),
    (OpportunityScore, opportunity_scores),
]


@pytest.mark.parametrize(
    "model,warm_table", _MIRRORED_PAIRS, ids=[m.__name__ for m, _ in _MIRRORED_PAIRS]
)
def test_warm_table_has_every_model_column(model, warm_table):
    model_cols = {c.key for c in model.__table__.columns}
    warm_cols = {c.name for c in warm_table.columns}
    missing = model_cols - warm_cols
    assert not missing, (
        f"{model.__name__} has columns {sorted(missing)} that "
        f"corp/warmstore/schema.py's {warm_table.name!r} table doesn't — "
        "mirroring this model will raise CompileError (silently caught and "
        "logged by sync.py). Add the missing column(s) to schema.py."
    )

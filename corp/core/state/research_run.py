"""Validation for ResearchRun's run_type/reference invariants (§11).

Enforces the full doc-specified rule set: CREATOR_RESEARCH requires
creator_id, NICHE_VERIFICATION requires niche_id, NICHE_DISCOVERY requires
neither. New call sites (niche discovery/verification, built in later
slices) should call validate_run_type before creating a run.

Existing creator-pipeline call sites are NOT required to call this —
cross-creator clustering (ClusterPipeline.run(creator_id=None)) is existing,
designed behavior that predates this rule and must keep working unmodified.
Only the unambiguous half of this rule set (NICHE_VERIFICATION requires
niche_id) is enforced at the database level; see
docs/DECISIONS/0005-slice-5-generalize-researchrun.md.
"""

from corp.core.models.workflow import RunType


class InvalidResearchRunError(Exception):
    pass


def validate_run_type(
    run_type: RunType, *, creator_id: str | None, niche_id: str | None
) -> None:
    if run_type == RunType.CREATOR_RESEARCH and creator_id is None:
        raise InvalidResearchRunError("CREATOR_RESEARCH requires creator_id")
    if run_type == RunType.NICHE_VERIFICATION and niche_id is None:
        raise InvalidResearchRunError("NICHE_VERIFICATION requires niche_id")

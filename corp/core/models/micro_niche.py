"""Micro-niche suggestions — the approval queue between a creator's audience
and the niche drill engine.

A researched creator's audience problem clusters (ProblemCluster) are the
most specific niche evidence CORP collects: not "woodworking" but "finishing
outdoor oak", "fitting a shop in a one-car garage". Before this table they
fed scoring and dossiers only and never found their way back into niche
discovery. Each row here proposes one of them as a seed for the drill
engine, and waits for a human.

Why a table of its own rather than NicheCandidate: the campaign
``canonicalize`` stage consumes STAGED NicheCandidates automatically, so a
suggestion stored there would be drilled without the approval this queue
exists to enforce. Why a table at all rather than a live query: a rejected
suggestion must stay rejected, or the queue never shrinks.

One row per normalised label: a problem that shows up in several creators'
audiences is one suggestion with several sources, which is also the
strongest kind of evidence the queue can show.
"""

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from corp.core.models.base import Base, TimestampMixin, generate_uuid


class MicroNicheStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class MicroNicheSuggestion(TimestampMixin, Base):
    __tablename__ = "micro_niche_suggestions"
    __table_args__ = (
        Index("ix_micro_niche_suggestions_normalized_label", "normalized_label", unique=True),
        Index("ix_micro_niche_suggestions_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    # The cluster's own wording, shown for review.
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    # Lowercased, whitespace-collapsed label: the dedup key across creators
    # and across repeated suggestion runs.
    normalized_label: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[MicroNicheStatus] = mapped_column(
        Enum(MicroNicheStatus),
        default=MicroNicheStatus.PENDING,
        server_default=MicroNicheStatus.PENDING.name,
        nullable=False,
    )

    # The strongest supporting cluster, for a direct link from the queue to
    # the observations behind it. SET NULL: a cluster being superseded or
    # removed must not take the review history with it.
    problem_cluster_id: Mapped[str | None] = mapped_column(
        ForeignKey("problem_clusters.id", ondelete="SET NULL")
    )
    creator_id: Mapped[str | None] = mapped_column(
        ForeignKey("creators.id", ondelete="SET NULL")
    )
    # Context for the reviewer: the creator's own niche label and size.
    creator_niche: Mapped[str | None] = mapped_column(String(255))
    follower_count: Mapped[int | None] = mapped_column(Integer)

    # Evidence totals across every source, so the queue can be sorted by
    # how widely and how often the problem shows up.
    total_frequency: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    source_creator_count: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    # [{cluster_id, creator_id, label, frequency}] for every supporting cluster.
    sources: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default="[]", nullable=False
    )

    # The decision. approved_topic is what was actually drilled — the
    # reviewer may reword a problem-shaped label into a searchable niche.
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[str | None] = mapped_column(String(255))
    decision_note: Mapped[str | None] = mapped_column(Text)
    approved_topic: Mapped[str | None] = mapped_column(String(255))
    # The in-process discovery job started on approval (jobs are not
    # durable; the ResearchRun it creates is).
    discovery_job_id: Mapped[str | None] = mapped_column(String(64))

"""SQLite table definitions for the CORP warm store.

Mirrors the PostgreSQL models' columns using SQLite-compatible types:
JSONB → TEXT (JSON string), pgvector Vector(384) → BLOB, Enum → TEXT.
"""

from sqlalchemy import (
    Column,
    Float,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    Text,
)

metadata = MetaData()

evidence = Table(
    "evidence",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("source_type", String(50), nullable=False),
    Column("source_id", String(255), nullable=False),
    Column("source_platform", String(50), nullable=False),
    Column("raw_text", Text, nullable=False),
    Column("author_handle", String(255)),
    Column("source_url", String(500)),
    Column("access_method", String(50), nullable=False),
    Column("compliance_status", String(50), nullable=False),
    Column("collected_at", String(40), nullable=False),
    Column("research_run_id", String(36)),
    Column("evidence_type", String(50)),
)

problem_observations = Table(
    "problem_observations",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("evidence_id", String(36), nullable=False),
    Column("text", Text, nullable=False),
    Column("category", String(100)),
    Column("is_inferred", Integer, nullable=False, default=0),
    Column("extraction_prompt_version", String(50), nullable=False),
    Column("model_version", String(100), nullable=False),
    Column("confidence", Float),
    Column("source_side", String(20), nullable=False, default="audience"),
    Column("sentiment", String(20)),
    Column("urgency", String(20)),
    Column("embedding", LargeBinary),
    Column("created_at", String(40)),
    Column("updated_at", String(40)),
)

content_items = Table(
    "content_items",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("creator_id", String(36), nullable=False),
    Column("platform", String(50), nullable=False),
    Column("external_id", String(255), nullable=False),
    Column("title", Text),
    Column("description", Text),
    Column("content_type", String(50), nullable=False),
    Column("published_at", String(40)),
    Column("view_count", Integer),
    Column("like_count", Integer),
    Column("comment_count", Integer),
    Column("url", String(500)),
    Column("topics", Text),
    Column("extra", Text),
    Column("duration", Integer),
    Column("tags", Text),
    Column("language", String(10)),
    Column("is_short", Integer),
    Column("created_at", String(40)),
    Column("updated_at", String(40)),
)

audience_interactions = Table(
    "audience_interactions",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("content_item_id", String(36), nullable=False),
    Column("external_id", String(255), nullable=False),
    Column("text", Text, nullable=False),
    Column("author_handle", String(255)),
    Column("interaction_type", String(50), nullable=False),
    Column("posted_at", String(40)),
    Column("like_count", Integer),
    Column("parent_id", String(255)),
    Column("author_channel_id", String(255)),
    # Extraction bookkeeping (see corp.core.models.content.AudienceInteraction).
    Column("extracted_at", String(40)),
    Column("extracted_prompt_version", String(50)),
    Column("extracted_model", String(100)),
    Column("created_at", String(40)),
    Column("updated_at", String(40)),
)

metrics_snapshots = Table(
    "metrics_snapshots",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("research_run_id", String(36)),
    Column("platform_account_id", String(36)),
    Column("content_item_id", String(36)),
    Column("captured_at", String(40), nullable=False),
    Column("follower_count", Integer),
    Column("view_count", Integer),
    Column("like_count", Integer),
    Column("comment_count", Integer),
    Column("share_count", Integer),
    Column("extra", Text),
)

research_queries = Table(
    "research_queries",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("research_run_id", String(36), nullable=False),
    Column("source", String(50), nullable=False),
    Column("query", Text, nullable=False),
    Column("executed_at", String(40), nullable=False),
    Column("results_seen", Integer, nullable=False, default=0),
    Column("new_results", Integer, nullable=False, default=0),
    Column("duplicate_results", Integer, nullable=False, default=0),
    Column("archive_reference", Text),
    Column("status", String(50), nullable=False),
    Column("error", Text),
    Column("created_at", String(40)),
    Column("updated_at", String(40)),
)

creator_scores = Table(
    "creator_scores",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("creator_id", String(36), nullable=False),
    Column("component_scores", Text, nullable=False),
    Column("aggregate_score", Float, nullable=False),
    Column("computed_hash", String(64), nullable=False),
    Column("confidence_band", String(50), nullable=False),
    Column("rule_version", String(50), nullable=False),
    Column("model_version", String(100), nullable=False),
    Column("research_run_id", String(36)),
    Column("superseded_at", String(40)),
    Column("diagnostics", Text),
    Column("created_at", String(40)),
    Column("updated_at", String(40)),
)

opportunity_scores = Table(
    "opportunity_scores",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("creator_id", String(36), nullable=False),
    Column("problem_cluster_id", String(36), nullable=False),
    Column("component_scores", Text, nullable=False),
    Column("aggregate_score", Float, nullable=False),
    Column("computed_hash", String(64), nullable=False),
    Column("confidence_band", String(50), nullable=False),
    Column("rule_version", String(50), nullable=False),
    Column("model_version", String(100), nullable=False),
    Column("research_run_id", String(36)),
    Column("superseded_at", String(40)),
    Column("diagnostics", Text),
    Column("created_at", String(40)),
    Column("updated_at", String(40)),
)

ALL_TABLES = [
    evidence,
    problem_observations,
    content_items,
    audience_interactions,
    metrics_snapshots,
    research_queries,
    creator_scores,
    opportunity_scores,
]

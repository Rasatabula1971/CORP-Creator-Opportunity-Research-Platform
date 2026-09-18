"""Pydantic schemas for the structured JSON dossier endpoint."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from corp.core.schemas.competitive import CompetitorResponse
from corp.core.schemas.intelligence import (
    ProblemClusterResponse,
    ProblemObservationResponse,
)
from corp.core.schemas.intent import CommercialSignalResponse
from corp.core.schemas.scoring import ComponentScores, OpportunityScoreResponse


class DossierOpportunityResponse(BaseModel):
    cluster: ProblemClusterResponse
    score: OpportunityScoreResponse
    signal: CommercialSignalResponse | None = None
    observations: list[ProblemObservationResponse] = []
    competitors: list[CompetitorResponse] = []


class DossierSignalResponse(BaseModel):
    cluster_label: str
    signal: CommercialSignalResponse


class DataCoverageResponse(BaseModel):
    source_count: int = 0
    evidence_count: int = 0
    cluster_count: int = 0
    observation_count: int = 0
    competitor_count: int = 0


class DossierCreatorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    niche: str | None = None
    status: str


class DossierPlatformAccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    platform: str
    handle: str
    subscriber_count: int | None = None


class DossierScoreResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    component_scores: ComponentScores
    aggregate_score: float
    confidence_band: str


class DossierResponse(BaseModel):
    creator: DossierCreatorResponse
    platform_accounts: list[DossierPlatformAccountResponse] = []
    creator_score: DossierScoreResponse | None = None
    score_band: str = ""
    weights: dict[str, float] = {}
    opportunities: list[DossierOpportunityResponse] = []
    signals: list[DossierSignalResponse] = []
    data_coverage: DataCoverageResponse = DataCoverageResponse()
    generated_at: str = ""


class PersistedDossierResponse(BaseModel):
    """CORP1 Stage 5, T6 -- the real, persisted Dossier row (not the
    live-computed DossierResponse above). ``content`` is the same shape
    DossierGenerator.generate_and_persist builds, plus product_ideas,
    niche_path, and a deterministic recommendation the request-scoped
    endpoint above does not compute."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    creator_id: str
    niche_id: str
    status: str
    generated_at: datetime
    content: dict[str, Any]

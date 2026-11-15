"""Versioned schemas for AI-generated and backend-validated decision reports."""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


SCHEMA_VERSION = "1.2.0"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class DecisionState(str, Enum):
    PROCEED = "proceed"
    PROCEED_WITH_CONDITIONS = "proceed_with_conditions"
    REVISE_PLAN = "revise_plan"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class RecommendationStatus(str, Enum):
    RECOMMENDED = "recommended"
    CONDITIONAL = "conditional"
    NOT_RECOMMENDED = "not_recommended"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class InformationBasis(str, Enum):
    MEASURED = "measured"
    MODELED = "modeled"
    HISTORICAL = "historical"
    ASSUMED = "assumed"
    UNAVAILABLE = "unavailable"
    MIXED = "mixed"


class ProposalStatus(str, Enum):
    PROPOSED = "proposed"
    BACKEND_VALIDATED = "backend_validated"
    REQUIRES_REVISION = "requires_revision"
    REJECTED = "rejected"
    UNVALIDATED = "unvalidated"


class ValidationStatus(str, Enum):
    VALIDATED = "validated"
    REQUIRES_REVISION = "requires_revision"
    REJECTED = "rejected"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class ExecutiveSummary(StrictModel):
    decision: DecisionState
    explanation: str
    supporting_evidence: list[str]
    primary_constraints: list[str]
    actionable: bool


class CropRecommendation(StrictModel):
    crop_id: str
    ranking: int | None = Field(ge=1)
    recommendation_status: RecommendationStatus
    agronomic_suitability_interpretation: str
    benefits: list[str]
    limitations: list[str]
    environmental_compatibility: str
    water_requirements: str
    soil_compatibility: str
    evidence_references: list[str]
    missing_information: list[str]


class CropSchedule(StrictModel):
    crop_id: str
    proposed_planting_date: date | None
    proposed_harvest_date: date | None
    expected_growth_duration_days: int | None = Field(ge=1)
    calendar_constraints: list[str]
    irrigation_considerations: list[str]
    required_assumptions: list[str]
    requires_irrigation: bool
    proposal_status: Literal["proposed"]


class ValidatedSchedule(CropSchedule):
    proposal_status: ProposalStatus


class NumericalClaim(StrictModel):
    evidence_reference: str
    value_path: list[str]
    value: float
    units: str | None


class ResourceFinding(StrictModel):
    basis: InformationBasis
    status: Literal["adequate", "constrained", "unknown", "not_applicable"]
    assessment: str
    evidence_references: list[str]


class ResourceAssessment(StrictModel):
    rainfall: ResourceFinding
    irrigation: ResourceFinding
    crop_water_demand: ResourceFinding
    soil_moisture: ResourceFinding
    soil_properties: ResourceFinding
    nutrient_availability: ResourceFinding
    environmental_constraints: ResourceFinding


class RiskAssessment(StrictModel):
    risk_id: str
    severity: Severity
    description: str
    supporting_evidence: list[str]
    potential_consequences: list[str]
    recommended_mitigation: list[str]
    remaining_uncertainty: str


class ActionItem(StrictModel):
    priority: int = Field(ge=1)
    recommended_action: str
    reason: str
    supporting_evidence: list[str]
    required_farmer_input: list[str]
    additional_verification_required: bool


class SequenceAnalysis(StrictModel):
    scenario_name: str
    assessment: str
    tradeoffs: list[str]
    changes_needed: list[str]
    evidence_references: list[str]


class AIDecisionDraft(StrictModel):
    """Model-owned interpretation. It deliberately excludes validation metadata."""

    executive_summary: ExecutiveSummary
    crop_recommendations: list[CropRecommendation]
    planting_and_harvest_plan: list[CropSchedule]
    resource_assessment: ResourceAssessment
    risk_assessment: list[RiskAssessment]
    agricultural_action_plan: list[ActionItem]
    assumptions: list[str]
    missing_measurements: list[str]
    unresolved_questions: list[str]
    limitations: list[str]
    numerical_claims: list[NumericalClaim] = Field(default_factory=list)
    sequence_analysis: list[SequenceAnalysis] = Field(default_factory=list)


class ReportMetadata(StrictModel):
    schema_version: str
    analysis_identifier: str
    report_identifier: str
    generated_at: datetime
    ai_model_identifier: str
    planning_start: date
    planning_end: date
    openai_response_id: str | None
    ai_response_id: str | None
    ai_provider: str
    token_usage: dict[str, int]


class FieldContext(StrictModel):
    field_identifier: str
    latitude: float
    longitude: float
    area_ha: float
    planning_horizon_days: int
    irrigation_status: Literal["available", "unavailable", "unknown"]


class ValidationCheck(StrictModel):
    check: str
    status: Literal["passed", "warning", "failed", "not_evaluated"]
    message: str


class AuditAndExplainability(StrictModel):
    source_references: list[str]
    assumptions: list[str]
    missing_measurements: list[str]
    conflicts_between_ai_and_backend: list[str]
    validation_status: ValidationStatus
    validation_checks: list[ValidationCheck]
    unresolved_questions: list[str]
    limitations: list[str]
    evidence_catalog: list[dict]
    input_origin: Literal["caller_supplied_analysis"]
    scientific_validation: Literal["not_established"]


class GrainStormDecisionReport(StrictModel):
    """Frontend-ready report with Python-owned facts and validation outcomes."""

    metadata: ReportMetadata
    field_context: FieldContext
    executive_summary: ExecutiveSummary
    crop_recommendations: list[CropRecommendation]
    planting_and_harvest_plan: list[ValidatedSchedule]
    resource_assessment: ResourceAssessment
    risk_assessment: list[RiskAssessment]
    agricultural_action_plan: list[ActionItem]
    audit_and_explainability: AuditAndExplainability
    sequence_analysis: list[SequenceAnalysis]
    estimated_outcomes: dict
    calendar_alternatives: list[dict]

"""Independent validation of AI proposals against deterministic backend evidence."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from uuid import uuid4

from grainstorm.crops import PROFILES
from grainstorm.intelligence.schemas import (
    AIDecisionDraft,
    AuditAndExplainability,
    DecisionState,
    FieldContext,
    GrainStormDecisionReport,
    ProposalStatus,
    ReportMetadata,
    ValidationCheck,
    ValidationStatus,
    ValidatedSchedule,
)


def _all_evidence_references(draft: AIDecisionDraft) -> set[str]:
    references = set(draft.executive_summary.supporting_evidence)
    for crop in draft.crop_recommendations:
        references.update(crop.evidence_references)
    for resource in (
        draft.resource_assessment.rainfall,
        draft.resource_assessment.irrigation,
        draft.resource_assessment.crop_water_demand,
        draft.resource_assessment.soil_moisture,
        draft.resource_assessment.soil_properties,
        draft.resource_assessment.nutrient_availability,
        draft.resource_assessment.environmental_constraints,
    ):
        references.update(resource.evidence_references)
    for risk in draft.risk_assessment:
        references.update(risk.supporting_evidence)
    for action in draft.agricultural_action_plan:
        references.update(action.supporting_evidence)
    return references


def _backend_schedule_matches(context: dict[str, Any], crop_id: str,
                              planting: date | None, harvest: date | None) -> tuple[bool, bool]:
    for scenario in context["scenarios"]:
        for crop in scenario["schedule"]:
            if crop["crop_id"] != crop_id:
                continue
            if crop.get("planting_date") == (planting.isoformat() if planting else None) and \
                    crop.get("harvest_date") == (harvest.isoformat() if harvest else None):
                return True, scenario.get("calendar_feasible") is True
    return False, False


def validate_ai_draft(*, draft: AIDecisionDraft, context: dict[str, Any],
                      analysis_identifier: str, model: str,
                      response_id: str | None, token_usage: dict[str, int]) -> GrainStormDecisionReport:
    checks: list[ValidationCheck] = []
    conflicts: list[str] = []
    hard_failure = False
    revision_required = False
    draft = AIDecisionDraft.model_validate(draft.model_dump())

    crop_ids = [item.crop_id for item in draft.crop_recommendations]
    invalid_crops = sorted(set(crop_ids) - set(PROFILES))
    if invalid_crops:
        hard_failure = True
        checks.append(ValidationCheck(check="supported_crop_identifiers", status="failed",
                                      message=f"Unsupported crop identifiers: {', '.join(invalid_crops)}."))
    else:
        checks.append(ValidationCheck(check="supported_crop_identifiers", status="passed",
                                      message="Every recommended crop exists in the supported crop catalog."))

    available_evidence = {item["id"] for item in context["evidence_catalog"]}
    evidence_by_id = {item["id"]: item for item in context["evidence_catalog"]}
    used_evidence = _all_evidence_references(draft)
    invalid_evidence = sorted(used_evidence - available_evidence)
    if invalid_evidence:
        hard_failure = True
        checks.append(ValidationCheck(check="evidence_references", status="failed",
                                      message=f"Unknown evidence references: {', '.join(invalid_evidence)}."))
    else:
        checks.append(ValidationCheck(check="evidence_references", status="passed",
                                      message="All AI evidence references resolve to supplied backend evidence."))

    for claim in draft.numerical_claims:
        source = evidence_by_id.get(claim.evidence_reference)
        value = source["value"] if source else None
        try:
            for key in claim.value_path:
                value = value[int(key)] if isinstance(value, list) else value[key]
            valid = (isinstance(value, (int, float)) and not isinstance(value, bool)
                     and abs(value - claim.value) <= 1e-8
                     and claim.units == source["units"])
        except (KeyError, IndexError, TypeError, ValueError):
            valid = False
        if not valid:
            hard_failure = True
            checks.append(ValidationCheck(check="numerical_consistency", status="failed",
                                          message=f"Numerical claim does not match {claim.evidence_reference}."))
    if not used_evidence or any(not crop.evidence_references for crop in draft.crop_recommendations):
        revision_required = True
        checks.append(ValidationCheck(check="evidence_coverage", status="warning",
                                      message="Significant conclusions lack supporting references."))
    for resource in draft.resource_assessment.model_dump().values():
        if resource["basis"] == "measured" and not any(
            evidence_by_id.get(ref, {}).get("basis") == "measured"
            for ref in resource["evidence_references"]
        ):
            hard_failure = True
            checks.append(ValidationCheck(check="measurement_basis", status="failed",
                                          message="A modeled, assumed or missing resource was claimed as measured."))
    evaluated_crops = set(context["requested_crop_sequence"])
    for crop in draft.crop_recommendations:
        if crop.crop_id not in evaluated_crops and crop.recommendation_status == "recommended":
            revision_required = True
            conflicts.append(f"{crop.crop_id} lacks location-specific evaluation and cannot be recommended yet.")
    ranks = [crop.ranking for crop in draft.crop_recommendations if crop.ranking is not None]
    if len(ranks) != len(set(ranks)) or len(crop_ids) != len(set(crop_ids)):
        hard_failure = True
        checks.append(ValidationCheck(check="ranking", status="failed", message="Duplicate crop identifiers or ranks."))

    backend_decision = (context.get("backend_decision") or {}).get("decision")
    ai_decision = draft.executive_summary.decision.value
    if backend_decision == "revise_plan" and ai_decision in {
        DecisionState.PROCEED.value, DecisionState.PROCEED_WITH_CONDITIONS.value,
    }:
        revision_required = True
        conflict = (f"AI decision '{ai_decision}' conflicts with deterministic backend decision "
                    f"'{backend_decision}'.")
        conflicts.append(conflict)
        checks.append(ValidationCheck(check="backend_decision_consistency", status="failed", message=conflict))
    else:
        checks.append(ValidationCheck(check="backend_decision_consistency", status="passed",
                                      message="AI decision does not override a deterministic revise-plan result."))

    start = date.fromisoformat(context["field"]["planning_start"])
    end = date.fromisoformat(context["field"]["planning_end"])
    schedule_failed = False
    schedule_unvalidated = False
    validated_schedules = []
    for schedule in draft.planting_and_harvest_plan:
        updated = ValidatedSchedule.model_validate(schedule.model_dump())
        if schedule.crop_id not in PROFILES:
            updated.proposal_status = ProposalStatus.REJECTED
            schedule_failed = True
        elif schedule.proposed_planting_date is None or schedule.proposed_harvest_date is None:
            updated.proposal_status = ProposalStatus.UNVALIDATED
            schedule_unvalidated = True
        elif not (start <= schedule.proposed_planting_date <= schedule.proposed_harvest_date <= end):
            updated.proposal_status = ProposalStatus.REJECTED
            schedule_failed = True
        else:
            duration = (schedule.proposed_harvest_date - schedule.proposed_planting_date).days + 1
            exact, feasible = _backend_schedule_matches(
                context, schedule.crop_id, schedule.proposed_planting_date, schedule.proposed_harvest_date
            )
            if schedule.expected_growth_duration_days != duration:
                updated.proposal_status = ProposalStatus.REJECTED
                schedule_failed = True
            elif exact and feasible:
                updated.proposal_status = ProposalStatus.BACKEND_VALIDATED
            elif exact:
                updated.proposal_status = ProposalStatus.REJECTED
                schedule_failed = True
            else:
                updated.proposal_status = ProposalStatus.UNVALIDATED
                schedule_unvalidated = True
        if schedule.requires_irrigation and context["field"]["irrigation_status"] != "available":
            if updated.proposal_status != ProposalStatus.REJECTED:
                updated.proposal_status = ProposalStatus.REQUIRES_REVISION
            revision_required = True
            conflicts.append(
                f"{schedule.crop_id} assumes irrigation, but irrigation availability is not confirmed."
            )
        validated_schedules.append(updated)

    proposed_pairs = [(s.crop_id, s.proposed_planting_date.isoformat() if s.proposed_planting_date else None,
                       s.proposed_harvest_date.isoformat() if s.proposed_harvest_date else None)
                      for s in draft.planting_and_harvest_plan]
    matching = [s for s in context["scenarios"] if proposed_pairs == [
        (c["crop_id"], c.get("planting_date"), c.get("harvest_date")) for c in s["schedule"]]]
    if not matching:
        revision_required = True
        checks.append(ValidationCheck(check="whole_rotation", status="not_evaluated",
                                      message="The entire proposed sequence has not been simulated together; gaps and resource carryover require rerunning rotation-advice."))
    if any((s["water"].get("unmet_water_mm") or 0) > 0 for s in matching):
        revision_required = True
        checks.append(ValidationCheck(check="water_balance", status="warning",
                                      message="The matching simulation has unmet water demand; supply changes require recalculation."))
    if any(c.get("water_model_warning") for s in matching for c in s["schedule"]):
        revision_required = True
        checks.append(ValidationCheck(check="model_limits", status="warning",
                                      message="The selected plan has explicit water-model limitations."))

    if schedule_failed:
        hard_failure = True
        checks.append(ValidationCheck(check="schedule_feasibility", status="failed",
                                      message="At least one proposed schedule is outside the horizon or repeats a backend-infeasible plan."))
    elif schedule_unvalidated:
        revision_required = True
        checks.append(ValidationCheck(check="schedule_feasibility", status="warning",
                                      message="Alternative dates are proposals only; the deterministic planner has not evaluated them."))
    else:
        checks.append(ValidationCheck(check="schedule_feasibility", status="passed",
                                      message="Proposed dates match a calendar-feasible deterministic scenario."))

    irrigation_conflicts = [item for item in conflicts if "irrigation" in item.lower()]
    checks.append(ValidationCheck(
        check="irrigation_availability",
        status="failed" if irrigation_conflicts else "passed",
        message=("; ".join(irrigation_conflicts) if irrigation_conflicts
                 else "The plan does not claim unavailable irrigation as confirmed."),
    ))

    if hard_failure:
        validation_status = ValidationStatus.REJECTED
    elif revision_required:
        validation_status = ValidationStatus.REQUIRES_REVISION
    elif context["input_quality"].get("critical_generated_count", 0):
        validation_status = ValidationStatus.INSUFFICIENT_EVIDENCE
    else:
        # Passing structural checks cannot establish the truth of free-text agronomy.
        validation_status = ValidationStatus.REQUIRES_REVISION

    executive = draft.executive_summary.model_copy(deep=True)
    if validation_status != ValidationStatus.VALIDATED:
        executive.actionable = False
        if executive.decision in {DecisionState.PROCEED, DecisionState.PROCEED_WITH_CONDITIONS}:
            executive.decision = (DecisionState.REVISE_PLAN if hard_failure or revision_required
                                  else DecisionState.INSUFFICIENT_EVIDENCE)
            executive.explanation = "Backend review requires verification before acting. AI assessment: " + executive.explanation

    field = context["field"]
    replacement_questions = [item["reason"] for item in context["input_quality"].get(
        "recommended_replacements", [])]
    audit = AuditAndExplainability(
        source_references=sorted(used_evidence & available_evidence),
        assumptions=list(dict.fromkeys(draft.assumptions)),
        missing_measurements=list(dict.fromkeys(draft.missing_measurements + replacement_questions)),
        conflicts_between_ai_and_backend=list(dict.fromkeys(conflicts)),
        validation_status=validation_status,
        validation_checks=checks,
        unresolved_questions=list(dict.fromkeys(draft.unresolved_questions)),
        limitations=list(dict.fromkeys(draft.limitations + context.get("backend_limitations", []) + [
            "Free-text agronomic claims and reference relevance require human review; resolving an evidence ID does not prove a claim.",
            "The submitted analysis is caller supplied and is not authenticated as a server-generated measurement record.",
            "Alternative schedules need a new deterministic analysis; this analysis object omits the full simulation inputs.",
        ])),
        evidence_catalog=context["evidence_catalog"],
        input_origin="caller_supplied_analysis",
        scientific_validation="not_established",
    )
    metadata = ReportMetadata(
        schema_version="1.0.0",
        analysis_identifier=analysis_identifier,
        report_identifier=f"gsdr_{uuid4().hex}",
        generated_at=datetime.now(timezone.utc),
        ai_model_identifier=model,
        planning_start=start,
        planning_end=end,
        openai_response_id=response_id,
        token_usage=token_usage,
    )
    field_context = FieldContext(
        field_identifier=field["name"], latitude=field["latitude"], longitude=field["longitude"],
        area_ha=field["area_ha"], planning_horizon_days=field["planning_horizon_days"],
        irrigation_status=field["irrigation_status"],
    )
    return GrainStormDecisionReport(
        metadata=metadata,
        field_context=field_context,
        executive_summary=executive,
        crop_recommendations=draft.crop_recommendations,
        planting_and_harvest_plan=validated_schedules,
        resource_assessment=draft.resource_assessment,
        risk_assessment=draft.risk_assessment,
        agricultural_action_plan=sorted(draft.agricultural_action_plan, key=lambda item: item.priority),
        audit_and_explainability=audit,
    )

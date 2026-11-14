"""Tests for compact AI context, OpenAI handling and independent validation."""
import json
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import patch
from pydantic import ValidationError
import httpx

from fastapi.testclient import TestClient

from grainstorm.api import app, get_intelligence_orchestrator
from grainstorm.intelligence.context_builder import ContextBuildError, build_ai_context
from grainstorm.intelligence.openai_engine import (
    GenerationResult,
    IntelligenceGenerationError,
    OpenAIDecisionEngine,
)
from grainstorm.intelligence.orchestrator import IntelligenceOrchestrator
from grainstorm.intelligence.schemas import AIDecisionDraft, ValidationStatus
from grainstorm.intelligence.validator import validate_ai_draft


def rice_analysis():
    return {
        "status": "preliminary",
        "field": {
            "centroid": {"latitude": 30.34, "longitude": 76.39},
            "area_ha": 4.2684, "method": "polygon approximation",
        },
        "request": {
            "crop_sequence": ["rice"], "preferred_start_date": "2024-04-01",
            "planning_end_date": "2024-09-30", "schedule_mode": "fixed_gap",
        },
        "advice": {"decision_summary": {
            "decision": "revise_plan", "headline": "Do not plant this plan as submitted.",
            "confidence": {"level": "low"},
        }},
        "crop_analysis": {
            "suitability": {"dataset": {"baseline": {"time_period": "1981-2010"}}, "crops": [{
                "crop_id": "rice", "suitability_index_percent": 77.78,
                "suitability_class": {"code": "S", "label": "suitable"},
            }]},
            "calendar": {"crops": [{
                "crop_id": "rice", "planting_date_for_target_year": "2024-02-15",
                "projected_harvest_date": "2024-07-13", "cycle_length_days": 150,
            }]},
            "yield_baseline": {"crops": [{
                "crop_id": "rice", "historical_yield_t_ha": 4.58478,
            }]},
        },
        "soil_context": {"status": "unavailable", "unavailable_properties": ["current_nitrogen"]},
        "environmental_context": {"sources": {"imerg": {"status": "complete", "records": [
            {"date": "2024-04-01", "gpm_precipitation_mm_day": 0},
            {"date": "2024-04-02", "gpm_precipitation_mm_day": 0},
            {"date": "2024-04-03", "gpm_precipitation_mm_day": 42},
        ]}}},
        "input_resolution": {
            "generated_count": 2, "critical_generated_count": 2,
            "generated_inputs": [
                {"path": "field_inputs.initial_mineral_n_kg_ha", "value": 0,
                 "confidence": "low", "note": "Not a measurement", "source": "Zero-credit scenario"},
                {"path": "crop_inputs.rice.planting_windows", "value": [{"start_month_day": "02-01", "end_month_day": "02-28"}],
                 "confidence": "medium", "note": "Coarse window", "source": "GAEZ"},
            ],
            "recommended_replacements": [{"path": "soil_test.mineral_n_kg_ha", "reason": "Add a soil test."}],
        },
        "missing_inputs": [],
        "calculation": {"report": {
            "field": {"name": "Rice field", "area_ha": 4.2684, "irrigation": {"enabled": False}},
            "scenarios": [{
                "name": "rice", "calendar_status": "infeasible", "calendar_feasible": False,
                "schedule_issues": [{"code": "outside_planting_window", "crop": "rice"}],
                "schedule_warnings": [{"code": "water_model_limitation"}],
                "sequence": [{
                    "crop": "rice", "planting_date": "2024-04-01", "planned_harvest_date": "2024-08-28",
                    "duration_days": 150, "planting_window_status": "outside_window",
                    "crop_water_need_mm": 1020.91, "rain_mm": 471.77, "irrigation_mm": 0,
                    "unmet_water_mm": 681.11, "estimated_n_shortfall_kg_ha": 59.14,
                    "estimated_p_shortfall_kg_ha": 12.84, "estimated_k_shortfall_kg_ha": 13.75,
                    "water_model_warning": "Paddy hydrology is incomplete.",
                }],
                "total_rain_mm": 471.77, "total_irrigation_mm": 0,
                "total_irrigation_m3_for_field": 0, "total_unmet_water_mm": 681.11,
                "total_nutrient_shortfall_kg_ha": 85.74,
                "estimated_final_mineral_n_kg_ha": 0,
                "estimated_final_available_p_kg_ha": 0,
                "estimated_final_exchangeable_k_kg_ha": 0,
                "economics_summary": {"status": "not_fully_evaluated", "net_margin_for_field": None},
                "pest_disease_rotation_score": None,
            }],
        }},
        "limitations": ["Historical suitability is not a current-season forecast."],
    }


def ai_draft(*, decision="revise_plan", evidence="scenario.0.calendar",
             crop_id="rice", planting="2024-04-01", harvest="2024-08-28",
             requires_irrigation=True):
    finding = {"basis": "modeled", "status": "constrained", "assessment": "Constrained.",
               "evidence_references": [evidence]}
    return AIDecisionDraft.model_validate({
        "executive_summary": {
            "decision": decision, "explanation": "The submitted plan is infeasible.",
            "supporting_evidence": [evidence], "primary_constraints": ["Calendar", "Water"],
            "actionable": False,
        },
        "crop_recommendations": [{
            "crop_id": crop_id, "ranking": 1, "recommendation_status": "not_recommended",
            "agronomic_suitability_interpretation": "Historical suitability is favorable but not predictive.",
            "benefits": [], "limitations": ["Current soil data unavailable"],
            "environmental_compatibility": "Water constrained", "water_requirements": "High",
            "soil_compatibility": "Unknown", "evidence_references": [evidence],
            "missing_information": ["Soil test"],
        }],
        "planting_and_harvest_plan": [{
            "crop_id": crop_id, "proposed_planting_date": planting,
            "proposed_harvest_date": harvest, "expected_growth_duration_days": 150,
            "calendar_constraints": ["Outside window"], "irrigation_considerations": ["Deficit"],
            "required_assumptions": [], "requires_irrigation": requires_irrigation,
            "proposal_status": "proposed",
        }],
        "resource_assessment": {
            "rainfall": finding, "irrigation": finding, "crop_water_demand": finding,
            "soil_moisture": finding, "soil_properties": finding,
            "nutrient_availability": finding, "environmental_constraints": finding,
        },
        "risk_assessment": [{
            "risk_id": "water_deficit", "severity": "critical", "description": "Water deficit.",
            "supporting_evidence": [evidence], "potential_consequences": ["Stress"],
            "recommended_mitigation": ["Confirm supply"], "remaining_uncertainty": "Paddy losses",
        }],
        "agricultural_action_plan": [{
            "priority": 1, "recommended_action": "Revise dates", "reason": "Infeasible",
            "supporting_evidence": [evidence], "required_farmer_input": ["Irrigation capacity"],
            "additional_verification_required": True,
        }],
        "assumptions": ["GAEZ calendar is coarse"], "missing_measurements": ["Current N/P/K"],
        "unresolved_questions": ["Is irrigation available?"], "limitations": ["Not field validated"],
    })


class ContextBuilderTests(unittest.TestCase):
    def test_missing_day_breaks_dry_spell(self):
        data = rice_analysis()
        data["environmental_context"]["sources"]["imerg"]["records"][1]["date"] = "2024-04-04"
        self.assertEqual(build_ai_context(data)["environment"]["imerg"]["longest_dry_spell"]["days"], 1)

    def test_malformed_analysis_is_client_error(self):
        with self.assertRaises(ContextBuildError):
            build_ai_context({"status": "complete", "calculation": {"report": {"scenarios": [{}]}}, "advice": {}})

    def test_mapped_soil_is_not_labeled_measured(self):
        data = rice_analysis()
        data["soil_context"]["status"] = "complete"
        context = build_ai_context(data)
        self.assertEqual(next(e for e in context["evidence_catalog"] if e["id"] == "soil.context")["basis"], "modeled")

    def test_compacts_analysis_and_preserves_critical_values_and_extremes(self):
        analysis = rice_analysis()
        analysis["environmental_context"]["sources"]["imerg"]["provenance"] = "retrieval metadata" * 1000
        context = build_ai_context(analysis)
        self.assertEqual(context["field"]["area_ha"], 4.2684)
        self.assertEqual(context["crops"][0]["suitability"]["suitability_index_percent"], 77.78)
        self.assertEqual(context["scenarios"][0]["water"]["unmet_water_mm"], 681.11)
        self.assertEqual(context["environment"]["imerg"]["rain_mm"]["maximum"], 42)
        self.assertEqual(context["environment"]["imerg"]["longest_dry_spell"]["days"], 2)
        self.assertLess(len(json.dumps(context)), len(json.dumps(analysis)))

    def test_rejects_incomplete_backend_analysis(self):
        with self.assertRaises(ContextBuildError):
            build_ai_context({"status": "processing"})


class ValidatorTests(unittest.TestCase):
    def test_model_cannot_claim_missing_soil_was_measured(self):
        draft = ai_draft()
        draft.resource_assessment.soil_properties.basis = "measured"
        draft.resource_assessment.soil_properties.evidence_references = ["soil.context"]
        report = self.validate(draft)
        self.assertTrue(any(c.check == "measurement_basis" and c.status == "failed"
                            for c in report.audit_and_explainability.validation_checks))

    def test_model_cannot_certify_schedule(self):
        data = ai_draft().model_dump()
        data["planting_and_harvest_plan"][0]["proposal_status"] = "backend_validated"
        with self.assertRaises(ValidationError):
            AIDecisionDraft.model_validate(data)

    def test_invented_number_is_rejected(self):
        data = ai_draft().model_dump()
        data["numerical_claims"] = [{"evidence_reference": "field.area", "value_path": [], "value": 99, "units": "ha"}]
        report = self.validate(AIDecisionDraft.model_validate(data))
        self.assertTrue(any(c.check == "numerical_consistency" and c.status == "failed"
                            for c in report.audit_and_explainability.validation_checks))

    def test_rejected_report_is_never_actionable(self):
        draft = ai_draft(decision="proceed")
        draft.executive_summary.actionable = True
        report = self.validate(draft)
        self.assertFalse(report.executive_summary.actionable)
        self.assertEqual(report.executive_summary.decision, "revise_plan")

    def test_uncomputed_alternative_is_not_validated(self):
        draft = ai_draft(planting="2024-04-02", harvest="2024-08-29", requires_irrigation=False)
        report = self.validate(draft)
        self.assertEqual(report.planting_and_harvest_plan[0].proposal_status, "unvalidated")

    def validate(self, draft):
        return validate_ai_draft(
            draft=draft, context=build_ai_context(rice_analysis()), analysis_identifier="gsa_test",
            model="test-model", response_id="resp_test", token_usage={"total_tokens": 10},
        )

    def test_rice_reference_scenario_is_rejected_and_missing_data_is_preserved(self):
        report = self.validate(ai_draft())
        self.assertEqual(report.audit_and_explainability.validation_status, ValidationStatus.REJECTED)
        self.assertEqual(report.planting_and_harvest_plan[0].proposal_status, "rejected")
        self.assertIn("Add a soil test.", report.audit_and_explainability.missing_measurements)

    def test_invalid_crop_and_evidence_are_rejected(self):
        report = self.validate(ai_draft(crop_id="invented_crop", evidence="invented.source"))
        self.assertEqual(report.audit_and_explainability.validation_status, ValidationStatus.REJECTED)
        failed = [item.check for item in report.audit_and_explainability.validation_checks
                  if item.status == "failed"]
        self.assertIn("supported_crop_identifiers", failed)
        self.assertIn("evidence_references", failed)

    def test_ai_cannot_override_backend_revise_decision(self):
        report = self.validate(ai_draft(decision="proceed"))
        self.assertTrue(report.audit_and_explainability.conflicts_between_ai_and_backend)

    def test_unconfirmed_irrigation_requires_revision(self):
        draft = ai_draft(planting="2024-02-15", harvest="2024-07-13")
        report = self.validate(draft)
        self.assertEqual(report.planting_and_harvest_plan[0].proposal_status, "rejected")
        self.assertTrue(any("irrigation" in item.lower()
                            for item in report.audit_and_explainability.conflicts_between_ai_and_backend))


class OpenAIEngineTests(unittest.IsolatedAsyncioTestCase):
    async def test_rate_limit_does_not_leak_upstream_body(self):
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key="test-key", max_retries=0,
                             http_client=httpx.AsyncClient(transport=httpx.MockTransport(
                                 lambda request: httpx.Response(429, json={"error": {"message": "private-upstream-detail"}}))))
        with self.assertRaises(IntelligenceGenerationError) as error:
            await OpenAIDecisionEngine(client=client).generate({})
        self.assertNotIn("private-upstream-detail", str(error.exception))

    async def test_real_sdk_transport_and_structured_parsing(self):
        from openai import AsyncOpenAI
        def handler(request):
            payload = json.loads(request.content)
            self.assertEqual(payload["text"]["format"]["type"], "json_schema")
            self.assertFalse(payload["store"])
            return httpx.Response(200, json={
                "id": "resp_mock", "created_at": 0, "object": "response", "status": "completed",
                "model": "test-model", "parallel_tool_calls": False, "tool_choice": "auto", "tools": [],
                "output": [{"id": "msg_mock", "type": "message", "role": "assistant", "status": "completed",
                            "content": [{"type": "output_text", "text": ai_draft().model_dump_json(), "annotations": []}]}],
            })
        client = AsyncOpenAI(api_key="test-key", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        result = await OpenAIDecisionEngine(client=client, model="test-model").generate({})
        self.assertEqual(result.response_id, "resp_mock")

    async def test_missing_parsed_output_and_invalid_output_fail(self):
        for parsed in (None, {"invalid": True}):
            client = SimpleNamespace(responses=SimpleNamespace(parse=AsyncMock(return_value=SimpleNamespace(
                status="completed", output_parsed=parsed))))
            with self.assertRaises(IntelligenceGenerationError):
                await OpenAIDecisionEngine(client=client).generate({})

    async def test_valid_structured_response(self):
        response = SimpleNamespace(
            status="completed", output_parsed=ai_draft(), id="resp_1",
            usage=SimpleNamespace(input_tokens=100, output_tokens=50, total_tokens=150),
        )
        client = SimpleNamespace(responses=SimpleNamespace(parse=AsyncMock(return_value=response)))
        result = await OpenAIDecisionEngine(client=client, model="test-model").generate({"evidence_catalog": []})
        self.assertEqual(result.response_id, "resp_1")
        self.assertEqual(result.token_usage["total_tokens"], 150)
        client.responses.parse.assert_awaited_once()

    async def test_api_failure_is_explicit(self):
        client = SimpleNamespace(responses=SimpleNamespace(parse=AsyncMock(side_effect=TimeoutError())))
        with self.assertRaises(IntelligenceGenerationError):
            await OpenAIDecisionEngine(client=client).generate({})

    async def test_incomplete_model_response_is_explicit(self):
        response = SimpleNamespace(status="incomplete", output_parsed=None, id="resp_2", usage=None)
        client = SimpleNamespace(responses=SimpleNamespace(parse=AsyncMock(return_value=response)))
        with self.assertRaises(IntelligenceGenerationError):
            await OpenAIDecisionEngine(client=client).generate({})


class OrchestratorAndApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_analysis_and_unconfigured_ai_http_errors(self):
        client = TestClient(app)
        self.assertEqual(client.post("/api/v1/intelligence", json={"analysis": {}}).status_code, 422)
        with patch.dict("os.environ", {"OPENAI_API_KEY": ""}):
            self.assertEqual(client.post("/api/v1/intelligence", json={"analysis": rice_analysis()}).status_code, 503)

    async def test_final_report_assembly(self):
        engine = SimpleNamespace(generate=AsyncMock(return_value=GenerationResult(
            draft=ai_draft(), model="test-model", response_id="resp_3", token_usage={}
        )))
        result = await IntelligenceOrchestrator(engine).analyze(rice_analysis())
        self.assertEqual(result.metadata.ai_model_identifier, "test-model")
        self.assertEqual(result.field_context.area_ha, 4.2684)

    async def test_endpoint_returns_structured_report(self):
        orchestrator = SimpleNamespace(analyze=AsyncMock())
        engine = SimpleNamespace(generate=AsyncMock(return_value=GenerationResult(
            draft=ai_draft(), model="test-model", response_id="resp_4", token_usage={}
        )))
        orchestrator.analyze.return_value = await IntelligenceOrchestrator(engine).analyze(rice_analysis())
        app.dependency_overrides[get_intelligence_orchestrator] = lambda: orchestrator
        self.addCleanup(app.dependency_overrides.clear)
        response = TestClient(app).post("/api/v1/intelligence", json={"analysis": rice_analysis()})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["metadata"]["schema_version"], "1.0.0")


if __name__ == "__main__":
    unittest.main()

"""Tests for compact AI context, Gemini handling and independent validation."""
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
from grainstorm.intelligence.common import (
    GenerationResult,
    IntelligenceGenerationError,
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


class GeminiEngineTests(unittest.IsolatedAsyncioTestCase):
    async def test_provider_errors_are_distinct_and_sanitized(self):
        from google.genai.errors import ClientError, ServerError
        from grainstorm.intelligence.gemini_engine import GeminiDecisionEngine
        for code, expected in ((400, "gemini_invalid_request"), (401, "gemini_invalid_key"),
                               (403, "gemini_access_denied"), (404, "gemini_model_unavailable"),
                               (503, "gemini_service_unavailable")):
            error_type = ServerError if code >= 500 else ClientError
            client = self.client(error=error_type(code, {"error": {"message": "private-key-and-url"}}))
            with self.assertRaises(IntelligenceGenerationError) as caught:
                await GeminiDecisionEngine(client=client).generate({})
            self.assertEqual(caught.exception.code, expected)
            self.assertNotIn("private-key-and-url", str(caught.exception))

    async def test_duplicate_requests_generate_once_and_model_changes_cache_key(self):
        import asyncio
        import tempfile
        from grainstorm.intelligence.cache import DecisionCache
        async def generate(context):
            await asyncio.sleep(0.01)
            return GenerationResult(ai_draft(), "gemini-test", "id", {})
        with tempfile.TemporaryDirectory() as directory:
            cache = DecisionCache(directory + "/ai.sqlite3")
            engine = SimpleNamespace(model="gemini-test", generate=AsyncMock(side_effect=generate))
            orchestrator = IntelligenceOrchestrator(engine, cache)
            await asyncio.gather(orchestrator.analyze(rice_analysis()), orchestrator.analyze(rice_analysis()))
            self.assertEqual(engine.generate.await_count, 1)
            engine.model = "another-model"
            await orchestrator.analyze(rice_analysis())
            self.assertEqual(engine.generate.await_count, 2)

    async def test_configured_retry_is_bounded(self):
        from grainstorm.intelligence.gemini_engine import GeminiDecisionEngine
        with patch.dict("os.environ", {"GRAINSTORM_AI_RETRY_ATTEMPTS": "1"}):
            client = self.client()
            client.models.generate_content.side_effect = [OSError("offline"), self.response()]
            await GeminiDecisionEngine(client=client).generate({})
            self.assertEqual(client.models.generate_content.await_count, 2)

    async def test_unsupported_provider_and_model_config(self):
        from grainstorm.intelligence.gemini_engine import GeminiDecisionEngine
        from grainstorm.intelligence.common import IntelligenceConfigurationError
        with patch.dict("os.environ", {"GRAINSTORM_AI_PROVIDER": "openai"}):
            with self.assertRaises(IntelligenceConfigurationError):
                GeminiDecisionEngine()
        with patch.dict("os.environ", {"GRAINSTORM_GEMINI_MODEL": "my-gemini-model"}):
            self.assertEqual(GeminiDecisionEngine().model, "my-gemini-model")

    async def test_official_sdk_schema_and_response_transport(self):
        from google import genai
        from google.genai import types
        from grainstorm.intelligence.gemini_engine import GeminiDecisionEngine
        def handler(request):
            body = json.loads(request.content)
            self.assertEqual(body["generationConfig"]["responseMimeType"], "application/json")
            self.assertIn("responseSchema", body["generationConfig"])
            return httpx.Response(200, json={
                "candidates": [{"content": {"role": "model", "parts": [{"text": ai_draft().model_dump_json()}]}, "finishReason": "STOP"}],
                "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 20, "totalTokenCount": 30},
                "modelVersion": "gemini-test", "responseId": "mock-response",
            })
        client = genai.Client(api_key="fake-test-key", vertexai=False,
            http_options=types.HttpOptions(async_client_args={"transport": httpx.MockTransport(handler)})).aio
        try:
            result = await GeminiDecisionEngine(client=client).generate({})
            self.assertEqual(result.token_usage["total_tokens"], 30)
        finally:
            await client.aclose()

    def client(self, response=None, error=None):
        return SimpleNamespace(models=SimpleNamespace(generate_content=AsyncMock(return_value=response, side_effect=error)))

    def response(self, **kwargs):
        values = dict(text=ai_draft().model_dump_json(), candidates=[SimpleNamespace(finish_reason="STOP")],
                      model_version="gemini-test", response_id="gemini-response",
                      usage_metadata=SimpleNamespace(prompt_token_count=100, candidates_token_count=50, total_token_count=150))
        values.update(kwargs)
        return SimpleNamespace(**values)

    async def test_request_schema_model_usage(self):
        from grainstorm.intelligence.gemini_engine import GeminiDecisionEngine
        client = self.client(self.response())
        result = await GeminiDecisionEngine(client=client, model="gemini-test").generate({"evidence_catalog": []})
        self.assertEqual(result.token_usage["total_tokens"], 150)
        call = client.models.generate_content.call_args.kwargs
        self.assertEqual(call["model"], "gemini-test")
        self.assertEqual(call["config"].response_mime_type, "application/json")
        self.assertIs(call["config"].response_schema, AIDecisionDraft)

    async def test_invalid_and_incomplete(self):
        from grainstorm.intelligence.gemini_engine import GeminiDecisionEngine
        for response in (self.response(text="bad json"), self.response(candidates=[]),
                         self.response(candidates=[SimpleNamespace(finish_reason="MAX_TOKENS")])):
            with self.assertRaises(IntelligenceGenerationError):
                await GeminiDecisionEngine(client=self.client(response)).generate({})

    async def test_quota_and_network(self):
        from grainstorm.intelligence.gemini_engine import GeminiDecisionEngine
        from google.genai.errors import ClientError
        for error, expected in ((ClientError(429, {"error": {"message": "secret"}}), "gemini_quota_exhausted"),
                                (OSError("secret"), "gemini_request_failed")):
            client = self.client(error=error)
            with self.assertRaises(IntelligenceGenerationError) as caught:
                await GeminiDecisionEngine(client=client).generate({})
            self.assertEqual(caught.exception.code, expected)
            self.assertNotIn("secret", str(caught.exception))
            self.assertEqual(client.models.generate_content.await_count, 1)

    async def test_missing_credentials(self):
        from grainstorm.intelligence.gemini_engine import GeminiDecisionEngine
        from grainstorm.intelligence.common import IntelligenceConfigurationError
        with patch.dict("os.environ", {"GEMINI_API_KEY": ""}):
            with self.assertRaises(IntelligenceConfigurationError):
                await GeminiDecisionEngine().generate({})

    async def test_timeout_and_input_limit(self):
        import asyncio
        from grainstorm.intelligence.gemini_engine import GeminiDecisionEngine
        async def slow(**kwargs):
            await asyncio.sleep(10)
        client = self.client()
        client.models.generate_content.side_effect = slow
        with self.assertRaises(IntelligenceGenerationError) as caught:
            await GeminiDecisionEngine(client=client, timeout_seconds=1).generate({})
        self.assertEqual(caught.exception.code, "gemini_timeout")
        with patch.dict("os.environ", {"GRAINSTORM_AI_MAX_INPUT_BYTES": "1024"}):
            client = self.client()
            with self.assertRaises(IntelligenceGenerationError):
                await GeminiDecisionEngine(client=client).generate({"large": "x" * 2000})
            client.models.generate_content.assert_not_awaited()

    async def test_cache_persists_and_call_budget(self):
        import tempfile
        from pathlib import Path
        from grainstorm.intelligence.cache import DecisionCache
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "decisions.sqlite3")
            engine = SimpleNamespace(model="gemini-test", generate=AsyncMock(return_value=GenerationResult(
                ai_draft(), "gemini-test", "id", {})))
            await IntelligenceOrchestrator(engine, DecisionCache(path)).analyze(rice_analysis())
            await IntelligenceOrchestrator(engine, DecisionCache(path)).analyze(rice_analysis())
            self.assertEqual(engine.generate.await_count, 1)
            cache = DecisionCache(path)
            cache.reserve("failed", 1)
            cache.finish("failed", None)
            with self.assertRaises(IntelligenceGenerationError) as caught:
                cache.reserve("failed", 1)
            self.assertEqual(caught.exception.code, "analysis_call_limit")


class OrchestratorAndApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_endpoint_preserves_safe_error_classification(self):
        orchestrator = SimpleNamespace(analyze=AsyncMock(side_effect=IntelligenceGenerationError(
            "Check API credits.", code="insufficient_quota", status_code=503)))
        app.dependency_overrides[get_intelligence_orchestrator] = lambda: orchestrator
        self.addCleanup(app.dependency_overrides.clear)
        response = TestClient(app).post("/api/v1/intelligence", json={"analysis": rice_analysis()})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"]["code"], "insufficient_quota")
        self.assertFalse(response.json()["detail"]["retryable"])

    async def test_invalid_analysis_and_unconfigured_ai_http_errors(self):
        import tempfile
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        settings = patch.dict("os.environ", {"GRAINSTORM_AI_CACHE_DB": directory.name + "/ai.sqlite3"})
        settings.start()
        self.addCleanup(settings.stop)
        self.addCleanup(lambda: delattr(app.state, "intelligence_orchestrator"))
        client = TestClient(app)
        self.assertEqual(client.post("/api/v1/intelligence", json={"analysis": {}}).status_code, 422)
        with patch.dict("os.environ", {"GEMINI_API_KEY": ""}):
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
        self.assertEqual(response.json()["metadata"]["schema_version"], "1.1.0")


if __name__ == "__main__":
    unittest.main()

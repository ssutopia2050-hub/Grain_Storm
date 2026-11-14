# Grain Storm intelligence API v1

The optional intelligence layer uses OpenAI to assess the evidence, compare crop
options, propose revisions and prioritize farmer actions. Python preserves the
scientific analysis and independently checks the AI draft. No new database or
background AI worker is required.

## Architecture

`rotation-advice analysis → context_builder → OpenAI Responses API → validator → GrainStormDecisionReport`

- `src/grainstorm/api.py`: FastAPI entry point; existing endpoints continue to work without an OpenAI key.
- `rotation_advice.py`: combines polygon geometry, FAO GAEZ suitability/calendar/yield,
  SSURGO mapped soil context, IMERG/ERA5 historical weather or bounded forecast/scenario,
  automatic input resolution and `planner.simulate_scenarios`.
- `context.py` and `satellite_jobs.py`: existing SQLite environmental cache and satellite acquisition.
- `intelligence/context_builder.py`: deterministic compact evidence with stable IDs and original paths.
- `intelligence/schemas.py`: model-owned `AIDecisionDraft` and backend-assembled `GrainStormDecisionReport`.
- `intelligence/openai_engine.py`: official asynchronous Python SDK, Responses `parse`, Pydantic Structured Outputs.
- `intelligence/validator.py`: constraints, evidence references, numerical claims, schedule checks and report assembly.
- `intelligence/orchestrator.py`: one model generation and one validation pass; no recursive calls.

The existing application does not persist analyses. The endpoint accepts the complete
analysis object and computes a SHA-256 content identifier. This is an identifier, not
a retrieval token. Caller-submitted analysis is not authenticated as server-generated;
the audit explicitly records that origin. Keep the original analysis for inspection.

## Setup

Install project dependencies with `python -m pip install -e .` in the environment.
Configure these on the backend only:

| Variable | Requirement |
| --- | --- |
| `OPENAI_API_KEY` | Required to call OpenAI; keep in hosting secrets, never frontend code or Git. |
| `GRAINSTORM_AI_MODEL` | Optional; defaults to `gpt-6-astra`. Set an available Responses/Structured Outputs model for your account. |
| `GRAINSTORM_AI_TIMEOUT_SECONDS` | Optional; default 60, permitted range 1–180 seconds. |

The API uses `store=False`, a maximum 8,000 output tokens, SDK retries capped at two,
and an overall timeout including retries. Each request incurs API usage; no live
generation is required for tests. There is no report cache in this MVP.
Restart the server after setting environment variables.

## Endpoints and frontend flow

1. Call the existing `POST /v1/rotation-advice`.
2. Wait until its status is `complete` or `preliminary`.
3. Send that JSON object inside `analysis` to `POST /api/v1/intelligence`.
4. Render the executive summary, crop options, proposed schedule, resources, risks and actions.
5. Check audit validation and `executive_summary.actionable` before presenting a plan as ready.

```javascript
const report = await fetch(`${backendUrl}/api/v1/intelligence`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ analysis: rotationAdviceResponse })
});
if (!report.ok) throw new Error(await report.text());
const decision = await report.json();
```

Test with the downloaded rice response (no rewriting of that file):

```bash
jq '{analysis: .}' /Users/shikharsharma/Downloads/response_1794674438310.json | \
  curl --fail-with-body http://127.0.0.1:8000/api/v1/intelligence \
  -H 'Content-Type: application/json' --data-binary @-
```

`GET /api/v1/intelligence/schema` returns the full versioned JSON Schema. Swagger
at `/docs` also exposes the request and `GrainStormDecisionReport` models.

## Report contract

| Section | Fields and ownership |
| --- | --- |
| `metadata` | Python-owned schema version, content analysis ID, UUID report ID, UTC timestamp, actual model ID, planning dates, response ID and token counts. |
| `field_context` | Python copies field ID/name, coordinates, hectares, horizon and irrigation status from the supplied analysis. |
| `executive_summary` | AI decision, explanation, evidence and constraints; Python forces non-actionable status and revises a conflicting proceed decision. |
| `crop_recommendations` | AI crop ID/rank/status, suitability interpretation, benefits, limitations, environmental/water/soil compatibility, evidence and missing inputs. |
| `planting_and_harvest_plan` | Crop/date/duration proposals with constraints and assumptions; proposal validation status belongs to Python. |
| `resource_assessment` | Rainfall, irrigation, water demand, moisture, soil, nutrients and environmental constraints, each with basis/status/evidence. |
| `risk_assessment` | Risk ID, severity, description, evidence, consequences, mitigation and uncertainty. |
| `agricultural_action_plan` | Priority, action, reason, evidence, farmer input and verification requirement. |
| `audit_and_explainability` | Evidence catalog, assumptions, missing measurements, conflicts, checks, unresolved questions and limitations. Python owns validation status and scientific-validation flag. |

Decision states: `proceed`, `proceed_with_conditions`, `revise_plan`, `insufficient_evidence`.
Information basis: `measured`, `modeled`, `historical`, `assumed`, `unavailable`, `mixed`.
Schedule states after validation: `backend_validated`, `requires_revision`, `rejected`, `unvalidated`.
The generation schema only permits `proposed`; the model cannot certify a schedule.
Report schema version is `1.0.0`. Extra generated fields and nonfinite floats are rejected.

Example response fragment (illustrative, not a live model result):

```json
{
  "executive_summary": {
    "decision": "revise_plan",
    "explanation": "The submitted schedule fails the supplied calendar and water constraints.",
    "supporting_evidence": ["scenario.0.calendar", "scenario.0.water"],
    "primary_constraints": ["Planting window", "Water deficit"],
    "actionable": false
  }
}
```

## Context and validation rules

Context retains source paths, units, crop calculations, nutrient budgets, rooting
depths, rotation effects, water-model diagnostics, soil status, missing inputs,
generated baselines and source limitations. Repetitive acquisition metadata and
raw raster descriptors are removed. Available daily records are summarized with
minimum/maximum dates, totals, dry spells (rain below 1 mm/day) and all days at
or above 25 mm rainfall. Those thresholds describe aggregation, not crop-damage
thresholds. Missing dates break dry spells. The context is capped at 160 KB;
input JSON is capped at 2 MB after parsing. Configure ingress body-size limits too.

The normal rotation response omits daily weather records. Consequently it cannot
establish rainfall extremes or growth-stage timing from season totals; this
limitation is included in context. Existing dual-coefficient stress diagnostics
are retained when available.

The validator checks supported crop IDs, duplicate ranks, reference existence,
structured numerical claims against exact evidence values and units, measured
versus modeled basis, date ordering, duration, horizon, matching complete scenario,
backend calendar failure, water deficit and unconfirmed irrigation. Unknown
alternatives remain unvalidated. Backend metadata and evidence are never taken
from model output. Evidence context is explicitly treated as untrusted data in
the model instructions.

No free-text validator can establish that an agronomic statement is true merely
because it cites an existing reference. The MVP therefore requires review for
all reports and never claims scientific validation. Numeric claims in prose
must be mirrored in the structured claim list, but exhaustive natural-language
claim checking is not implemented. Do not treat a well-formed report as proof.

Changed schedules cannot be recalculated from the saved response alone because
the original complete weather/configuration is not retained. Resubmit those
proposals to `/v1/rotation-advice` with verified inputs. No alternative is silently
promoted to a validated recommendation. Public deployment needs authentication,
rate limits and spending controls before exposing this paid endpoint.

## Errors and tests

- 422: incomplete/malformed/oversized analysis; no model call is made.
- 503: missing key, unavailable SDK or invalid backend AI configuration.
- 502: API/network/rate-limit failure, timeout, refusal, incomplete generation or invalid structured result.
- Upstream quota exhaustion returns 503 with `detail.code: insufficient_quota` and
  `retryable: false`; check API credits and project billing limits.
- Temporary upstream throttling returns 429 with `detail.code: rate_limit_exceeded`
  and `retryable: true`. Generation errors return a safe `{code, message, retryable}`
  object under `detail`; raw upstream messages are never exposed.
- 200: report returned, including rejected/revision-required proposals. Inspect the audit.

Errors do not expose keys or upstream response bodies and never substitute invented advice.

```bash
python -m unittest tests.test_intelligence -v
python -m unittest discover -s tests -q
```

Tests use a representative rice fixture and mocked generation, including the real
SDK over a mocked HTTP transport. No API key or network is needed.

## Remaining work

Persist authenticated analysis/configuration snapshots for ID-based retrieval and
deterministic alternative simulation; add stage-resolved weather evidence;
evaluate agronomic claims against expert-reviewed cases; validate paddy hydrology;
add deployment authentication/rate limits and a bounded report cache; then run a
live model evaluation with account access and approved spend.

Official SDK pattern: [Structured Outputs with Responses](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses).

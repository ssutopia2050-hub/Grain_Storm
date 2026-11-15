# Grain Storm Gemini intelligence API

The optional decision layer uses Google's official `google-genai` SDK and Gemini
Developer API. Scientific analysis continues to run without an AI key.

## Architecture and repository map

`POST /v1/rotation-advice → context_builder → Gemini → AIDecisionDraft → independent validator → GrainStormDecisionReport`

The existing FastAPI backend assembles source-backed analysis in
`rotation_advice.py`, using polygon geometry, FAO GAEZ suitability/calendars/yields,
SSURGO mapped soil context, IMERG/ERA5 weather, input resolution and
`planner.simulate_scenarios`. Environmental acquisition and SQLite caching remain
in `context.py` and `satellite_jobs.py`.

The intelligence package reuses `context_builder.py`, `schemas.py` and
`validator.py`. `gemini_engine.py` handles async generate_content and Pydantic JSON
output. `common.py` holds provider-neutral errors/results; `prompts.py` versions
the instructions. `cache.py` stores AI drafts and atomic call reservations in
SQLite. `orchestrator.py` checks the cache, generates once and independently
validates each report. The old OpenAI adapter and project dependency were removed;
there is no Ollama integration or provider fallback.

## Setup and free-tier verification

1. Obtain a Gemini API key in [Google AI Studio](https://aistudio.google.com/api-keys).
2. Select a project using the free tier. Check its billing status and quotas in
   AI Studio. Do not enable paid billing if you require free-only usage.
3. Check the selected model's current availability and free-tier eligibility on
   [Google's pricing page](https://ai.google.dev/gemini-api/docs/pricing) and your
   account's model/quota listing. The default model name does not guarantee
   access or eligibility.
4. Install dependencies and configure environment variables, then restart.

Application limits cannot guarantee zero charges when the Google project has paid
billing enabled. The application never upgrades billing, changes providers or
switches models automatically. Google free-tier data handling may differ from
paid-tier terms; review those before sending real farm information.

```bash
python -m pip install -e .
export GEMINI_API_KEY='your-key'
export GRAINSTORM_AI_PROVIDER=gemini
export GRAINSTORM_GEMINI_MODEL=gemini-2.5-flash
uvicorn grainstorm.api:app --reload
```

Keep keys server-side in deployment secrets. Shell exports apply to that shell;
no dotenv loading was added. Never commit keys or filled .env files. The SDK is
explicitly configured for the Developer API, rather than Vertex AI.

| Variable | Default / bounds |
| --- | --- |
| GEMINI_API_KEY | Required for a new generation |
| GRAINSTORM_AI_PROVIDER | gemini; other providers are rejected |
| GRAINSTORM_GEMINI_MODEL | gemini-2.5-flash; configure a model available to your account |
| GRAINSTORM_AI_TIMEOUT_SECONDS | 60; 1–180, overall generation including retry waits |
| GRAINSTORM_AI_RETRY_ATTEMPTS | 0; 0–2 additional attempts for transient network/5xx failures |
| GRAINSTORM_AI_MAX_CONCURRENT | 1; 1–8 simultaneous generations per API process |
| GRAINSTORM_AI_MAX_CALLS_PER_ANALYSIS | 1; 1–3 generation invocations per normalized cache key |
| GRAINSTORM_AI_MAX_INPUT_BYTES | 160000; 1024–160000 bytes of serialized compact context |
| GRAINSTORM_AI_CACHE_DB | data/cache/intelligence.sqlite3; use writable persistent absolute path in deployment |

Restart the API when changing configuration. Maximum output is 8,000 tokens.
SDK retries are disabled; only the bounded application retries apply. 429 quota
errors are not retried. Total possible HTTP attempts per cache key are bounded
by calls-per-analysis times (1 + retry-attempts).

The shared orchestrator limits concurrency in a single process. Use one API
process for this MVP; global concurrency across hosts is not enforced. The cache
uses SQLite transactions to reserve each analysis atomically. The stable key
includes normalized context, configured model, prompt content/version and schema
version. Identical analyses reuse the draft across restarts, then run validation
again and receive fresh report metadata. Cache hits require no Gemini call.
Token usage on a cached draft describes its original generation.

Failed calls consume the configured call budget. Review the error before
increasing the budget and restarting. A process killed during generation can
leave a running reservation; inspect that record before clearing it. Never clear
reservations while another process may be generating. There is no automatic
expiry/retry of interrupted calls that could silently consume quota twice.
The database contains farm context interpretations and should stay private.
Cache cleanup, retention policies and administration UI remain future work.

## API and frontend flow

Endpoints remain:
- `POST /v1/rotation-advice`: original agricultural analysis.
- `POST /api/v1/intelligence`: accepts `{"analysis": <whole analysis response>}`.
- `GET /api/v1/intelligence/schema`: complete final JSON Schema.
- `/docs`: Swagger request and report schema.

Wait for analysis status `complete` or `preliminary`; processing or missing
calculation results are rejected before generation. Analyses are not persisted
for identifier lookup; the content hash identifies the caller-provided object
but does not authenticate it as a server-owned record.

```javascript
const response = await fetch(`${backendUrl}/api/v1/intelligence`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ analysis: rotationAdviceResponse })
});
if (!response.ok) throw new Error(await response.text());
const decision = await response.json();
```

```bash
jq '{analysis: .}' /Users/shikharsharma/Downloads/response_1794674438310.json |
curl --fail-with-body http://127.0.0.1:8000/api/v1/intelligence \
  -H 'Content-Type: application/json' --data-binary @-
```

## Report schema and validation

`GrainStormDecisionReport` version 1.2.0 retains all nine report sections:
metadata, field_context, executive_summary, crop_recommendations,
planting_and_harvest_plan, resource_assessment, risk_assessment,
agricultural_action_plan, audit_and_explainability.

Metadata now adds `ai_provider: "gemini"` and `ai_response_id`. The deprecated
`openai_response_id` is retained as null. Model identity/token usage comes from
the SDK; field facts, content/report IDs, timestamp and validation outcomes come
from Python. Existing request shape and endpoint path are unchanged.

Version 1.2 adds `sequence_analysis` (Gemini compares every evaluated order),
`estimated_outcomes` and `calendar_alternatives` (Python calculations). Historical
yield is multiplied by hectares to estimate field production benchmarks. A labeled
0.8/1.0/1.2 baseline-yield sensitivity explores assumed production changes; these
are illustrative scenarios, not probability bounds or stress-adjusted forecasts.
Water deficits and elemental N/P/K shortfalls are converted to whole-field quantities.
Indicative withdrawal divides water deficit by supplied application efficiency,
without claiming an exact irrigation schedule. Prices and costs remain unknown
unless supplied. Calendar screening searches supplied/provisional windows in
each evaluated order with supplied maturity and turnaround gaps; alternatives
do not receive revised water/nutrient/yield claims without resimulation.

Gemini receives exact permitted scalar numerical-claim paths and catalog units.
The validator still rejects mismatched values/units; failure diagnostics now
include the supplied path, value and units and resolved source value/units.
An irrigation-disabled simulation is labeled unknown physical availability.
Crop-specific GAEZ baseline overrides supersede general dataset metadata.

The model generates only `AIDecisionDraft`. Its schedule status can only be
`proposed`. Python assigns backend_validated, unvalidated, rejected or
requires_revision after checking dates, horizons, duration, complete-sequence
matching, irrigation availability, backend infeasibility and water constraints.
It checks valid crop IDs/ranks, evidence reference existence, structured numeric
claims and units, and measured versus modeled information. Existing rice
hydrology limitations, missing soil measurements, historical yield/suitability
and generated-baseline uncertainty remain in the evidence and final audit.

Extra fields and nonfinite floats are rejected. Reports remain non-actionable
until further review; resolving evidence IDs cannot establish every free-text
agronomic claim. Historical suitability is not crop-success probability.
Proposed alternatives cannot be resimulated from saved analysis alone because
the complete original configuration/weather is absent. Resubmit revised inputs
to rotation-advice before relying on alternative dates.

The compact context keeps scientific constraints, units, source paths, nutrient
budgets, rooting depth, rotations, water diagnostics and assumptions. When daily
records exist it retains extreme dates, dry spells (rain below 1 mm/day), and all
days at or above 25 mm rainfall. These are aggregation thresholds, not damage
thresholds. Missing dates break dry spells. The ordinary rotation response omits
daily weather records; seasonal totals cannot establish extremes or stage timing.
That limitation is explicitly communicated. Input analysis is limited to 2 MB
after JSON parsing; configure ingress body limits separately.

## Controlled errors and tests

- 422: malformed/incomplete analysis or oversized context.
- 503: missing key, unsupported provider, invalid configuration or unavailable cache.
- 429 gemini_quota_exhausted: check free-tier quotas in AI Studio; no automatic retry.
- 429 analysis_call_limit: generation budget already consumed for this cache key.
- 409 analysis_busy: identical generation running, or interrupted reservation.
- 504 gemini_timeout: overall timeout reached.
- 502 gemini_request_failed / gemini_incomplete / gemini_invalid_output: controlled upstream or output failure.

Generation errors use `detail: {code, message, retryable}`. Raw provider bodies
and credentials are not exposed. No paid or deterministic fallback is silently
returned as an AI result. The original agricultural endpoint remains available.

```bash
python -m unittest tests.test_intelligence -v
python -m unittest discover -s tests -q
```

Tests mock Gemini, including the official SDK over httpx MockTransport. They do
not make real Gemini calls or consume quota. Remaining work: live Gemini model
evaluation (only with explicit authorization), trusted analysis snapshots,
deterministic recalculation of alternatives, expert review, temporal evidence,
paddy hydrology, access control, cache retention and distributed request limits.

References: [Google SDK](https://googleapis.github.io/python-genai/),
[structured outputs](https://ai.google.dev/gemini-api/docs/structured-output),
[pricing](https://ai.google.dev/gemini-api/docs/pricing).

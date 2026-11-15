"""Gemini Developer API adapter. Never selects another model or paid provider."""
from __future__ import annotations

import asyncio
import json
import os

from pydantic import ValidationError
from grainstorm.intelligence.common import (
    GenerationResult, IntelligenceConfigurationError, IntelligenceGenerationError,
)
from grainstorm.intelligence.prompts import SYSTEM_INSTRUCTIONS
from grainstorm.intelligence.schemas import AIDecisionDraft


def classify_error(exc: Exception) -> IntelligenceGenerationError:
    """Expose only allowlisted categories, never upstream bodies or URLs."""
    code = getattr(exc, "code", None)
    data = getattr(exc, "response_json", None)
    error = data.get("error", {}) if isinstance(data, dict) else {}
    details = error.get("details", []) if isinstance(error, dict) else []
    message = str(error.get("message", "")).lower() if isinstance(error, dict) else ""
    reasons = {item.get("reason") for item in details if isinstance(item, dict)}
    if reasons & {"API_KEY_INVALID", "API_KEY_EXPIRED", "API_KEY_NOT_FOUND"} or code == 401:
        return IntelligenceGenerationError("Gemini rejected the API key. Replace GEMINI_API_KEY with an active Google AI Studio key and restart.", code="gemini_invalid_key", status_code=503)
    if code == 403:
        return IntelligenceGenerationError("Gemini access was denied. Check API-key restrictions, project permissions and regional availability.", code="gemini_access_denied", status_code=503)
    if code == 404:
        return IntelligenceGenerationError("The configured Gemini model or API resource is unavailable. Check GRAINSTORM_GEMINI_MODEL against your account's available models.", code="gemini_model_unavailable", status_code=503)
    if code == 400:
        if "api key not valid" in message:
            return IntelligenceGenerationError("Gemini rejected the API key. Check GEMINI_API_KEY.", code="gemini_invalid_key", status_code=503)
        if "schema" in message and any(word in message for word in ("complex", "nesting", "depth", "states")):
            return IntelligenceGenerationError("Gemini rejected the output schema complexity or nesting depth.", code="gemini_schema_too_complex")
        if "schema" in message:
            return IntelligenceGenerationError("Gemini rejected a structured-output schema field.", code="gemini_schema_rejected")
        if "location" in message or "region" in message or "country" in message:
            return IntelligenceGenerationError("Gemini rejected the service location or account region.", code="gemini_region_unsupported", status_code=503)
        return IntelligenceGenerationError("Gemini rejected the request configuration. The model may not support this output schema or generation settings; backend review is required.", code="gemini_invalid_request", status_code=502)
    if code in {500, 502, 503, 504}:
        return IntelligenceGenerationError("Gemini is temporarily unavailable. Retry within your configured call budget.", code="gemini_service_unavailable", retryable=True, status_code=503)
    if isinstance(exc, (ValueError, TypeError)):
        return IntelligenceGenerationError("The Gemini SDK rejected local request settings or the output schema before generation.", code="gemini_sdk_configuration", status_code=503)
    return IntelligenceGenerationError("Gemini request failed due to a network or unclassified provider error.", code="gemini_request_failed", retryable=True)


def bounded_setting(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
        if not low <= value <= high:
            raise ValueError()
        return value
    except ValueError as exc:
        raise IntelligenceConfigurationError(f"{name} must be between {low} and {high}.") from exc


class GeminiDecisionEngine:
    def __init__(self, *, client=None, model: str | None = None, timeout_seconds: int | None = None):
        if os.environ.get("GRAINSTORM_AI_PROVIDER", "gemini").lower() != "gemini":
            raise IntelligenceConfigurationError("Only the Gemini provider is enabled. Set GRAINSTORM_AI_PROVIDER=gemini.")
        self.model = model or os.environ.get("GRAINSTORM_GEMINI_MODEL", "gemini-2.5-flash")
        self.timeout = timeout_seconds if timeout_seconds is not None else bounded_setting(
            "GRAINSTORM_AI_TIMEOUT_SECONDS", 60, 1, 180)
        if not 1 <= self.timeout <= 180:
            raise IntelligenceConfigurationError("AI timeout must be between 1 and 180 seconds.")
        self.retries = bounded_setting("GRAINSTORM_AI_RETRY_ATTEMPTS", 0, 0, 2)
        self.max_input = bounded_setting("GRAINSTORM_AI_MAX_INPUT_BYTES", 160000, 1024, 160000)
        self.max_output = bounded_setting("GRAINSTORM_AI_MAX_OUTPUT_TOKENS", 12000, 1000, 16000)
        self._client = client

    async def generate(self, context: dict) -> GenerationResult:
        contents = json.dumps(context, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if len(contents.encode()) > self.max_input:
            raise IntelligenceGenerationError("AI context exceeds configured input limit.", code="input_too_large", status_code=422)
        if self._client is None and not os.environ.get("GEMINI_API_KEY"):
            raise IntelligenceConfigurationError("GEMINI_API_KEY is not configured on the backend.")
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise IntelligenceConfigurationError("Install project dependencies including google-genai.") from exc

        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTIONS,
            response_mime_type="application/json",
            response_json_schema=AIDecisionDraft.model_json_schema(),
            max_output_tokens=self.max_output,
        )

        async def request():
            for attempt in range(self.retries + 1):
                owned = self._client is None
                client = self._client or genai.Client(
                    api_key=os.environ["GEMINI_API_KEY"], vertexai=False,
                    http_options=types.HttpOptions(timeout=int(self.timeout * 1000),
                        retry_options=types.HttpRetryOptions(attempts=1)),
                ).aio
                try:
                    response = await client.models.generate_content(model=self.model, contents=contents, config=config)
                    return response
                except Exception as exc:
                    code = getattr(exc, "code", None)
                    if code == 429:
                        raise IntelligenceGenerationError(
                            "Gemini quota or request limit reached. Check free-tier quotas in Google AI Studio; no fallback was used.",
                            code="gemini_quota_exhausted", retryable=False, status_code=429,
                        ) from exc
                    if attempt < self.retries and (code in {500, 502, 503, 504} or isinstance(exc, (OSError, TimeoutError))):
                        await asyncio.sleep(min(2 ** attempt, 2))
                        continue
                    raise classify_error(exc) from exc
                finally:
                    if owned:
                        await client.aclose()

        try:
            response = await asyncio.wait_for(request(), timeout=self.timeout)
        except TimeoutError as exc:
            raise IntelligenceGenerationError("Gemini request timed out.", code="gemini_timeout", retryable=True, status_code=504) from exc
        candidates = getattr(response, "candidates", None) or []
        if not candidates or str(getattr(candidates[0], "finish_reason", "")).split(".")[-1] != "STOP":
            raise IntelligenceGenerationError("Gemini returned blocked or incomplete output.", code="gemini_incomplete")
        try:
            draft = AIDecisionDraft.model_validate_json(response.text or "")
        except (ValidationError, ValueError, TypeError) as exc:
            raise IntelligenceGenerationError("Gemini returned invalid structured output.", code="gemini_invalid_output") from exc
        usage = getattr(response, "usage_metadata", None)
        tokens = {name: value for source, name in (
            ("prompt_token_count", "input_tokens"), ("candidates_token_count", "output_tokens"),
            ("total_token_count", "total_tokens"), ("thoughts_token_count", "reasoning_tokens"),
        ) if isinstance(value := getattr(usage, source, None), int)}
        return GenerationResult(draft, getattr(response, "model_version", None) or self.model,
                                getattr(response, "response_id", None), tokens)

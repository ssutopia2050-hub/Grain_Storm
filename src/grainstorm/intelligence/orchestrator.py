"""One-pass AI generation followed by independent deterministic validation."""
from __future__ import annotations

import hashlib
import json
import asyncio
import os
from typing import Any

from grainstorm.intelligence.context_builder import build_ai_context
from grainstorm.intelligence.gemini_engine import GeminiDecisionEngine, bounded_setting
from grainstorm.intelligence.cache import DecisionCache
from grainstorm.intelligence.common import IntelligenceConfigurationError
from grainstorm.intelligence.prompts import PROMPT_VERSION, SYSTEM_INSTRUCTIONS
from grainstorm.intelligence.schemas import SCHEMA_VERSION
from grainstorm.intelligence.schemas import GrainStormDecisionReport
from grainstorm.intelligence.validator import validate_ai_draft


def analysis_identifier(analysis: dict[str, Any]) -> str:
    canonical = json.dumps(analysis, sort_keys=True, separators=(",", ":"), default=str)
    return f"gsa_{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:24]}"


class IntelligenceOrchestrator:
    def __init__(self, engine: Any | None = None, cache: DecisionCache | None = None):
        self.engine = engine or GeminiDecisionEngine()
        self.cache = cache
        if engine is None and cache is None:
            self.cache = DecisionCache(os.environ.get("GRAINSTORM_AI_CACHE_DB", "data/cache/intelligence.sqlite3"))
        self.max_calls = bounded_setting("GRAINSTORM_AI_MAX_CALLS_PER_ANALYSIS", 1, 1, 3)
        self.semaphore = asyncio.Semaphore(bounded_setting("GRAINSTORM_AI_MAX_CONCURRENT", 1, 1, 8))

    async def analyze(self, analysis: dict[str, Any]) -> GrainStormDecisionReport:
        context = build_ai_context(analysis)
        key = hashlib.sha256(json.dumps({
            "context": context, "model": getattr(self.engine, "model", "injected"),
            "prompt_version": PROMPT_VERSION, "prompt": SYSTEM_INSTRUCTIONS, "schema_version": SCHEMA_VERSION,
        }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        async with self.semaphore:
            generated = await asyncio.to_thread(self.cache.reserve, key, self.max_calls) if self.cache else None
            if generated is None:
                try:
                    generated = await self.engine.generate(context)
                except BaseException as exc:
                    if self.cache:
                        await asyncio.shield(asyncio.to_thread(self.cache.finish, key, None,
                                                               isinstance(exc, IntelligenceConfigurationError)))
                    raise
                if self.cache:
                    await asyncio.to_thread(self.cache.finish, key, generated)
        return validate_ai_draft(
            draft=generated.draft,
            context=context,
            analysis_identifier=analysis_identifier(analysis),
            model=generated.model,
            response_id=generated.response_id,
            token_usage=generated.token_usage,
        )

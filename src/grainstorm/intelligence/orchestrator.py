"""One-pass AI generation followed by independent deterministic validation."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from grainstorm.intelligence.context_builder import build_ai_context
from grainstorm.intelligence.openai_engine import OpenAIDecisionEngine
from grainstorm.intelligence.schemas import GrainStormDecisionReport
from grainstorm.intelligence.validator import validate_ai_draft


def analysis_identifier(analysis: dict[str, Any]) -> str:
    canonical = json.dumps(analysis, sort_keys=True, separators=(",", ":"), default=str)
    return f"gsa_{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:24]}"


class IntelligenceOrchestrator:
    def __init__(self, engine: OpenAIDecisionEngine | Any | None = None):
        self.engine = engine or OpenAIDecisionEngine()

    async def analyze(self, analysis: dict[str, Any]) -> GrainStormDecisionReport:
        context = build_ai_context(analysis)
        generated = await self.engine.generate(context)
        return validate_ai_draft(
            draft=generated.draft,
            context=context,
            analysis_identifier=analysis_identifier(analysis),
            model=generated.model,
            response_id=generated.response_id,
            token_usage=generated.token_usage,
        )

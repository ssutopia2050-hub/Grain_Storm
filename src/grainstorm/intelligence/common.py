"""Provider-independent generation types and errors."""
from dataclasses import dataclass
from grainstorm.intelligence.schemas import AIDecisionDraft


class IntelligenceConfigurationError(RuntimeError):
    pass


class IntelligenceGenerationError(RuntimeError):
    def __init__(self, message: str, *, code: str = "generation_failed",
                 retryable: bool = False, status_code: int = 502):
        super().__init__(message)
        self.code, self.retryable, self.status_code = code, retryable, status_code


@dataclass(frozen=True)
class GenerationResult:
    draft: AIDecisionDraft
    model: str
    response_id: str | None
    token_usage: dict[str, int]

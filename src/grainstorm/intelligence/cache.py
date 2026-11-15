"""Persistent generation cache and atomic per-analysis call budget."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from grainstorm.intelligence.common import GenerationResult, IntelligenceGenerationError
from grainstorm.intelligence.schemas import AIDecisionDraft


class DecisionCache:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS decisions (key TEXT PRIMARY KEY, calls INTEGER NOT NULL, running INTEGER NOT NULL, result TEXT)")

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def reserve(self, key: str, max_calls: int) -> GenerationResult | None:
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT calls, running, result FROM decisions WHERE key=?", (key,)).fetchone()
            if row and row[2]:
                data = json.loads(row[2])
                return GenerationResult(AIDecisionDraft.model_validate(data["draft"]), data["model"], data["response_id"], data["token_usage"])
            if row and row[1]:
                raise IntelligenceGenerationError("Identical analysis is already generating, or was interrupted. Check the worker before retrying.", code="analysis_busy", retryable=True, status_code=409)
            if row and row[0] >= max_calls:
                raise IntelligenceGenerationError("AI call budget for this analysis is exhausted. Review the failure before increasing the configured budget.", code="analysis_call_limit", status_code=429)
            conn.execute("INSERT INTO decisions VALUES (?,1,1,NULL) ON CONFLICT(key) DO UPDATE SET calls=calls+1,running=1", (key,))
        return None

    def finish(self, key: str, result: GenerationResult | None, refund: bool = False):
        data = None if result is None else json.dumps({
            "draft": result.draft.model_dump(mode="json"), "model": result.model,
            "response_id": result.response_id, "token_usage": result.token_usage,
        })
        with self.connect() as conn:
            conn.execute("UPDATE decisions SET running=0,result=?,calls=calls-? WHERE key=?", (data, int(refund), key))

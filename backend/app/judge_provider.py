"""Provider-independent code-judge interface.

SECURITY: nothing in this module (or anywhere in the API process) executes
participant code. A real provider must call an *external*, isolated sandbox
(microVM / hardened container service) that offers CPU+memory+time limits, no
network, a restricted filesystem and cleanup. No such provider has been selected
or verified yet, so the default provider is `disabled`.

JUDGE_PROVIDER=disabled (default)  -> every request is a SYSTEM_ERROR "not enabled"
JUDGE_PROVIDER=mock                -> deterministic FAKE results for UI/tests, labelled MOCK
"""
import os
from typing import Protocol

from pydantic import BaseModel, Field, field_validator

OUTCOMES = ("ACCEPTED", "WRONG_ANSWER", "COMPILATION_ERROR", "RUNTIME_ERROR",
            "TIME_LIMIT_EXCEEDED", "MEMORY_LIMIT_EXCEEDED", "SYSTEM_ERROR")
MAX_CODE_CHARS = 200_000
MAX_MESSAGE_CHARS = 2_000          # output limit applied to anything shown to participants
LANGUAGES = {"c", "cpp", "java", "python", "sql"}


class TestCase(BaseModel):
    __test__ = False  # not a pytest class
    input: str
    expected_output: str


class JudgeRequest(BaseModel):
    language: str
    code: str = Field(max_length=MAX_CODE_CHARS)
    tests: list[TestCase]
    time_limit_ms: int = Field(default=2000, ge=100, le=10_000)
    memory_limit_kb: int = Field(default=262_144, ge=16_384, le=1_048_576)

    @field_validator("language")
    @classmethod
    def _lang(cls, v: str) -> str:
        if v not in LANGUAGES:
            raise ValueError("Unsupported language")
        return v


class JudgeResult(BaseModel):
    outcome: str
    passed: int = 0
    total: int = 0
    runtime_ms: int | None = None
    memory_kb: int | None = None
    message: str = ""
    provider: str
    is_mock: bool = False

    @field_validator("outcome")
    @classmethod
    def _outcome(cls, v: str) -> str:
        if v not in OUTCOMES:
            raise ValueError("Unknown outcome")
        return v

    @field_validator("message")
    @classmethod
    def _clip(cls, v: str) -> str:
        return v[:MAX_MESSAGE_CHARS]


class JudgeProvider(Protocol):
    name: str

    def run(self, req: JudgeRequest) -> JudgeResult: ...


class DisabledProvider:
    name = "disabled"

    def run(self, req: JudgeRequest) -> JudgeResult:
        return JudgeResult(outcome="SYSTEM_ERROR", total=len(req.tests), provider=self.name,
                           message="Code execution is not enabled for this event. Your code was saved but not run.")


class MockProvider:
    """Never executes anything. `MOCK:<OUTCOME>` anywhere in the code selects the outcome."""
    name = "mock"

    def run(self, req: JudgeRequest) -> JudgeResult:
        outcome = "ACCEPTED"
        for o in OUTCOMES:
            if f"MOCK:{o}" in req.code:
                outcome = o
        total = len(req.tests)
        passed = total if outcome == "ACCEPTED" else max(total - 1, 0)
        return JudgeResult(outcome=outcome, passed=passed, total=total, runtime_ms=1, memory_kb=1, provider=self.name,
                           is_mock=True, message="MOCK RESULT — your code was NOT executed. This is not a correctness verdict.")


_PROVIDERS = {"disabled": DisabledProvider, "mock": MockProvider}


def get_provider() -> JudgeProvider:
    name = os.getenv("JUDGE_PROVIDER", "disabled").lower()
    return _PROVIDERS.get(name, DisabledProvider)()


def run_safely(provider: JudgeProvider, req: JudgeRequest) -> JudgeResult:
    """Provider failures never escape as exceptions or as WRONG_ANSWER: they are SYSTEM_ERROR."""
    try:
        res = provider.run(req)
        return JudgeResult.model_validate(res.model_dump())
    except Exception:
        return JudgeResult(outcome="SYSTEM_ERROR", total=len(req.tests), provider=getattr(provider, "name", "unknown"),
                           message="The judge is temporarily unavailable. Your submission was saved.")

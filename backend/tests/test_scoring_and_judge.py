"""Pure unit tests: ranking/tie handling and the judge-provider safety properties."""
from datetime import datetime, timedelta, timezone

import pytest

from app import scoring
from app.judge_provider import (DisabledProvider, JudgeRequest, JudgeResult, MockProvider, TestCase, run_safely)

T0 = datetime(2026, 10, 24, 10, 0, tzinfo=timezone.utc)


def team(n, total, minutes=None):
    return {"team_number": n, "total": total, "last_final_at": None if minutes is None else T0 + timedelta(minutes=minutes)}


def test_competition_ranking_gives_ties_the_same_rank():
    r = scoring.rank([team(1, 10), team(2, 20), team(3, 20), team(4, 5)], "none")
    assert [(t["team_number"], t["rank"]) for t in r] == [(2, 1), (3, 1), (1, 3), (4, 4)]


def test_optional_tiebreak_earlier_final_submission_wins():
    r = scoring.rank([team(1, 20, 30), team(2, 20, 10), team(3, 15, 5)], "earliest_final_submission")
    assert [(t["team_number"], t["rank"]) for t in r] == [(2, 1), (1, 2), (3, 3)]
    same = scoring.rank([team(1, 20, 10), team(2, 20, 10)], "earliest_final_submission")
    assert [t["rank"] for t in same] == [1, 1]


def req(code="x", n=2, lang="python"):
    return JudgeRequest(language=lang, code=code, tests=[TestCase(input="1", expected_output="1")] * n)


def test_disabled_provider_never_claims_a_verdict():
    r = DisabledProvider().run(req())
    assert r.outcome == "SYSTEM_ERROR" and not r.is_mock and "not enabled" in r.message


def test_mock_provider_is_always_labelled_and_never_executes():
    r = MockProvider().run(req("import os; os.system('touch /tmp/pwned')"))
    assert r.is_mock and "NOT executed" in r.message
    import os
    assert not os.path.exists("/tmp/pwned")
    assert MockProvider().run(req("# MOCK:TIME_LIMIT_EXCEEDED")).outcome == "TIME_LIMIT_EXCEEDED"


def test_provider_exception_becomes_system_error_not_wrong_answer():
    class Boom:
        name = "boom"

        def run(self, r):
            raise RuntimeError("sandbox down")
    out = run_safely(Boom(), req())
    assert out.outcome == "SYSTEM_ERROR" and out.outcome != "WRONG_ANSWER"


def test_oversized_output_is_clipped_and_bad_outcomes_rejected():
    class Chatty:
        name = "chatty"

        def run(self, r):
            return JudgeResult(outcome="RUNTIME_ERROR", message="A" * 50_000, provider="chatty")
    assert len(run_safely(Chatty(), req()).message) == 2000

    class Lies:
        name = "lies"

        def run(self, r):
            return JudgeResult.model_construct(outcome="PERFECT", message="", provider="lies", passed=0, total=0, runtime_ms=None, memory_kb=None, is_mock=False)
    assert run_safely(Lies(), req()).outcome == "SYSTEM_ERROR"


def test_request_validation():
    with pytest.raises(Exception):
        JudgeRequest(language="ruby", code="x", tests=[])
    with pytest.raises(Exception):
        JudgeRequest(language="python", code="x" * 200_001, tests=[])
    with pytest.raises(Exception):
        JudgeRequest(language="python", code="x", tests=[], time_limit_ms=999_999)

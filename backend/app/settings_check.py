"""Fail-fast production configuration. A misconfigured production API must refuse to start, not run permissively."""
import os

from .config import Settings

REAL_JUDGES = {"judge0"}
EVAL_MODES = {"background", "inline", "manual", "worker"}


def is_production() -> bool:
    return os.getenv("APP_ENV", "development").lower() == "production"


def validate(s: Settings) -> list[str]:
    """Returns problems; empty means safe to start. Only enforced in production."""
    problems = []
    for name, val in (("NEXT_PUBLIC_SUPABASE_URL", s.supabase_url), ("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", s.supabase_publishable_key),
                      ("SUPABASE_SECRET_KEY", s.supabase_secret_key), ("DATABASE_URL", s.database_url)):
        if not val:
            problems.append(f"{name} is not set")
    if s.database_url and "pooler.supabase.com" not in s.database_url:
        problems.append("DATABASE_URL should be the Supabase Session pooler URL (the direct host is IPv6-only)")
    if not s.supabase_secret_key.startswith("sb_secret_") and s.supabase_secret_key:
        problems.append("SUPABASE_SECRET_KEY does not look like a Supabase secret key")
    judge = os.getenv("JUDGE_PROVIDER", "disabled").lower()
    if judge == "mock":
        problems.append("JUDGE_PROVIDER=mock is forbidden in production (fake verdicts). Use 'disabled' or a verified real provider")
    elif judge not in {"disabled"} | REAL_JUDGES:
        problems.append(f"JUDGE_PROVIDER={judge!r} is not a known provider")
    if os.getenv("EVALUATION_MODE", "background") not in EVAL_MODES:
        problems.append(f"EVALUATION_MODE must be one of {sorted(EVAL_MODES)}")
    if not s.gemini_api_key and os.getenv("EVALUATION_MODE", "background") != "manual":
        problems.append("GEMINI_API_KEY is not set (reports would never be evaluated); set EVALUATION_MODE=manual to run without AI")
    return problems

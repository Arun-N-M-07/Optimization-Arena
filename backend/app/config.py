"""Environment-driven settings. Secrets are read here and nowhere else."""
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


@dataclass(frozen=True)
class Settings:
    supabase_url: str
    supabase_publishable_key: str
    supabase_secret_key: str
    gemini_api_key: str
    gemini_model: str
    database_url: str  # direct Postgres URL for SQLAlchemy; contains the DB password


@lru_cache
def get_settings() -> Settings:
    return Settings(
        supabase_url=os.getenv("NEXT_PUBLIC_SUPABASE_URL", "").rstrip("/"),
        supabase_publishable_key=os.getenv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", ""),
        supabase_secret_key=os.getenv("SUPABASE_SECRET_KEY", ""),
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        gemini_model=os.getenv("GEMINI_MODEL") or "gemini-3.5-flash-lite",
        database_url=os.getenv("DATABASE_URL", ""),
    )

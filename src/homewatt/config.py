"""Runtime settings. Environment variables prefixed HOMEWATT_, or a .env file."""

from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HOMEWATT_", env_file=str(REPO_ROOT / ".env"), extra="ignore", populate_by_name=True)

    spacetime_host: str = "https://maincloud.spacetimedb.com"
    spacetime_database: str = "house-energy-7q7yy"
    household_id: str = "hh-demo"
    local_tz: str = "America/Detroit"
    spacetime_module_dir: Path = REPO_ROOT / "spacetimedb"
    # CMP-20 narrator. Read from GEMINI_API_KEY in .env (gitignored); never logged.
    gemini_api_key: str = Field(default="", validation_alias=AliasChoices("GEMINI_API_KEY", "HOMEWATT_GEMINI_API_KEY"))
    gemini_model: str = "gemini-2.5-flash"
    session_secret: str = ""  # v0.12 sign-in cookies; empty = generated into data/.session_secret
    location_id: str = "ann_arbor"
    tariff_dir: Path = REPO_ROOT / "config" / "tariffs"
    profile_path: Path = REPO_ROOT / "config" / "profiles" / "demo_household.yaml"
    dataset_root: Path = REPO_ROOT / "data" / "raw" / "nilm-dataset"
    library_dir: Path = REPO_ROOT / "data" / "library"
    synthetic_dir: Path = REPO_ROOT / "data" / "synthetic"


def get_settings() -> Settings:
    return Settings()

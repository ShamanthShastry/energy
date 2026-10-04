"""Runtime settings. Environment variables prefixed HOMEWATT_, or a .env file."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HOMEWATT_", env_file=".env", extra="ignore")

    spacetime_host: str = "https://maincloud.spacetimedb.com"
    spacetime_database: str = "house-energy-7q7yy"
    household_id: str = "hh-demo"
    local_tz: str = "America/Detroit"
    spacetime_module_dir: Path = REPO_ROOT / "spacetimedb"
    dataset_root: Path = REPO_ROOT / "data" / "raw" / "nilm-dataset"
    library_dir: Path = REPO_ROOT / "data" / "library"
    synthetic_dir: Path = REPO_ROOT / "data" / "synthetic"


def get_settings() -> Settings:
    return Settings()

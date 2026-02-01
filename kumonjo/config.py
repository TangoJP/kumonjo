"""Configuration: API key from .env, data paths."""

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*_args, **_kwargs):
        pass


def _project_root() -> Path:
    """Project root (directory containing kumonjo package)."""
    return Path(__file__).resolve().parent.parent


def load_env():
    """Load .env from project root. Safe to call multiple times."""
    load_dotenv(_project_root() / ".env")


def get_api_key() -> str:
    """e-Stat API application ID. Set ESTAT_APP_ID in .env."""
    load_env()
    key = os.environ.get("ESTAT_APP_ID", "").strip()
    if not key:
        raise ValueError(
            "ESTAT_APP_ID is not set. Add it to .env (see .env.example)."
        )
    return key


def get_data_dirs(
    *,
    raw: str | None = None,
    processed: str | None = None,
    official: str | None = None,
) -> dict[str, Path]:
    """Return data directory paths. Defaults are under project root."""
    root = _project_root()
    return {
        "raw": Path(raw) if raw else root / "data" / "raw",
        "processed": Path(processed) if processed else root / "data" / "processed",
        "official": Path(official) if official else root / "data" / "official",
    }

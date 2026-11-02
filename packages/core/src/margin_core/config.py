"""Settings, from four places (highest priority first):

1. environment variables (for deployments and CI);
2. settings saved by the user, e.g. from the web UI, in ``settings.json`` in the user's
   config folder (``MARGIN_CONFIG_FILE`` overrides the path; empty turns it off);
3. the file named by ``MARGIN_ENV_FILE``, if any;
4. the defaults below.

No file is read unless ``MARGIN_ENV_FILE`` names one. A ``.env`` in the current folder is not
trusted: that folder may be a repository being analysed, and its settings could send the code
to another server.

Empty values are ignored, so ``ANTHROPIC_API_KEY=`` in a ``.env`` does not count as a key.
Secrets never have defaults, and saved secrets are never sent back to a browser.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Literal

from dotenv import dotenv_values
from pydantic import SecretStr
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

ENV_FILE_VAR = "MARGIN_ENV_FILE"
CONFIG_FILE_VAR = "MARGIN_CONFIG_FILE"

# What the user may save (the rest is configured by environment or env file only).
SAVEABLE = frozenset({
    "default_llm_provider",
    "local_llm_base_url", "local_llm_api_key", "local_llm_model",
    "anthropic_api_key", "anthropic_model",
    "openai_api_key", "openai_model",
    "max_cost_usd",
})  # fmt: skip

Source = Literal["environment", "saved", "env_file", "default"]


def user_config_path() -> Path | None:
    """Where saved settings live, or None when saving is turned off."""
    override = os.environ.get(CONFIG_FILE_VAR)
    if override is not None:
        return Path(override) if override else None
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "margin" / "settings.json"


def load_user_config() -> dict[str, Any]:
    """Saved settings; an unreadable or malformed file counts as empty."""
    path = user_config_path()
    if path is None or not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if k in SAVEABLE and v not in (None, "")}


def save_user_config(updates: dict[str, Any]) -> Path:
    """Merge ``updates`` into the saved settings. ``None`` or ``""`` removes a value.

    The file is written atomically and, on POSIX systems, readable by the user only.
    """
    path = user_config_path()
    if path is None:
        raise RuntimeError(f"Saving settings is turned off ({CONFIG_FILE_VAR} is empty)")
    unknown = set(updates) - SAVEABLE
    if unknown:
        raise ValueError(f"These settings cannot be saved: {sorted(unknown)}")
    data = load_user_config()
    for key, value in updates.items():
        if value in (None, ""):
            data.pop(key, None)
        else:
            data[key] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".settings-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
        if sys.platform != "win32":
            os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path


class _SavedSettings(PydanticBaseSettingsSource):
    """The user's saved settings, as a pydantic-settings source."""

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        return None, field_name, False  # unused: __call__ returns everything at once

    def __call__(self) -> dict[str, Any]:
        return load_user_config()


class Settings(BaseSettings):
    """Global settings for margin."""

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8", extra="ignore", env_ignore_empty=True
    )

    anthropic_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    github_token: SecretStr | None = None

    local_llm_base_url: str = "http://localhost:11434"
    local_llm_api_key: SecretStr | None = None
    local_llm_reasoning_effort: str = "none"  # empty: don't send the field

    default_llm_provider: str = "local"
    default_llm_model: str | None = None  # applies to the default provider only
    # the model to use with each provider (empty: the provider's default)
    local_llm_model: str | None = None
    anthropic_model: str | None = None
    openai_model: str | None = None

    max_cost_usd: float = 1.0
    log_level: str = "INFO"

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            _SavedSettings(settings_cls),
            dotenv_settings,
            file_secret_settings,
        )


def _env_file() -> str | None:
    return os.environ.get(ENV_FILE_VAR) or None


def get_settings() -> Settings:
    """Load settings fresh from all four places."""
    return Settings(_env_file=_env_file())  # type: ignore[call-arg]


def setting_sources(fields: frozenset[str] = SAVEABLE) -> dict[str, Source]:
    """Where each setting's current value comes from, so a UI can explain it."""
    saved = load_user_config()
    env_file = _env_file()
    from_file: dict[str, str | None] = {}
    if env_file and Path(env_file).is_file():
        from_file = {k.lower(): v for k, v in dotenv_values(env_file).items()}
    sources: dict[str, Source] = {}
    for name in fields:
        if os.environ.get(name.upper()):
            sources[name] = "environment"
        elif name in saved:
            sources[name] = "saved"
        elif from_file.get(name):
            sources[name] = "env_file"
        else:
            sources[name] = "default"
    return sources

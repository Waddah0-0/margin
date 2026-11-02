from __future__ import annotations

from pathlib import Path

import pytest
from margin_core.config import get_settings, setting_sources


def test_a_env_file_in_the_current_folder_is_not_trusted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # the folder may be a repository being analysed, and this would send its code elsewhere
    (tmp_path / ".env").write_text(
        "LOCAL_LLM_BASE_URL=https://attacker.example\nMAX_COST_USD=9999\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MARGIN_ENV_FILE", raising=False)
    settings = get_settings()
    assert settings.local_llm_base_url == "http://localhost:11434"
    assert settings.max_cost_usd == 1.0
    assert setting_sources()["local_llm_base_url"] == "default"


def test_env_file_can_be_chosen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = tmp_path / "custom.env"
    env.write_text("DEFAULT_LLM_MODEL=from-file\n", encoding="utf-8")
    monkeypatch.setenv("MARGIN_ENV_FILE", str(env))
    assert get_settings().default_llm_model == "from-file"


def test_environment_variables_win(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEFAULT_LLM_PROVIDER", "mock")
    assert get_settings().default_llm_provider == "mock"

"""Tests for the Secret Leaks agent: rules, filtering, redaction, and git history."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from margin_core import CancellationToken, InputValidationError, ProgressEvent, RunContext
from margin_core.reporting import to_json, to_markdown
from secret_leaks import SecretLeaksAgent, SecretMatchSummary, __version__
from secret_leaks.rules import redact, scan_line, shannon_entropy, strip_control_chars
from secret_leaks.scanner import _MAX_FINDINGS, _build_finding

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _tok(prefix: str, suffix: str) -> str:
    """Build synthetic test tokens dynamically without storing literal token shapes in source."""
    return prefix + suffix


def _run_git(repo: Path, *args: str, date: str = "2026-11-01T12:00:00+00:00") -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_DATE": date,
        "GIT_COMMITTER_DATE": date,
        "GIT_AUTHOR_NAME": "Test User",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test User",
        "GIT_COMMITTER_EMAIL": "test@example.com",
        "GIT_TERMINAL_PROMPT": "0",
    }
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        env=env,
        check=True,
    ).stdout


def _synthetic_aws_key(index: int) -> str:
    """Generate deterministic, unique high-entropy synthetic AWS keys for cap tests."""
    alphabet = "BCDFGHJKLMNPQRSTVWYZ23456789"
    base = len(alphabet)
    n = index + 100
    chars: list[str] = []
    for _ in range(4):
        chars.append(alphabet[n % base])
        n //= base
    return _tok("AKIA", "Q7M9K2P4L8N3" + "".join(chars))


def test_agent_metadata_and_lightweight_import() -> None:
    info = SecretLeaksAgent.info()
    assert info.id == "secret-leaks"
    assert info.version == __version__ == "0.1.0"
    assert info.primary_input == "target"
    assert info.uses_llm is False

    agent_src = str(Path(__file__).resolve().parents[1] / "src")
    core_src = str(Path(__file__).resolve().parents[3] / "packages" / "core" / "src")
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            [p for p in (agent_src, core_src, os.environ.get("PYTHONPATH", "")) if p]
        ),
    }
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, secret_leaks; "
            "assert 'secret_leaks.scanner' not in sys.modules; "
            "assert secret_leaks.__version__ == '0.1.0'",
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest.mark.parametrize(
    ("line_factory", "expected_rule"),
    [
        (lambda: f"AWS_ACCESS_KEY_ID = '{_tok('AKIA', 'Q7M9K2P4L8N3R5X6')}'", "aws_access_key"),
        (
            lambda: (
                f"aws_secret_access_key = '{_tok('wJalrXUtnFEMI/K7MDENG/', 'bPxRfiCYReal99Key1')}'"
            ),
            "aws_secret_key",
        ),
        (
            lambda: f"GITHUB_TOKEN = '{_tok('ghp_', '9mK2pL7vR4wQ8nZ3xJ6bC1fH5gT0yU2aB4cDe')}'",
            "github_token",
        ),
        (
            lambda: f"GH_OAUTH = '{_tok('gho_', '7kR3mP9vX2wQ5nL8zB4cT1yH6jF0gD3sA9eWq')}'",
            "github_token",
        ),
        (
            lambda: f"GH_USER = '{_tok('ghu_', '5jN8mK2pL7vR4wQ9zB3cT1yH6fD0gS3aE9rWq')}'",
            "github_token",
        ),
        (
            lambda: f"GH_SRV = '{_tok('ghs_', '3hB6nM9pK2vR7wQ4zL8cT1yJ5fD0gS3aE9rWq')}'",
            "github_token",
        ),
        (
            lambda: (
                f"GH_PAT = '{_tok('github_pat_', '11ABCDEFG_9mK2pL7vR4wQ8nZ3xJ6bC1fH5gT0yU2')}'"
            ),
            "github_token",
        ),
        (
            lambda: f"GITLAB_TOKEN = '{_tok('glpat-', 'k9LmP2xQ8vR4nZ7wJ3aB5cD')}'",
            "gitlab_token",
        ),
        (
            lambda: (
                "SLACK_TOKEN = "
                f"'{_tok('xoxb-', '918273645012-918273645013-aB3cD4eF5gH6iJ7kL8mN9oP0')}'"
            ),
            "slack_token",
        ),
        (
            lambda: f"STRIPE_KEY = '{_tok('sk_live_', '51NxYzAbCdEfGhIjKlMnOpQrStUvWx')}'",
            "stripe_key",
        ),
        (
            lambda: f"STRIPE_RESTRICTED = '{_tok('rk_live_', '82MzXyBcDeFgHiJkLmNoPqRsTuVwXy')}'",
            "stripe_key",
        ),
        (
            lambda: f"GOOGLE_API_KEY = '{_tok('AIza', 'SyD9mK2pL7vR4wQ8nZ3xJ6bC1fH5gT0yU2aB')}'",
            "google_api_key",
        ),
        (
            lambda: f"OPENAI_KEY = '{_tok('sk-', '9mK2pL7vR4wQ8nZ3xJ6bC1fH5gT0yU2aB4cDe')}'",
            "openai_api_key",
        ),
        (
            lambda: f"OPENAI_PROJ = '{_tok('sk-proj-', 'aB3cD4eF5gH6iJ7kL8mN9oP0qR1sT2uV3')}'",
            "openai_api_key",
        ),
        (
            lambda: (
                f"ANTHROPIC_KEY = '{_tok('sk-ant-', 'api03-mK2pL7vR4wQ8nZ3xJ6bC1fH5gT0yU2aB4cD')}'"
            ),
            "anthropic_api_key",
        ),
        (
            lambda: _tok("-----BEGIN RSA ", "PRIVATE KEY-----"),
            "pem_private_key",
        ),
        (
            lambda: (
                "DATABASE_URL = "
                f"'{_tok('postgresql://prodadmin:', 'V3ryStr0ngDbP4ss!@db.internal:5432/app')}'"
            ),
            "database_url",
        ),
        (
            lambda: (
                "LEGACY_DB = "
                f"'{_tok('postgres://ops:', 'K9mP2vR7wQ4nL8z!@legacy.db.local/service')}'"
            ),
            "database_url",
        ),
        (
            lambda: 'api_key = "k9LmP2xQ8vR4nZ7wJ3aB5cD"',
            "generic_secret",
        ),
        (
            lambda: '{"client_secret": "X8vR4nZ7wJ3aB5cD9mK2p"}',
            "generic_secret",
        ),
    ],
)
def test_rule_detection(line_factory: object, expected_rule: str) -> None:
    assert callable(line_factory)
    line = str(line_factory())
    matches = scan_line(line)
    assert len(matches) == 1
    assert matches[0].rule_id == expected_rule


def test_non_secret_code_and_public_pem_do_not_trigger() -> None:
    benign_lines = [
        'api_key = os.environ["API_KEY"]',
        "password = user.password",
        'token_type = "bearer"',
        'secret_name = "access_token"',
        'private_key_path = "/etc/ssl/private/server.key"',
        'oauth_url = "https://auth.example.com/oauth/token"',
        "-----BEGIN PUBLIC KEY-----",
        "-----BEGIN CERTIFICATE-----",
        'api_key = "aaaaaaaaaaaaaaaaaaaa"',  # zero entropy
    ]
    for line in benign_lines:
        assert scan_line(line) == [], f"Unexpected match for: {line}"


@pytest.mark.parametrize(
    "line",
    [
        f"AWS_KEY = '{_tok('AKIA', 'IOSFODNN7EXAMPLE')}'",
        f"AWS_SECRET = '{_tok('wJalrXUtnFEMI/K7MDENG/', 'bPxRfiCYEXAMPLEKEY')}'",
        'password = "changeme"',
        'api_key = "your_api_key_here"',
        'api_key = "test_secret_value_12345"',
        f"GITLAB_TOKEN = '{_tok('glpat-', 'test_token_1234567890abcdef')}'",
        'secret = "dummy_secret_value_99"',
        'token = "placeholder_token_value"',
        f"STRIPE_KEY = '{_tok('sk_live_', 'xxxxxxxxxxxxxxxxxxxxxxxx')}'",
        f"STRIPE_KEY = '{_tok('sk_live_', '000000000000000000000000')}'",
        'api_key = "<YOUR_API_KEY>"',
        'token = "${API_TOKEN}"',
        'DATABASE_URL = "postgresql://postgres:changeme@localhost:5432/app"',
    ],
)
def test_placeholder_suppression(line: str) -> None:
    assert scan_line(line) == [], f"Expected placeholder to be suppressed: {line}"


def test_random_provider_keys_containing_test_are_detected() -> None:
    lines_and_rules = [
        (f"AWS_KEY = '{_tok('AKIA', 'Q7M9TESTL8N3R5X6')}'", "aws_access_key"),
        (
            f"GH = '{_tok('ghp_', '9mK2pL7vR4test8nZ3xJ6bC1fH5gT0yU2aB4c')}'",
            "github_token",
        ),
        (
            f"OPENAI = '{_tok('sk-proj-', '9mK2pL7vR4TeSt8nZ3xJ6bC1fH5gT0yU2')}'",
            "openai_api_key",
        ),
    ]
    for line, expected_rule in lines_and_rules:
        matches = scan_line(line)
        assert len(matches) == 1, f"Expected match for {line}"
        assert matches[0].rule_id == expected_rule


def test_inline_ignore_comments() -> None:
    aws_key = _tok("AKIA", "Q7M9K2P4L8N3R5X6")
    gh_tok = _tok("ghp_", "9mK2pL7vR4wQ8nZ3xJ6bC1fH5gT0yU2aB4cDe")
    assert scan_line(f'AWS_KEY = "{aws_key}"  # margin:ignore') == []
    assert scan_line(f'GITHUB_TOKEN = "{gh_tok}"  # pragma: allowlist secret') == []
    assert scan_line(f'const key = "{aws_key}"; // margin:ignore') == []


async def test_custom_allowlist_patterns(tmp_path: Path) -> None:
    allowed = _tok("AKIA", "Q7M9K2P4L8N3R5X6")
    blocked = _tok("ghp_", "9mK2pL7vR4wQ8nZ3xJ6bC1fH5gT0yU2aB4cDe")
    (tmp_path / "settings.py").write_text(
        f'SANDBOX_AWS = "{allowed}"\nPROD_GH = "{blocked}"\n',
        encoding="utf-8",
    )

    result = await SecretLeaksAgent().execute(
        {
            "target": str(tmp_path),
            "allowlist_patterns": [r"SANDBOX_AWS"],
        }
    )
    assert result.status == "ok", result.error
    assert result.data["total_matches"] == 1
    assert result.data["rules_triggered"] == ["github_token"]
    assert allowed not in result.model_dump_json()
    assert blocked not in result.model_dump_json()


async def test_invalid_allowlist_regex_rejected(tmp_path: Path) -> None:
    with pytest.raises(InputValidationError, match="Invalid allowlist regex"):
        await SecretLeaksAgent().execute(
            {"target": str(tmp_path), "allowlist_patterns": ["[unclosed"]}
        )


def test_redact_masks_all_lengths() -> None:
    assert redact("abc") == "***"
    assert redact("short12345") == "***"
    assert redact("fifteen-chars-1") == "***"
    assert redact("sixteen-chars-12") == "si...12"
    aws_key = _tok("AKIA", "1234567890ABXY12")
    assert redact(aws_key, prefix="AKIA") == "AKIA...12"
    assert redact(_tok("ghp_", "short"), prefix="ghp_") == "ghp_***"
    assert aws_key not in redact(aws_key)
    assert shannon_entropy("aaaa") == 0.0
    assert shannon_entropy("abcd") == 2.0


async def test_multiple_pem_keys_in_one_file_and_readable_preview(tmp_path: Path) -> None:
    rsa_hdr = _tok("-----BEGIN RSA ", "PRIVATE KEY-----")
    ec_hdr = _tok("-----BEGIN EC ", "PRIVATE KEY-----")
    (tmp_path / "keys.pem").write_text(
        "\n".join(
            [
                rsa_hdr,
                "not-a-real-key-line-1",
                "-----END RSA PRIVATE KEY-----",
                "",
                rsa_hdr,
                "not-a-real-key-line-2",
                "-----END RSA PRIVATE KEY-----",
                "",
                ec_hdr,
                "not-a-real-key-line-3",
                "-----END EC PRIVATE KEY-----",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = await SecretLeaksAgent().execute({"target": str(tmp_path)})
    assert result.status == "ok", result.error
    assert result.data["total_matches"] == 3
    matches = result.data["matches"]
    assert [(m["line"], m["redacted_preview"]) for m in matches] == [
        (1, "BEGIN RSA PRIVATE KEY"),
        (5, "BEGIN RSA PRIVATE KEY"),
        (9, "BEGIN EC PRIVATE KEY"),
    ]
    serialized = json.dumps(result.model_dump(mode="json"))
    assert "----...----" not in serialized
    assert rsa_hdr not in serialized
    assert ec_hdr not in serialized


def test_control_characters_stripped_from_outputs() -> None:
    assert strip_control_chars("src/a\x1b[31m\x07\x00\x7f\x9bb.py") == "src/a[31mb.py"
    assert not _CONTROL_RE.search(redact("ab\x1bcd\x07efghijklmnop\x7fqr"))

    generic_line = 'api_key = "k9Lm\x07P2xQ8vR4nZ7wJ3aB\x1b5cD"'
    matches = scan_line(generic_line)
    assert len(matches) == 1
    assert not _CONTROL_RE.search(matches[0].redacted_preview)

    dirty_match = SecretMatchSummary(
        rule_id="generic_secret",
        rule_name="Generic Secret Assignment",
        severity="high",
        source="workspace",
        file_path="src/evil\x1b[31m\x07\nfile.py",
        line=4,
        commit_sha="deadbeef\x071234",
        in_head=True,
        redacted_preview="k9Lm...\x1b[31m5cD",
        entropy=3.9,
    )
    finding = _build_finding(dirty_match)
    assert not _CONTROL_RE.search(finding.title)
    assert not _CONTROL_RE.search(finding.summary)
    for ev in finding.evidence:
        assert not _CONTROL_RE.search(ev.location or "")
        assert not _CONTROL_RE.search(ev.detail)


async def test_matches_and_findings_capped_at_max_findings(tmp_path: Path) -> None:
    total = _MAX_FINDINGS + 5
    lines = [f'KEY_{i} = "{_synthetic_aws_key(i)}"' for i in range(total)]
    (tmp_path / "many.py").write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = await SecretLeaksAgent().execute({"target": str(tmp_path)})
    assert result.status == "ok", result.error
    assert result.data["total_matches"] == total
    assert result.data["counts_by_severity"] == {"high": total, "medium": 0, "low": 0}
    assert result.data["workspace_matches"] == total
    assert len(result.data["matches"]) == _MAX_FINDINGS
    assert len(result.findings) == _MAX_FINDINGS
    assert any(f"{_MAX_FINDINGS} of {total}" in w for w in result.warnings)


async def test_raw_secrets_never_appear_anywhere_in_agent_result(tmp_path: Path) -> None:
    aws_key = _tok("AKIA", "Q7M9K2P4L8N3R5X6")
    aws_secret = _tok("wJalrXUtnFEMI/K7MDENG/", "bPxRfiCYReal99Key1")
    gh_tok = _tok("ghp_", "9mK2pL7vR4wQ8nZ3xJ6bC1fH5gT0yU2aB4cDe")
    anthropic_tok = _tok("sk-ant-", "api03-mK2pL7vR4wQ8nZ3xJ6bC1fH5gT0yU2aB4cD")
    db_pass = "V3ryStr0ngDbP4ss!"
    db_url = f"postgresql://prodadmin:{db_pass}@db.internal:5432/app"
    pem_hdr = _tok("-----BEGIN RSA ", "PRIVATE KEY-----")
    generic_val = "k9LmP2xQ8vR4nZ7wJ3aB5cD"

    (tmp_path / "secrets.py").write_text(
        "\n".join(
            [
                f'AWS_ACCESS_KEY_ID = "{aws_key}"',
                f'aws_secret_access_key = "{aws_secret}"',
                f'GITHUB_TOKEN = "{gh_tok}"',
                f'ANTHROPIC_API_KEY = "{anthropic_tok}"',
                f'DATABASE_URL = "{db_url}"',
                f'PEM = "{pem_hdr}"',
                f'api_key = "{generic_val}"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = await SecretLeaksAgent().execute({"target": str(tmp_path)})
    assert result.status == "ok", result.error
    assert result.data["total_matches"] == 7
    assert result.data["matches"][0]["in_head"] is None

    serialized = json.dumps(result.model_dump(mode="json"))
    markdown = to_markdown(result)
    json_report = to_json(result)

    raw_secrets = [
        aws_key,
        aws_secret,
        gh_tok,
        anthropic_tok,
        db_pass,
        db_url,
        pem_hdr,
        generic_val,
    ]
    for raw in raw_secrets:
        assert raw not in result.summary
        assert raw not in serialized
        assert raw not in markdown
        assert raw not in json_report
        for finding in result.findings:
            assert raw not in finding.title
            assert raw not in finding.summary
            for ev in finding.evidence:
                assert raw not in (ev.location or "")
                assert raw not in ev.detail


async def test_git_history_catches_deleted_secret_and_respects_flag(tmp_path: Path) -> None:
    if shutil.which("git") is None:
        pytest.skip("git not installed")

    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init", "-q", "-b", "main")

    current_secret = _tok("AKIA", "Q7M9K2P4L8N3R5X6")
    deleted_secret = _tok("ghp_", "9mK2pL7vR4wQ8nZ3xJ6bC1fH5gT0yU2aB4cDe")

    (repo / "config.py").write_text(f'AWS_KEY = "{current_secret}"\n', encoding="utf-8")
    (repo / "legacy.py").write_text(f'OLD_GH = "{deleted_secret}"\n', encoding="utf-8")
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-q", "-m", "initial commit with secrets")
    first_sha = _run_git(repo, "rev-parse", "HEAD").strip()

    # Delete the historical secret in a subsequent commit
    (repo / "legacy.py").write_text('OLD_GH = ""\n', encoding="utf-8")
    _run_git(repo, "add", "legacy.py")
    _run_git(repo, "commit", "-q", "-m", "remove legacy token", date="2026-11-02T12:00:00+00:00")

    # 1. scan_git_history=True catches BOTH current workspace secret and deleted historical secret
    events: list[ProgressEvent] = []
    full_result = await SecretLeaksAgent().execute(
        {"target": str(repo), "scan_git_history": True},
        ctx=RunContext(progress=events.append),
    )
    assert full_result.status == "ok", full_result.error
    data = full_result.data
    assert data["commits_scanned"] == 2
    assert data["workspace_matches"] == 1
    assert data["git_history_matches"] == 1
    assert data["total_matches"] == 2
    assert set(data["rules_triggered"]) == {"aws_access_key", "github_token"}
    assert "git_history" in [e.stage for e in events]

    ws_match = next(m for m in data["matches"] if m["source"] == "workspace")
    assert ws_match["file_path"] == "config.py"
    assert ws_match["in_head"] is True
    assert ws_match["commit_sha"] == first_sha

    hist_match = next(m for m in data["matches"] if m["source"] == "git_history")
    assert hist_match["file_path"] == "legacy.py"
    assert hist_match["commit_sha"] == first_sha
    assert hist_match["in_head"] is False
    assert deleted_secret not in json.dumps(data)
    assert current_secret not in json.dumps(data)

    # 2. scan_git_history=False only scans working files
    ws_only = await SecretLeaksAgent().execute(
        {"target": str(repo), "scan_git_history": False},
    )
    assert ws_only.status == "ok", ws_only.error
    assert ws_only.data["commits_scanned"] == 0
    assert ws_only.data["workspace_matches"] == 1
    assert ws_only.data["git_history_matches"] == 0
    assert ws_only.data["total_matches"] == 1
    assert ws_only.data["rules_triggered"] == ["aws_access_key"]

    # 3. history_depth=1 only inspects the removal commit, missing the earlier addition
    shallow = await SecretLeaksAgent().execute(
        {"target": str(repo), "scan_git_history": True, "history_depth": 1},
    )
    assert shallow.status == "ok", shallow.error
    assert shallow.data["commits_scanned"] == 1
    assert shallow.data["git_history_matches"] == 0
    assert shallow.data["workspace_matches"] == 1


async def test_partial_clone_skips_git_history_cleanly(tmp_path: Path) -> None:
    if shutil.which("git") is None:
        pytest.skip("git not installed")

    repo = tmp_path / "partial_repo"
    repo.mkdir()
    _run_git(repo, "init", "-q", "-b", "main")
    secret = _tok("AKIA", "Q7M9K2P4L8N3R5X6")
    (repo / "app.py").write_text(f'AWS_KEY = "{secret}"\n', encoding="utf-8")
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-q", "-m", "initial")

    # Simulate a blobless / partial clone configuration
    _run_git(repo, "config", "remote.origin.promisor", "true")
    _run_git(repo, "config", "remote.origin.partialclonefilter", "blob:none")

    result = await SecretLeaksAgent().execute({"target": str(repo), "scan_git_history": True})
    assert result.status == "partial", result.error
    assert result.data["commits_scanned"] == 0
    assert result.data["workspace_matches"] == 1
    assert result.data["git_history_matches"] == 0
    assert any("partial clone" in w.lower() for w in result.warnings)
    assert not any("failed:" in w.lower() for w in result.warnings)


async def test_git_history_patch_size_cap_and_lockfile_exclusion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if shutil.which("git") is None:
        pytest.skip("git not installed")

    repo = tmp_path / "bounded_repo"
    repo.mkdir()
    _run_git(repo, "init", "-q", "-b", "main")

    # Lockfile containing a token-shaped string should be excluded by git pathspecs
    lock_secret = _tok("ghp_", "9mK2pL7vR4wQ8nZ3xJ6bC1fH5gT0yU2aB4cDe")
    (repo / "package-lock.json").write_text(f'{{"token": "{lock_secret}"}}\n', encoding="utf-8")
    (repo / "app.py").write_text("x = 1\n" + ("# padding line\n" * 40), encoding="utf-8")
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-q", "-m", "first commit")

    (repo / "app.py").write_text("x = 2\n" + ("# more padding\n" * 40), encoding="utf-8")
    _run_git(repo, "add", "app.py")
    _run_git(repo, "commit", "-q", "-m", "second commit", date="2026-11-02T12:00:00+00:00")

    # Lockfile secret is excluded even without hitting patch cap
    normal = await SecretLeaksAgent().execute({"target": str(repo), "scan_git_history": True})
    assert normal.status == "ok", normal.error
    assert normal.data["total_matches"] == 0

    # Patch byte cap truncates cleanly with warning and partial status
    monkeypatch.setattr("secret_leaks.scanner._MAX_GIT_PATCH_BYTES", 150)
    capped = await SecretLeaksAgent().execute({"target": str(repo), "scan_git_history": True})
    assert capped.status == "partial", capped.error
    assert any("patch limit" in w.lower() for w in capped.warnings)


async def test_min_severity_paths_binary_and_cancellation(tmp_path: Path) -> None:
    high_tok = _tok("AKIA", "Q7M9K2P4L8N3R5X6")
    med_tok = _tok("AIza", "SyD9mK2pL7vR4wQ8nZ3xJ6bC1fH5gT0yU2aB")
    low_pass = "Str0ngPass!9"  # len 12, entropy ~3.42 -> generic_secret low severity

    (tmp_path / "src").mkdir()
    (tmp_path / "other").mkdir()
    (tmp_path / "src" / "a.py").write_text(
        f'K = "{high_tok}"\nG = "{med_tok}"\npassword = "{low_pass}"\n',
        encoding="utf-8",
    )
    (tmp_path / "other" / "b.py").write_text(f'OTHER = "{high_tok}"\n', encoding="utf-8")
    (tmp_path / "src" / "bin.dat").write_bytes(b"\x00\x01\x02" + high_tok.encode("ascii"))

    high_only = await SecretLeaksAgent().execute(
        {"target": str(tmp_path), "paths": ["src"], "min_severity": "high"}
    )
    assert high_only.status == "ok"
    assert high_only.data["total_matches"] == 1
    assert high_only.data["counts_by_severity"] == {"high": 1, "medium": 0, "low": 0}
    assert high_only.data["files_scanned"] == 1

    all_sev = await SecretLeaksAgent().execute({"target": str(tmp_path), "paths": ["src"]})
    assert all_sev.status == "ok"
    assert all_sev.data["counts_by_severity"] == {"high": 1, "medium": 1, "low": 1}

    token = CancellationToken()
    token.cancel()
    cancelled = await SecretLeaksAgent().execute(
        {"target": str(tmp_path)},
        ctx=RunContext(cancel_token=token),
    )
    assert cancelled.status == "error"
    assert "cancelled" in (cancelled.error or "").lower()


async def test_pem_key_moved_within_file_is_still_in_head(tmp_path: Path) -> None:
    if shutil.which("git") is None:
        pytest.skip("git not installed")

    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init", "-q", "-b", "main")
    header = _tok("-----BEGIN RSA ", "PRIVATE KEY-----")
    key = [header, "not-a-real-key-body", "-----END RSA PRIVATE KEY-----"]
    (repo / "deploy.txt").write_text("\n".join(key) + "\n", encoding="utf-8")
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-q", "-m", "add key")
    (repo / "deploy.txt").write_text("\n".join(["# notes", "", *key]) + "\n", encoding="utf-8")
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-q", "-m", "move key", date="2026-11-02T12:00:00+00:00")

    result = await SecretLeaksAgent().execute({"target": str(repo)})
    assert result.status == "ok", result.error
    assert result.data["total_matches"] == 1
    match = result.data["matches"][0]
    assert match["source"] == "workspace"
    assert match["line"] == 3
    assert match["in_head"] is True


async def test_long_lines_vendored_files_and_skipped_note(tmp_path: Path) -> None:
    gh_tok = _tok("ghp_", "9mK2pL7vR4wQ8nZ3xJ6bC1fH5gT0yU2aB4cDe")
    aws_key = _tok("AKIA", "Q7M9K2P4L8N3R5X6")
    filler = '"pad": "' + "a b " * 3000 + '", '
    (tmp_path / "config.json").write_text(
        "{" + filler + f'"token": "{gh_tok}"' + "}", encoding="utf-8"
    )
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor" / "client.py").write_text(f'KEY = "{aws_key}"\n', encoding="utf-8")
    (tmp_path / ".vscode").mkdir()
    (tmp_path / ".vscode" / "settings.json").write_text("{}", encoding="utf-8")

    result = await SecretLeaksAgent().execute({"target": str(tmp_path)})
    assert result.status == "ok", result.error
    found = {(m["file_path"], m["rule_id"]) for m in result.data["matches"]}
    assert ("config.json", "github_token") in found
    assert ("vendor/client.py", "aws_access_key") in found
    assert any(w.startswith("Not scanned:") and ".vscode" in w for w in result.warnings)

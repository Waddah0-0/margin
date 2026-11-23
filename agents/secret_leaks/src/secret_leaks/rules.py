"""Detection rules, entropy/placeholder filtering, suppression, and redaction."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass

from secret_leaks.models import Severity

MAX_LINE_LENGTH = 4096
_LONG_LINE_OVERLAP = 512  # longer lines are scanned in overlapping windows

SEVERITY_RANK: dict[Severity, int] = {
    "low": 1,
    "medium": 2,
    "high": 3,
}

INLINE_IGNORE_RE = re.compile(
    r"(?:margin\s*:\s*ignore|pragma\s*:\s*allowlist\s+secret)",
    re.IGNORECASE,
)

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]+")
_ANGLE_PLACEHOLDER_RE = re.compile(r"<[^<>\s]{2,}>")
_INTERP_PLACEHOLDER_RE = re.compile(r"\$\{[^}]+\}|\{\{[^}]+\}\}")
_TEST_DELIMITED_RE = re.compile(r"(?:^|[^a-z0-9])test(?:[^a-z0-9]|$)", re.IGNORECASE)
_PLACEHOLDER_SUBSTRINGS = (
    "example",
    "changeme",
    "change_me",
    "change-me",
    "your_",
    "your-",
    "dummy",
    "placeholder",
    "xxxx",
    "0000",
    "****",
)
_COMMON_NON_SECRET_WORDS = frozenset(
    {
        "password",
        "passwd",
        "pass",
        "secret",
        "token",
        "apikey",
        "api_key",
        "bearer",
        "basic",
        "oauth",
        "oauth2",
        "jwt",
        "csrf",
        "xsrf",
        "none",
        "null",
        "true",
        "false",
        "undefined",
        "unknown",
        "default",
        "redacted",
        "hidden",
        "masked",
        "empty",
        "postgres",
        "postgresql",
        "mysql",
        "mongodb",
        "redis",
        "admin",
        "root",
        "localhost",
        "development",
        "production",
        "staging",
        "authorization",
        "authentication",
        "credentials",
        "credential",
        "123456",
        "12345678",
        "123456789",
    }
)
_IDENT_SUFFIX_RE = re.compile(
    r"^[a-z]+(?:[_-][a-z]+)*[_-](?:key|token|secret|password|passwd|id|url|uri|name|header|env)$"
)
_PATH_OR_URL_PREFIXES = ("http://", "https://", "/", "./", "../", "~/")


@dataclass(frozen=True)
class CandidateMatch:
    """Internal match before redaction; never serialize or expose ``raw_secret``."""

    rule_id: str
    rule_name: str
    severity: Severity
    redacted_preview: str
    entropy: float | None
    secret_digest: str
    span: tuple[int, int]


@dataclass(frozen=True)
class _RuleSpec:
    rule_id: str
    rule_name: str
    severity: Severity
    pattern: re.Pattern[str]
    secret_group: int = 0
    prefix_re: re.Pattern[str] | None = None
    min_entropy: float | None = None
    check_placeholder: bool = True


_RULES: tuple[_RuleSpec, ...] = (
    _RuleSpec(
        rule_id="aws_access_key",
        rule_name="AWS Access Key ID",
        severity="high",
        pattern=re.compile(r"(?<![A-Z0-9])((?:AKIA|ASIA)[0-9A-Z]{16})(?![A-Z0-9])"),
        secret_group=1,
        prefix_re=re.compile(r"^(?:AKIA|ASIA)"),
        min_entropy=2.2,
    ),
    _RuleSpec(
        rule_id="aws_secret_key",
        rule_name="AWS Secret Access Key",
        severity="high",
        pattern=re.compile(
            r"(?i)\baws[_-]?(?:secret[_-]?(?:access[_-]?)?key)\b"
            r"\s*[:=]\s*['\"]?([A-Za-z0-9/+=]{40})['\"]?(?![A-Za-z0-9/+=])"
        ),
        secret_group=1,
        min_entropy=3.2,
    ),
    _RuleSpec(
        rule_id="github_token",
        rule_name="GitHub Token",
        severity="high",
        pattern=re.compile(
            r"\b((?:gh[pousr]_[A-Za-z0-9]{20,255})|(?:github_pat_[A-Za-z0-9_]{20,255}))\b"
        ),
        secret_group=1,
        prefix_re=re.compile(r"^(?:github_pat_|gh[pousr]_)"),
        min_entropy=2.2,
    ),
    _RuleSpec(
        rule_id="gitlab_token",
        rule_name="GitLab Personal Access Token",
        severity="high",
        pattern=re.compile(r"\b(glpat-[A-Za-z0-9_-]{20,255})\b"),
        secret_group=1,
        prefix_re=re.compile(r"^glpat-"),
        min_entropy=2.2,
    ),
    _RuleSpec(
        rule_id="slack_token",
        rule_name="Slack Token",
        severity="high",
        pattern=re.compile(r"\b(xox[baprs]-[0-9A-Za-z-]{12,255})\b"),
        secret_group=1,
        prefix_re=re.compile(r"^xox[baprs]-"),
        min_entropy=2.2,
    ),
    _RuleSpec(
        rule_id="stripe_key",
        rule_name="Stripe Live API Key",
        severity="high",
        pattern=re.compile(r"\b((?:sk|rk)_live_[0-9A-Za-z]{16,255})\b"),
        secret_group=1,
        prefix_re=re.compile(r"^(?:sk|rk)_live_"),
        min_entropy=2.2,
    ),
    _RuleSpec(
        rule_id="anthropic_api_key",
        rule_name="Anthropic API Key",
        severity="high",
        pattern=re.compile(
            r"(?<![A-Za-z0-9_-])(sk-ant-(?:api\d+-)?[A-Za-z0-9_-]{20,255})(?![A-Za-z0-9_-])"
        ),
        secret_group=1,
        prefix_re=re.compile(r"^sk-ant-(?:api\d+-)?"),
        min_entropy=2.2,
    ),
    _RuleSpec(
        rule_id="openai_api_key",
        rule_name="OpenAI API Key",
        severity="high",
        pattern=re.compile(
            r"(?<![A-Za-z0-9_-])(sk-(?:(?:proj|svcacct|admin)-[A-Za-z0-9_-]{20,255}"
            r"|(?!ant-)[A-Za-z0-9]{20,255}))(?![A-Za-z0-9_-])"
        ),
        secret_group=1,
        prefix_re=re.compile(r"^sk-(?:(?:proj|svcacct|admin)-)?"),
        min_entropy=2.2,
    ),
    _RuleSpec(
        rule_id="google_api_key",
        rule_name="Google API Key",
        severity="medium",
        pattern=re.compile(r"(?<![A-Za-z0-9_-])(AIza[0-9A-Za-z_-]{32,40})(?![A-Za-z0-9_-])"),
        secret_group=1,
        prefix_re=re.compile(r"^AIza"),
        min_entropy=2.2,
    ),
    _RuleSpec(
        rule_id="pem_private_key",
        rule_name="PEM Private Key",
        severity="high",
        pattern=re.compile(r"(-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----)"),
        secret_group=1,
        min_entropy=None,
        check_placeholder=False,
    ),
)

_DB_URL_RE = re.compile(
    r"\b((postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqps?)://"
    r"([^\s:/?#\"'<>@]+):([^\s\"'<>@]+)@([A-Za-z0-9._-]+(?::\d+)?))"
)

_GENERIC_SECRET_RE = re.compile(
    r"(?i)(?:['\"])?"
    r"\b[a-z0-9_-]{0,40}"
    r"(?:api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token|"
    r"refresh[_-]?token|client[_-]?secret|private[_-]?key|signing[_-]?key|"
    r"encryption[_-]?key|jwt[_-]?secret|db[_-]?password|database[_-]?password|"
    r"password|passwd|secret|token)\b"
    r"(?:['\"])?\s*(?::=|[:=])\s*(['\"])([^\s'\"\\]{8,256})\1"
)


def strip_control_chars(text: str) -> str:
    """Remove C0, DEL, and C1 control characters from untrusted text."""
    return _CONTROL_CHARS_RE.sub("", text)


def shannon_entropy(value: str) -> float:
    """Compute Shannon entropy in bits per character."""
    if not value:
        return 0.0
    length = len(value)
    counts = Counter(value)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def redact(value: str, prefix: str = "") -> str:
    """Return a masked preview that shows at most four characters of the secret itself.

    ``prefix`` is a public part of the value, such as ``ghp_`` or ``AKIA``, and is shown
    whole, followed by the last two characters. Without a prefix, values shorter than 16
    characters are fully masked and longer ones show their first and last two characters.
    """
    cleaned = strip_control_chars(" ".join(value.split()))
    prefix = strip_control_chars(prefix) if cleaned.startswith(prefix) else ""
    body = cleaned[len(prefix) :]
    if prefix:
        return f"{prefix}***" if len(body) < 12 else f"{prefix}...{body[-2:]}"
    if len(body) < 16:
        return "***"
    return f"{body[:2]}...{body[-2:]}"


def _pem_preview(header: str) -> str:
    """Return a readable, non-secret PEM header label without dashes or key material."""
    return strip_control_chars(" ".join(header.strip("-").split()))


def _strip_prefix(value: str, prefix_re: re.Pattern[str] | None) -> str:
    if prefix_re is None:
        return value
    return prefix_re.sub("", value, count=1)


def is_placeholder(
    value: str,
    *,
    body: str | None = None,
    check_test_substring: bool = False,
) -> bool:
    """Return True when ``value`` looks like a documentation or test placeholder.

    When ``check_test_substring`` is False (used for high-precision provider rules),
    ``"test"`` only triggers on delimiter boundaries (e.g. ``test_...`` or ``-test-``)
    so random tokens containing ``test`` are not dropped.
    """
    if _ANGLE_PLACEHOLDER_RE.search(value) or _INTERP_PLACEHOLDER_RE.search(value):
        return True
    target = (body if body is not None else value).lower()
    if any(marker in target for marker in _PLACEHOLDER_SUBSTRINGS):
        return True
    if check_test_substring:
        if "test" in target:
            return True
    elif _TEST_DELIMITED_RE.search(target):
        return True
    if value.lower() in _COMMON_NON_SECRET_WORDS or target in _COMMON_NON_SECRET_WORDS:
        return True
    return False


def is_inline_ignored(line: str) -> bool:
    """Return True if ``line`` contains an explicit inline suppression comment."""
    return INLINE_IGNORE_RE.search(line) is not None


def compile_allowlist(patterns: list[str]) -> list[re.Pattern[str]]:
    """Compile user-supplied allowlist regular expressions."""
    return [re.compile(p) for p in patterns]


def _is_allowlisted(
    allowlist: list[re.Pattern[str]],
    secret_value: str,
    matched_text: str,
    line: str,
) -> bool:
    return any(
        pattern.search(secret_value) or pattern.search(matched_text) or pattern.search(line)
        for pattern in allowlist
    )


def digest_text(text: str) -> str:
    """SHA-256 of ``text``, used to match the same secret across files and commits."""
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _spans_overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def scan_line(
    line: str,
    *,
    allowlist: list[re.Pattern[str]] | None = None,
    min_severity: Severity = "low",
) -> list[CandidateMatch]:
    """Scan a single line of text and return redacted candidate matches."""
    if not line or is_inline_ignored(line):
        return []
    if len(line) > MAX_LINE_LENGTH:
        return _scan_long_line(line, allowlist=allowlist, min_severity=min_severity)

    compiled_allowlist = allowlist or []
    min_rank = SEVERITY_RANK[min_severity]
    matches: list[CandidateMatch] = []
    occupied_spans: list[tuple[int, int]] = []

    # 1. High-precision provider and PEM patterns
    for rule in _RULES:
        for hit in rule.pattern.finditer(line):
            secret = hit.group(rule.secret_group)
            span = hit.span(rule.secret_group)
            body = _strip_prefix(secret, rule.prefix_re)
            if rule.check_placeholder and is_placeholder(secret, body=body):
                continue
            entropy = round(shannon_entropy(body), 3) if rule.min_entropy is not None else None
            if rule.min_entropy is not None and entropy is not None and entropy < rule.min_entropy:
                continue
            if _is_allowlisted(compiled_allowlist, secret, hit.group(0), line):
                continue
            occupied_spans.append(span)
            if SEVERITY_RANK[rule.severity] < min_rank:
                continue
            if rule.rule_id == "pem_private_key":
                preview = _pem_preview(secret)
            else:
                preview = redact(secret, prefix=secret[: len(secret) - len(body)])
            matches.append(
                CandidateMatch(
                    rule_id=rule.rule_id,
                    rule_name=rule.rule_name,
                    severity=rule.severity,
                    redacted_preview=preview,
                    entropy=entropy,
                    secret_digest=digest_text(secret),
                    span=span,
                )
            )

    # 2. Database URLs with embedded credentials
    for hit in _DB_URL_RE.finditer(line):
        full_url = hit.group(1)
        scheme = strip_control_chars(hit.group(2))
        password = hit.group(4)
        host_port = strip_control_chars(hit.group(5))
        span = hit.span(1)
        if is_placeholder(password):
            continue
        entropy = round(shannon_entropy(password), 3)
        if entropy < 2.3:
            continue
        if _is_allowlisted(compiled_allowlist, password, full_url, line):
            continue
        occupied_spans.append(span)
        if SEVERITY_RANK["high"] < min_rank:
            continue
        matches.append(
            CandidateMatch(
                rule_id="database_url",
                rule_name="Database URL with Credentials",
                severity="high",
                redacted_preview=f"{scheme}://***:***@{host_port}",
                entropy=entropy,
                secret_digest=digest_text(full_url),
                span=span,
            )
        )

    # 3. Generic quoted secret assignments (skipped when overlapping a specific match)
    for hit in _GENERIC_SECRET_RE.finditer(line):
        secret = hit.group(2)
        span = hit.span(2)
        if any(_spans_overlap(span, prev) for prev in occupied_spans):
            continue
        if secret.startswith(_PATH_OR_URL_PREFIXES):
            continue
        if is_placeholder(secret, check_test_substring=True):
            continue
        if _IDENT_SUFFIX_RE.match(secret):
            continue
        entropy = round(shannon_entropy(secret), 3)
        if entropy < 3.0:
            continue
        if _is_allowlisted(compiled_allowlist, secret, hit.group(0), line):
            continue
        severity: Severity = "medium" if (entropy >= 3.5 or len(secret) >= 16) else "low"
        if SEVERITY_RANK[severity] < min_rank:
            continue
        matches.append(
            CandidateMatch(
                rule_id="generic_secret",
                rule_name="Generic Secret Assignment",
                severity=severity,
                redacted_preview=redact(secret),
                entropy=entropy,
                secret_digest=digest_text(secret),
                span=span,
            )
        )

    return matches


def _scan_long_line(
    line: str,
    *,
    allowlist: list[re.Pattern[str]] | None,
    min_severity: Severity,
) -> list[CandidateMatch]:
    """Scan a line longer than ``MAX_LINE_LENGTH`` (minified JSON, one-line configs) in
    overlapping windows, so a secret is found wherever it sits and is reported once."""
    step = MAX_LINE_LENGTH - _LONG_LINE_OVERLAP
    seen: set[tuple[str, str]] = set()
    matches: list[CandidateMatch] = []
    for start in range(0, len(line), step):
        window = line[start : start + MAX_LINE_LENGTH]
        for match in scan_line(window, allowlist=allowlist, min_severity=min_severity):
            key = (match.rule_id, match.secret_digest)
            if key in seen:
                continue
            seen.add(key)
            span = (match.span[0] + start, match.span[1] + start)
            matches.append(
                CandidateMatch(
                    rule_id=match.rule_id,
                    rule_name=match.rule_name,
                    severity=match.severity,
                    redacted_preview=match.redacted_preview,
                    entropy=match.entropy,
                    secret_digest=match.secret_digest,
                    span=span,
                )
            )
        if start + MAX_LINE_LENGTH >= len(line):
            break
    return matches

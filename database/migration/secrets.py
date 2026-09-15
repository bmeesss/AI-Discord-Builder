"""Secret safety for the migration tooling.

Two responsibilities:

1. :func:`scan_record` / :func:`scan_text` detect credentials that must never
   end up in an export (Discord tokens, provider keys, Supabase keys, database
   passwords, ...).  The exporter runs this before it declares success and
   records the result in the manifest; the validator re-runs it over the files.
2. :func:`redact` scrubs credentials out of *any* text before it is printed or
   logged, so an SDK error can never leak a key into the terminal or CI logs.

Severity model
--------------
``critical``
    A value that *is* a credential: a known secret value from the environment,
    or a value matching a high-confidence token pattern.  Critical findings
    block a successful export and block importing.
``suspicious``
    A sensitive-looking *key name* (``token``, ``api_key``, ``password``, ...)
    or an inline ``key=value`` assignment.  Reported loudly, does not block —
    real data (a memory named ``webhook_url``) can legitimately match, and the
    operator decides.  Never silent: the manifest, the validator and the
    import summary all repeat the warning.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

REDACTED = "***"

# Environment variables whose value must never appear in an export or a log.
SECRET_ENV_VARS: tuple[str, ...] = (
    "DISCORD_TOKEN",
    "GROQ_API_KEY",
    "OPENAI_API_KEY",
    "OPENAI_API_BASE",
    "SUPABASE_KEY",
    "SUPABASE_SERVICE_KEY",
    "SUPABASE_ANON_KEY",
    "SUPABASE_JWT_SECRET",
    "POSTGRES_PASSWORD",
    "DATABASE_URL",
    "ANTHROPIC_API_KEY",
    "HUGGINGFACE_API_KEY",
    "AWS_SECRET_ACCESS_KEY",
)

# Values shorter than this are not treated as secrets (avoids masking "1").
MIN_SECRET_LENGTH = 6

# --------------------------------------------------------------------------
# Patterns
# --------------------------------------------------------------------------

TOKEN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("discord_token", re.compile(r"\b[A-Za-z0-9_-]{24}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,}\b")),
    ("discord_mfa_token", re.compile(r"\bmfa\.[A-Za-z0-9_-]{20,}\b")),
    ("openai_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{16,}\b")),
    ("groq_key", re.compile(r"\bgsk_[A-Za-z0-9]{20,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("url_with_password", re.compile(r"\b[a-z][a-z0-9+.\-]*://[^\s:/@]+:[^\s:/@]+@")),
)

# Key names that make a value worth reporting (severity: suspicious).
SENSITIVE_KEY_NAMES = re.compile(
    r"(?:token|secret|password|passwd|pwd|api[_-]?key|apikey|access[_-]?key|"
    r"private[_-]?key|credential|authorization|auth[_-]?header|cookie|"
    r"session[_-]?id|webhook[_-]?url|connection[_-]?string|\bdsn\b|"
    r"client[_-]?secret|refresh[_-]?token)",
    re.IGNORECASE,
)

# Inline assignments such as "password=hunter2" inside a free-text value.
ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|"
    r"authorization|bearer)\b\s*[:=]\s*[\"']?(?P<value>[^\s\"',;}]{4,})"
)

# Long run of base64/hex-ish characters: only reported together with a
# sensitive key name (never on its own) to avoid false positives.
HIGH_ENTROPY_VALUE = re.compile(r"^[A-Za-z0-9+/=_-]{16,}$")


@dataclass(frozen=True)
class Finding:
    """One detected (potential) secret."""

    severity: str  # "critical" | "suspicious"
    kind: str
    path: str
    detail: str = ""

    def describe(self) -> str:
        location = f" at {self.path}" if self.path else ""
        detail = f" ({self.detail})" if self.detail else ""
        return f"{self.severity}: {self.kind}{location}{detail}"


@dataclass
class ScanResult:
    """Aggregated scan outcome."""

    findings: list[Finding] = field(default_factory=list)
    scanned_records: int = 0

    def add(self, finding: Finding) -> None:
        self.findings.append(finding)

    @property
    def critical(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "critical"]

    @property
    def suspicious(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "suspicious"]

    @property
    def status(self) -> str:
        if self.critical:
            return "failed"
        if self.suspicious:
            return "warnings"
        return "clean"

    @property
    def ok(self) -> bool:
        return not self.critical

    def as_dict(self, limit: int = 20) -> dict[str, Any]:
        return {
            "status": self.status,
            "scanned_records": self.scanned_records,
            "critical_count": len(self.critical),
            "suspicious_count": len(self.suspicious),
            "findings": [
                {
                    "severity": finding.severity,
                    "kind": finding.kind,
                    "path": finding.path,
                    "detail": finding.detail,
                }
                for finding in self.findings[:limit]
            ],
        }


def known_secret_values(environ: dict[str, str] | None = None) -> list[str]:
    """Collect configured secret values (never logged, only compared)."""

    source = environ if environ is not None else os.environ
    values: list[str] = []

    for name in SECRET_ENV_VARS:
        value = (source.get(name) or "").strip()
        if len(value) >= MIN_SECRET_LENGTH:
            values.append(value)

    # The password inside a DSN is a secret on its own too.
    for name in SECRET_ENV_VARS:
        value = (source.get(name) or "").strip()
        if "://" in value and "@" in value:
            credentials = value.split("://", 1)[1].split("@", 1)[0]
            if ":" in credentials:
                password = credentials.split(":", 1)[1]
                if len(password) >= MIN_SECRET_LENGTH:
                    values.append(password)
    return values


class SecretScanner:
    """Scans records and text for credentials."""

    def __init__(
        self,
        secret_values: Iterable[str] | None = None,
        max_findings: int = 50,
    ) -> None:
        # Longest first so the most specific value is masked/reported.
        self._secret_values = sorted(
            set(secret_values if secret_values is not None
                else known_secret_values()),
            key=len,
            reverse=True,
        )
        self._max_findings = max_findings

    # -- public API --------------------------------------------------------

    def scan_record(self, record: Any, path: str = "$") -> list[Finding]:
        findings: list[Finding] = []
        self._scan_value(record, path, None, findings)
        return findings

    def scan_text(self, text: str, path: str = "$") -> list[Finding]:
        findings: list[Finding] = []
        self._scan_string(text, path, None, findings)
        return findings

    def scan(self, records: Iterable[Any], path: str = "$") -> ScanResult:
        result = ScanResult()
        for index, record in enumerate(records):
            for finding in self.scan_record(record, f"{path}[{index}]"):
                result.add(finding)
            result.scanned_records += 1
            if len(result.findings) >= self._max_findings:
                break
        return result

    # -- internals ---------------------------------------------------------

    def _add(self, findings: list[Finding], finding: Finding) -> None:
        if len(findings) < self._max_findings:
            findings.append(finding)

    def _scan_value(
        self,
        value: Any,
        path: str,
        key: str | None,
        findings: list[Finding],
    ) -> None:
        if isinstance(value, dict):
            for child_key, child in value.items():
                child_path = f"{path}.{child_key}"
                self._scan_value(child, child_path, str(child_key), findings)
            return

        if isinstance(value, list):
            for index, child in enumerate(value):
                self._scan_value(child, f"{path}[{index}]", key, findings)
            return

        if isinstance(value, str):
            self._scan_string(value, path, key, findings)

    def _scan_string(
        self,
        value: str,
        path: str,
        key: str | None,
        findings: list[Finding],
    ) -> None:
        if not value:
            return

        for secret in self._secret_values:
            if secret in value:
                self._add(
                    findings,
                    Finding(
                        "critical",
                        "configured_secret_value",
                        path,
                        "value matches a configured credential",
                    ),
                )
                return

        for kind, pattern in TOKEN_PATTERNS:
            if pattern.search(value):
                self._add(findings, Finding("critical", kind, path, ""))
                return

        if key and SENSITIVE_KEY_NAMES.search(key):
            detail = "non-empty value" if value else "null value"
            if HIGH_ENTROPY_VALUE.match(value.strip()):
                detail = "high-entropy value"
            self._add(
                findings,
                Finding("suspicious", "sensitive_key_name", path, detail),
            )
            return

        match = ASSIGNMENT_PATTERN.search(value)
        if match:
            self._add(
                findings,
                Finding("suspicious", "inline_assignment", path, ""),
            )


# --------------------------------------------------------------------------
# Redaction for logs and error messages
# --------------------------------------------------------------------------


def redact(
    text: Any,
    secret_values: Iterable[str] | None = None,
) -> str:
    """Return ``text`` with every known credential replaced by ``***``."""

    result = text if isinstance(text, str) else str(text)
    values = list(secret_values) if secret_values is not None else None
    if values is None:
        values = known_secret_values()

    for secret in sorted(set(values), key=len, reverse=True):
        result = result.replace(secret, REDACTED)

    for _kind, pattern in TOKEN_PATTERNS:
        result = pattern.sub(REDACTED, result)

    # Assignments such as password=hunter2 that survived the checks above.
    result = ASSIGNMENT_PATTERN.sub(
        lambda match: match.group(0).replace(match.group("value"), REDACTED),
        result,
    )
    return result

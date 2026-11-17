"""Error types and redaction for anything written to sync_runs.error / connections.last_error."""

from __future__ import annotations

import re

MAX_ERROR_LENGTH = 2000
REDACTED = "[REDACTED]"


class SourceAuthError(Exception):
    """Credentials were rejected (expired/revoked token). The connection becomes 'expired'."""


class SourceConfigError(Exception):
    """The connection or environment is misconfigured (e.g. bad account ID)."""


_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

_REDACT_KEY_NAMES = (
    r"access[_-]?token|refresh[_-]?token|id[_-]?token|client[_-]?secret|developer[_-]?token"
    r"|app[_-]?secret|api[_-]?key|apikey|password|passwd|secret|token|authorization"
    r"|x-api-key|sig|signature"
)

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Authorization: Bearer xxx / Basic xxx
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9\-._~+/]+=*"), r"\1 " + REDACTED),
    # key=value, key: value, "key": "value", key='value' (query strings, JSON, dicts)
    (
        re.compile(
            r"""(?ix)
            (["']?\b(?:"""
            + _REDACT_KEY_NAMES
            + r""")\b["']?\s*[:=]\s*)  # key and separator
            (["']?)                                                     # optional quote
            [^\s"'&,;}\]]+                                              # the value
            """
        ),
        r"\1\2" + REDACTED,
    ),
    # JWTs
    (re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*"), REDACTED),
    # Google OAuth access tokens and refresh tokens
    (re.compile(r"\bya29\.[A-Za-z0-9_\-.]+"), REDACTED),
    (re.compile(r"\b1//[A-Za-z0-9_\-]{10,}"), REDACTED),
]

# Any long run of token-ish characters (Meta EAA..., base64 blobs, hex secrets).
_LONG_TOKEN = re.compile(r"[A-Za-z0-9+/_\-]{32,}={0,2}")


def _redact_long(match: re.Match[str]) -> str:
    text = match.group(0)
    return text if _UUID.match(text) else REDACTED


def redact(message: object) -> str:
    """Strip anything token-shaped from an error message, then cap its length.

    Errs on the side of over-redacting: a slightly less useful error is fine, a leaked
    token is not. UUIDs (our row IDs) are kept because they're needed for debugging.
    """
    text = str(message)
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    text = _LONG_TOKEN.sub(_redact_long, text)
    if len(text) > MAX_ERROR_LENGTH:
        text = text[:MAX_ERROR_LENGTH] + "... [truncated]"
    return text

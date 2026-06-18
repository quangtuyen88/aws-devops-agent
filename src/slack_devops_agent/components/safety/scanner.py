"""CMP-005 — Input Safety Scanner (API-INT-003).

The pre-send gate (CS-4): scans assembled input for secrets/credentials BEFORE any
inference or MCP call (BR-012). Posture (NFR-4/NFR-21, Q4=b): best-effort heuristic,
**refuse-or-allow only** — a positive detection always returns ``refuse`` (never
``warn``), there is no override, and findings carry only redacted *class* descriptors,
never raw values (NFR-6/BR-026). On scanner error it fails safe to ``refuse``.

The rule set is a curated regex collection with known best-effort precision/recall limits
(it will miss novel/obfuscated secrets and may flag benign high-entropy strings); rules
evolve inside this component on their own cadence (A-6).
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass

from ...domain.entities import SafetyFinding, SafetyVerdict
from ...domain.enums import SafetyAction


@dataclass(frozen=True)
class _Rule:
    """A named secret-detection rule (regex)."""

    kind: str
    pattern: re.Pattern[str]


# Curated rule set (nfr.yaml R-3.3). Kinds are the redacted descriptors surfaced to users.
_RULES: tuple[_Rule, ...] = (
    _Rule("aws-access-key-id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    _Rule("aws-secret-access-key", re.compile(r"(?i)aws_secret_access_key\s*[=:]\s*\S{20,}")),
    _Rule("pem-private-key", re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----")),
    _Rule("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    _Rule("bearer-oauth-token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{16,}\b")),
    _Rule(
        "connection-string",
        re.compile(r"(?i)\b(?:postgres|mysql|mongodb(?:\+srv)?|redis)://[^\s:@/]+:[^\s@/]+@"),
    ),
    _Rule("generic-api-key", re.compile(r"(?i)\b(?:api[_-]?key|secret|token)\s*[=:]\s*\S{16,}")),
)

_HIGH_ENTROPY_TOKEN = re.compile(r"\b[A-Za-z0-9+/=_\-]{32,}\b")
# Raised from 4.0: descriptive CamelCase identifiers common in IaC (long AWS role/policy/export
# names) sit ~4.1-4.3 bits/char and were false-flagged. Genuinely random base64/hex secrets sit
# ~4.6+. The precise prefix rules above (AKIA/xox-/ghp_/etc.) catch structured tokens regardless.
_HIGH_ENTROPY_BITS_PER_CHAR = 4.6
# A token that is purely alphabetic (after stripping word separators) is a descriptive identifier,
# never a credential — real secrets always mix in digits or base64 symbols. Exempted from the
# entropy heuristic to stop IaC identifiers (e.g. AWSServiceRoleForApplicationAutoScaling) flagging.
_ALPHABETIC_IDENTIFIER = re.compile(r"^[A-Za-z]+$")


def _is_alphabetic_identifier(token: str) -> bool:
    """True when ``token`` is only letters once `_`/`-` separators are removed (not a secret)."""
    return bool(_ALPHABETIC_IDENTIFIER.match(token.replace("_", "").replace("-", "")))


def _shannon_entropy_bits_per_char(token: str) -> float:
    """Shannon entropy (bits/char) of ``token`` — high values suggest random secrets."""
    if not token:
        return 0.0
    counts: dict[str, int] = {}
    for char in token:
        counts[char] = counts.get(char, 0) + 1
    length = len(token)
    return -sum((c / length) * math.log2(c / length) for c in counts.values())


class SecretScanner:
    """Heuristic secret detector implementing the :class:`SafetyScanner` port."""

    def scan(self, assembled_input: str) -> SafetyVerdict:
        """Scan ``assembled_input``; return a refuse-or-allow verdict (Q4=b).

        Fails safe to ``refuse`` if the scan itself raises, so a detector bug can never
        let unscanned input reach an external backend (NFR-4 invariant).
        """
        try:
            findings = list(self._find(assembled_input))
        except Exception:
            return SafetyVerdict(
                flagged=True,
                findings=[SafetyFinding(kind="scanner-error", location="input")],
                recommended_action=SafetyAction.REFUSE,
            )
        if findings:
            return SafetyVerdict(
                flagged=True,
                findings=findings,
                recommended_action=SafetyAction.REFUSE,
            )
        return SafetyVerdict(flagged=False, findings=[], recommended_action=SafetyAction.ALLOW)

    def _find(self, text: str) -> Iterable[SafetyFinding]:
        """Yield a redacted finding per matched rule (and high-entropy heuristic)."""
        for rule in _RULES:
            match = rule.pattern.search(text)
            if match is not None:
                yield SafetyFinding(kind=rule.kind, location=f"offset:{match.start()}")
        for token_match in _HIGH_ENTROPY_TOKEN.finditer(text):
            token = token_match.group(0)
            if _is_alphabetic_identifier(token):
                continue  # descriptive identifier (e.g. an AWS role/policy name), never a secret
            if _shannon_entropy_bits_per_char(token) >= _HIGH_ENTROPY_BITS_PER_CHAR:
                yield SafetyFinding(
                    kind="high-entropy-string", location=f"offset:{token_match.start()}"
                )
                break

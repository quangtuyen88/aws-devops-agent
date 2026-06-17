"""CMP-002 — render answers and failure messages to Slack-formatted text (FR-14/FR-17).

Citations render as Slack links (BR-016); code snippets render as code blocks, advice-only
(BR-017). Failure messages always resolve the FR-3 ack (BR-013) — never silence.
"""

from __future__ import annotations

from ...domain.entities import Answer
from ...domain.enums import FailureCause

_FAILURE_TEXT: dict[FailureCause, str] = {
    FailureCause.TIMEOUT: (
        "I couldn't finish this one in time. Please try re-asking — if it keeps timing "
        "out, try narrowing the question."
    ),
    FailureCause.CAP: (
        "This question needed more lookups than I'm allowed per request. Try splitting it "
        "into smaller, more specific questions."
    ),
    FailureCause.BUDGET_DENY: (
        "I've reached the workspace's usage budget for now. Please re-ask after the budget "
        "period resets."
    ),
    FailureCause.OVERSIZE: (
        "Your question (with thread context) is too large for me to process. Please shorten "
        "it or ask in a new, focused thread."
    ),
    FailureCause.SAFETY_REFUSE: (
        "I can't process that because it looks like it contains a secret or credential "
        "({classes}). Please remove it and re-ask — never paste secrets, keys, or tokens."
    ),
    FailureCause.DEPENDENCY: (
        "I hit an error reaching a backend service and couldn't complete your request. "
        "Please try re-asking shortly."
    ),
    FailureCause.EXHAUSTED_RETRIES: (
        "I tried a few times but couldn't complete your request. Please try re-asking shortly."
    ),
}

HEARTBEAT_TEXT = "Still working on it… :hourglass_flowing_sand:"


def render_answer(answer: Answer) -> str:
    """Render a composed :class:`Answer` into Slack-formatted text."""
    parts: list[str] = [f"*Recommendation:* {answer.recommendation.strip()}"]
    if answer.rationale.strip():
        parts.append(f"*Rationale:* {answer.rationale.strip()}")
    if answer.trade_offs and answer.trade_offs.strip():
        parts.append(f"*Trade-offs:* {answer.trade_offs.strip()}")
    if answer.alternatives and answer.alternatives.strip():
        parts.append(f"*Alternative:* {answer.alternatives.strip()}")
    for snippet in answer.code_snippets:
        parts.append(f"```\n{snippet}\n```")
    if answer.is_grounded and answer.citations:
        links = "\n".join(f"• <{c.url}|{c.title}>" for c in answer.citations)
        parts.append(f"*Sources:*\n{links}")
    return "\n\n".join(parts)


def render_failure(cause: FailureCause, *, secret_classes: list[str] | None = None) -> str:
    """Render the FR-17 in-thread failure message for ``cause`` (BR-013)."""
    template = _FAILURE_TEXT[cause]
    if cause == FailureCause.SAFETY_REFUSE:
        classes = ", ".join(secret_classes or []) or "a credential"
        return template.format(classes=classes)
    return template

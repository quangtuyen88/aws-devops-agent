"""CMP-002 — Answer composition (BR-015/BR-016/BR-017).

Builds a validated :class:`Answer` from the model output and grounding sources. Sections
are parsed from labelled markers the model is prompted to emit; code fences become
advice-only ``code_snippets`` (never executed, OOS-3). If a structured answer-type
(architecture-review / solution-design) lacks trade-offs, the type is downgraded to
``factual`` rather than fabricating one — consistent with BR-015's best-effort fallback.
"""

from __future__ import annotations

import re
from uuid import UUID

from ...domain.entities import Answer, GroundingSource
from ...domain.enums import AnswerType
from ...domain.rules import classify_answer_type

_CODE_FENCE = re.compile(r"```[a-zA-Z0-9]*\n(.*?)```", re.DOTALL)
_SECTION = re.compile(
    r"(?im)^\s*(recommendation|rationale|trade-?offs?|alternatives?)\s*:\s*(.*?)(?=^\s*"
    r"(?:recommendation|rationale|trade-?offs?|alternatives?)\s*:|\Z)",
    re.DOTALL,
)
_UNGROUNDED_MARKER = "_Note: this answer is not grounded in a cited AWS source._"


class DefaultAnswerComposer:
    """Heuristic composer implementing the :class:`AnswerComposer` port."""

    def compose(
        self,
        correlation_id: UUID,
        question: str,
        model_output: str,
        sources: list[GroundingSource],
    ) -> Answer:
        sections = self._parse_sections(model_output)
        recommendation = sections.get("recommendation") or model_output.strip()
        rationale = sections.get("rationale") or "See recommendation."
        trade_offs = sections.get("trade-offs") or sections.get("tradeoff") or None
        alternatives = sections.get("alternatives") or sections.get("alternative") or None
        code_snippets = [m.strip() for m in _CODE_FENCE.findall(model_output)]

        answer_type = classify_answer_type(question)
        # BR-015: a structured type without trade-offs is downgraded, not fabricated.
        if answer_type.requires_trade_offs and not (trade_offs and trade_offs.strip()):
            answer_type = AnswerType.FACTUAL

        is_grounded = len(sources) > 0
        if not is_grounded:
            rationale = f"{rationale}\n\n{_UNGROUNDED_MARKER}"

        return Answer(
            correlation_id=correlation_id,
            answer_type=answer_type,
            recommendation=recommendation,
            rationale=rationale,
            trade_offs=trade_offs,
            alternatives=alternatives,
            citations=sources,
            is_grounded=is_grounded,
            code_snippets=code_snippets,
        )

    @staticmethod
    def _parse_sections(text: str) -> dict[str, str]:
        """Extract labelled sections, normalising the key (e.g. ``trade-offs``)."""
        out: dict[str, str] = {}
        for label, body in _SECTION.findall(text):
            key = (
                label.strip()
                .lower()
                .replace("trade-offs", "trade-offs")
                .replace("tradeoffs", "trade-offs")
            )
            if key.startswith("trade"):
                key = "trade-offs"
            elif key.startswith("alternative"):
                key = "alternatives"
            out[key] = body.strip()
        return out

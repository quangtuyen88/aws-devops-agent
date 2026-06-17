"""CMP-008 — Configuration & Policy (DynamoDB adapter, API-INT-008).

Read-only to all consumers (BR-024); only operators mutate it. Each config item is one
DynamoDB row keyed by a stable config key. Missing required config falls back to a defined
fail-safe default (e.g. ``non-allowlisted-behaviour=reply-not-designated``, F-3).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...domain.entities import ChannelAllowlist, GuardrailConfig, UsagePolicy
from ...domain.enums import NonAllowlistedBehaviour

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

_KEY_ALLOWLIST = "allowlist"
_KEY_USAGE_POLICY = "usage-policy"
_KEY_GUARDRAIL = "guardrail"


class DynamoConfigStore:
    """DynamoDB-backed :class:`ConfigStore` (read-only)."""

    def __init__(self, table: Table, default_per_period_limit: int = 500) -> None:
        self._table = table
        self._default_per_period_limit = default_per_period_limit

    def _read(self, key: str) -> dict[str, object] | None:
        response = self._table.get_item(Key={"pk": key})
        item = response.get("Item")
        return dict(item) if item else None

    def get_allowlist(self) -> ChannelAllowlist:
        item = self._read(_KEY_ALLOWLIST)
        if item is None:
            # Fail safe: no channels allowed, and announce the designated-channels rule.
            return ChannelAllowlist(
                allowed_channel_ids=[],
                non_allowlisted_behaviour=NonAllowlistedBehaviour.REPLY_NOT_DESIGNATED,
            )
        raw_ids = item.get("allowed_channel_ids")
        channel_ids = [str(c) for c in raw_ids] if isinstance(raw_ids, list) else []
        behaviour = str(item.get("non_allowlisted_behaviour") or "reply-not-designated")
        return ChannelAllowlist(
            allowed_channel_ids=channel_ids,
            non_allowlisted_behaviour=NonAllowlistedBehaviour(behaviour),
        )

    def get_usage_policy(self) -> UsagePolicy:
        item = self._read(_KEY_USAGE_POLICY)
        if item is None:
            return UsagePolicy(
                policy_text=(
                    "Only internal, non-production content. Never paste secrets, "
                    "credentials, PII, or customer/production data."
                )
            )
        return UsagePolicy(
            policy_text=str(item["policy_text"]),
            published_location_ref=(
                str(item["published_location_ref"]) if item.get("published_location_ref") else None
            ),
        )

    def get_guardrail(self) -> GuardrailConfig:
        item = self._read(_KEY_GUARDRAIL)
        if item is None:
            return GuardrailConfig(per_period_limit=self._default_per_period_limit)
        per_request = item.get("per_request_limit")
        per_period = item.get("per_period_limit")
        return GuardrailConfig(
            per_request_limit=int(str(per_request)) if per_request is not None else None,
            per_period_limit=int(str(per_period)) if per_period is not None else None,
            period_definition=str(item.get("period_definition") or "week"),
        )

"""Tests for CMP-005 safety scanner (Slice 3) — NFR-4/NFR-21/BR-012."""

from __future__ import annotations

import pytest

from slack_devops_agent.components.safety import SecretScanner
from slack_devops_agent.domain.enums import SafetyAction

# Synthetic secret corpus (fabricated, not real credentials).
SECRET_CORPUS = [
    "my key is AKIAIOSFODNN7EXAMPLE please use it",
    "aws_secret_access_key = wJalrXUtnFEMIabcdEFGHijklMNOPqrstUVWxyz12",
    "-----BEGIN RSA PRIVATE KEY-----\nMIIEoAIB...\n-----END RSA PRIVATE KEY-----",
    "slack token xoxb-EXAMPLE-PLACEHOLDER-NOT-A-REAL-TOKEN",
    "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
    "db url postgres://admin:s3cr3tPassword@db.internal:5432/app",
    "api_key: 1234567890abcdef1234567890",
    # A genuinely random, high-entropy base64 token (no recognizable prefix) must still flag via
    # the entropy backstop even after the threshold was raised to reduce IaC false positives.
    "token blob 7kQx2pLm9vRtZ4Nw8sFhB3jYcA6dKeUgW1oIqP5XnMa0bThlD",
]

BENIGN_CORPUS = [
    "How do I configure an Auto Scaling group across 3 AZs?",
    "What is the cheapest way to store infrequently accessed objects in S3?",
    "Why is my Lambda timing out when calling DynamoDB?",
    "Should I use ECS Fargate or EKS for a small service?",
    # IaC identifiers that previously false-flagged as high-entropy strings (BR-012 regression):
    # long descriptive AWS role/policy/export names are not credentials.
    "RoleARN: AWSServiceRoleForApplicationAutoScaling_ECSService is a managed service role",
    "ManagedPolicyArns include AmazonECSTaskExecutionRolePolicy for the task",
    "Export Name exploreS3EcsTaskExecutionRoleArnExportName for the stack output",
]


@pytest.mark.parametrize("text", SECRET_CORPUS)
def test_secrets_are_refused(text: str) -> None:
    verdict = SecretScanner().scan(text)
    assert verdict.flagged
    assert verdict.recommended_action == SafetyAction.REFUSE
    assert verdict.findings  # at least one redacted descriptor
    # NFR-6: findings carry class + location only, never the raw value.
    for finding in verdict.findings:
        assert finding.kind
        assert "offset:" in finding.location or finding.location == "input"


@pytest.mark.parametrize("text", BENIGN_CORPUS)
def test_benign_input_is_allowed(text: str) -> None:
    verdict = SecretScanner().scan(text)
    assert not verdict.flagged
    assert verdict.recommended_action == SafetyAction.ALLOW
    assert verdict.findings == []


def test_scanner_never_returns_warn_under_q4b() -> None:
    # Q4=b: secret detection is refuse-or-allow only; warn is never produced.
    for text in SECRET_CORPUS + BENIGN_CORPUS:
        assert SecretScanner().scan(text).recommended_action != SafetyAction.WARN

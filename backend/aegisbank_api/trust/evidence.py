"""Layered evidence model for the trust layer.

Every fact returned to a human must carry its provenance: whether it is mock
bank data, a human approval, a policy decision, or an audit-chain attestation.
The frontend uses this to separate "simulated data" from "verified action".
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class EvidenceSource(StrEnum):
    MOCK_BANK = "mock_bank"
    HUMAN_CONFIRMATION = "human_confirmation"
    POLICY_ENGINE = "policy_engine"
    AUDIT_CHAIN = "audit_chain"


class VerificationKind(StrEnum):
    TOOL_RESULT = "tool_result"
    APPROVAL = "approval"
    POLICY_DECISION = "policy_decision"
    HASH_CHAIN = "hash_chain"


@dataclass(frozen=True, slots=True)
class Evidence:
    source: EvidenceSource
    verified: bool
    verification_kind: VerificationKind
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source.value,
            "verified": self.verified,
            "verification_kind": self.verification_kind.value,
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Evidence:
        return cls(
            source=EvidenceSource(str(value["source"])),
            verified=bool(value["verified"]),
            verification_kind=VerificationKind(str(value["verification_kind"])),
            detail=str(value.get("detail") or ""),
        )


def tool_result_evidence(verified: bool = True, detail: str = "") -> Evidence:
    return Evidence(
        source=EvidenceSource.MOCK_BANK,
        verified=verified,
        verification_kind=VerificationKind.TOOL_RESULT,
        detail=detail,
    )


def approval_evidence(verified: bool = True, detail: str = "") -> Evidence:
    return Evidence(
        source=EvidenceSource.HUMAN_CONFIRMATION,
        verified=verified,
        verification_kind=VerificationKind.APPROVAL,
        detail=detail,
    )


def policy_decision_evidence(verified: bool = True, detail: str = "") -> Evidence:
    return Evidence(
        source=EvidenceSource.POLICY_ENGINE,
        verified=verified,
        verification_kind=VerificationKind.POLICY_DECISION,
        detail=detail,
    )


def hash_chain_evidence(verified: bool = True, detail: str = "") -> Evidence:
    return Evidence(
        source=EvidenceSource.AUDIT_CHAIN,
        verified=verified,
        verification_kind=VerificationKind.HASH_CHAIN,
        detail=detail,
    )


def evidence_payload(*items: Evidence | None) -> list[dict[str, Any]]:
    """Serialize evidence items, dropping ``None`` and duplicate proofs."""
    payload: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in items:
        if item is None:
            continue
        data = item.as_dict()
        key = (data["source"], data["verification_kind"], data["detail"])
        if key in seen:
            continue
        seen.add(key)
        payload.append(data)
    return payload


def merge_evidence(*groups: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for group in groups:
        for item in group or []:
            key = (
                str(item.get("source")),
                str(item.get("verification_kind")),
                str(item.get("detail") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            payload.append(dict(item))
    return payload

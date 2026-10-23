"""Trust engineering package for AegisBank phase 1.

Modules:
- ``action_envelope``: ActionEnvelope/v1 one-shot plan/argument/risk binding.
- ``idempotency``: request idempotency keys with persisted first results.
- ``state_machine``: audited task lifecycle including UNKNOWN recovery.
- ``evidence``: provenance layers for mock data, approvals, and audit chain.
- ``readiness``: fail-closed readiness probes.
- ``circuit_breaker``: persisted consecutive-failure breaker skeleton.
"""

from .action_envelope import (
    ActionEnvelope,
    EnvelopeError,
    EnvelopeExpired,
    EnvelopeMismatch,
    EnvelopeService,
    NonceReused,
    arguments_hash,
    build_envelopes,
    canonical_hash,
)
from .circuit_breaker import CircuitBreaker
from .evidence import (
    Evidence,
    EvidenceSource,
    VerificationKind,
    approval_evidence,
    evidence_payload,
    hash_chain_evidence,
    merge_evidence,
    policy_decision_evidence,
    tool_result_evidence,
)
from .idempotency import (
    IdempotencyError,
    IdempotencyInProgress,
    IdempotencyKeyReused,
    IdempotencyStore,
)
from .readiness import NotReadyError, ReadinessService
from .state_machine import (
    ActionState,
    ExecutionOutcomeUnknown,
    IllegalTransition,
    StateMachine,
)

__all__ = [
    "ActionEnvelope",
    "ActionState",
    "CircuitBreaker",
    "EnvelopeError",
    "EnvelopeExpired",
    "EnvelopeMismatch",
    "EnvelopeService",
    "Evidence",
    "EvidenceSource",
    "ExecutionOutcomeUnknown",
    "IdempotencyError",
    "IdempotencyInProgress",
    "IdempotencyKeyReused",
    "IdempotencyStore",
    "IllegalTransition",
    "NonceReused",
    "NotReadyError",
    "ReadinessService",
    "StateMachine",
    "VerificationKind",
    "approval_evidence",
    "arguments_hash",
    "build_envelopes",
    "canonical_hash",
    "evidence_payload",
    "hash_chain_evidence",
    "merge_evidence",
    "policy_decision_evidence",
    "tool_result_evidence",
]

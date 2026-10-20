## Summary

Adds a design note for **Draft Plan Provenance**: an off-chain, versioned `DraftPlanV1` + `planHash` that binds the exact draft, parser decision and quote reviewed by the user to the resulting task evidence.

This PR is documentation only. It does not change contracts, policy, signing, or the native-ETH-only scope.

## Why

The current evidence chain verifies that a payment satisfied on-chain policy and has matching contract events. It does not let an auditor recompute the exact draft/parser/quote that the user reviewed from task evidence.

The proposal adds a small, additive binding:

- hash `message`, `purpose`, normalized transfer fields and `ParserInfo`;
- hash the preview quote and its policy/block context;
- return `planHash` from preview and require it at submit;
- recompute server-side and fail closed on mismatch;
- expose hashes in task/evidence with explicit off-chain limitations.

## Included

- Problem statement and explicit off-chain trust boundary.
- `DraftPlanV1` interface and domain-separated `keccak256` hashing rules.
- API and storage changes (`draftHash`, `quoteHash`, `planHash`).
- Security invariants and a tamper-focused test matrix.
- Phased rollout: off-chain hashes, then attestation/evidence bundle, then optional on-chain anchor in a new policy domain.

## Validation

- Documentation-only patch generated against `main` (`71930d6`).
- No contracts, secrets, API keys, raw messages or generated evidence added.
- Recommended follow-up implementation: `backend/src/plan.ts` + `backend/test/plan.test.ts` + additive fields in `packages/shared/src/index.ts`.

## Open questions

1. Expose `draftHash` at creation or only at preview?
2. Include parser `reason` in the digest? (recommended yes)
3. Include observed block hash/number in `quoteHash`? (recommended yes)
4. Add a CLI verifier now or later?
5. If anchored on-chain later, extend `requestHash` domains or add a separate field/event?

# Draft Plan Provenance (Design Note)

Status: proposal for review · Date: 2026-10-20
Related: `backend/src/parser.ts`, `backend/src/llm.ts`, `backend/src/service.ts`,
`packages/shared/src/index.ts`, `docs/ARCHITECTURE.md`, `docs/SECURITY.md`

## 中文评审摘要

这份 PR 只新增设计文档，不改代码、不改合约、不改变当前 native ETH 单动作范围。

要解决的问题：

> 原项目可以证明付款满足链上策略并有交易事件，但还不能证明这笔任务来自用户刚刚审阅的同一份 draft、parser 结果和 quote。

建议增加：

- 一个版本化对象 `DraftPlanV1`；
- `draftHash`、`quoteHash`、`planHash`；
- preview 返回 `planHash`；
- submit 必须携带并由服务端重算 `planHash`；
- task/evidence 暴露 provenance hashes；
- hash 不一致时 fail closed，不创建 task、不准备交易、不广播。

本次 PR 需要评审决定的内容：

1. 是否接受 `planHash` 这个 provenance 概念；
2. hash 覆盖字段是否合理，尤其是 parser reason 和 quote 观测区块；
3. submit 新增必填字段是否可接受，还是需要先做兼容期；
4. 第一阶段只做 off-chain provenance 是否足够；
5. 未来是否需要把 `planHash` 锚定到链上。

明确不改：

- Wallet、PolicyEngine、Oracle、签名、Owner 审批；
- 单动作 native ETH 范围；
- LLM draft-only 边界；
- 链上 `requestHash`、事件证据和现有 API 语义。

## English TL;DR

AegisAgent already binds the financial request to on-chain policy and transaction
evidence, but the exact draft the user reviewed is not cryptographically bound to
the resulting task. This note proposes a small, off-chain-first increment: a
canonical `DraftPlanV1`, a `planHash` returned by preview and required at submit,
and the same hashes exposed in task evidence. It does not change contracts, policy,
signing, or the single-action native-ETH scope in phase one.

## 0. 10 分钟评审路径

1. 先读"中文评审摘要"，确认问题、建议改动和需要决策的事项。
2. 看第 1 节"What this PR adds at a glance"，确认本 PR 的范围。
3. 看第 5 节 before/after 示例，判断用户体验和 API 变化是否合理。
4. 看第 7-8 节安全不变量和验收标准，确认是否存在未覆盖的篡改路径。
5. 在第 12 节按 Product / Backend / Contract 三个维度给出评审意见。
6. 如果认可方向，再讨论第 10 节的 PR B/C/D 拆分顺序。

本文件的建议是：先接受或修改协议，再进入实现；不建议把设计讨论和代码实现放在同一个 PR 里。

## 1. What this PR adds at a glance

| Original project today | This proposal adds |
|---|---|
| `Intent`, `Quote` and `Task` contain the needed fields, but provenance is spread across records | A versioned `DraftPlanV1` contract that names exactly what is being bound |
| Task evidence exposes recipient/amount/requestHash/parser separately | `draftHash`, `quoteHash` and `planHash` in task/evidence |
| Preview returns quote context, but no single confirmation fingerprint | Preview returns `planHash`; the user confirms that exact value |
| Submit checks revision and quote ID | Submit also requires `planHash` and recomputes it server-side |
| Off-chain draft/parser changes are not detectable from task evidence | Hash mismatch blocks task creation and broadcast |
| Parser fallback is informational | Parser kind/model/reason becomes part of the hashed provenance |
| No dedicated verification test vector | Golden vectors and tamper cases in `backend/test/plan.test.ts` |

No runtime code is changed by this PR. The table describes the target state that
the follow-up implementation PRs should deliver.

## 2. Scope and non-goals

### In scope

- Add a versioned, canonical draft/quote/parser provenance contract.
- Return a `planHash` at preview time.
- Require and recompute it at submit time.
- Expose provenance hashes in task and evidence responses.
- Add a deterministic test matrix for tampering and version drift.

### Out of scope

- No multi-action DAG, subscriptions, swaps, ERC-20s, cross-chain or bank-tool expansion.
- No change to the native-ETH-only action set.
- No claim that LLM reasoning is honest, complete or safe.
- No change to Wallet, PolicyEngine, oracle, signing or approval semantics.
- No attempt to prove the natural-language message itself; only its digest is bound.
- No replacement for `requestHash`, chain events or on-chain policy checks.

## 3. Current state and the gap

The current flow is deliberately narrow and safe:

1. `parseDraft()` / `parseDraftWithLlm()` produce a draft-only `Intent`.
2. `preview()` creates a `Quote` bound to `draftId`, `draftVersion`, `policyVersion`,
   quote expiry and deadline.
3. `submit()` checks `expectedRevision`, `quoteId`, quote expiry, and the
   recipient/amount equality between the quote and intent.
4. The Wallet binds the financial request with an on-chain `requestHash` covering
   agent, recipient, amount, USD cap, nonce, deadline and policy version.
5. Event/receipt evidence determines whether the payment executed, queued or was cancelled.

That is a strong chain for authorization and execution. It does not prove this
second statement:

> The payment was generated from the exact draft, parser decision and quote that
> the user reviewed.

Why not:

- `Intent.message`, `purpose` and `parser` are stored off-chain but are not
  covered by a deterministic digest.
- `Task` copies `parser` into its record, but `publicTask()` and `evidence()` expose
  it without a value that can be recomputed from the original draft and quote.
- A database writer can alter a draft's message/purpose/parser metadata after the
  fact without changing the on-chain `requestHash`, because those fields are not
  part of the on-chain request.
- An auditor cannot compare the displayed preview with the task using a single verifiable identifier.

This is not a claim that the current flow is broken. It is a gap between two
different statements:

> The payment satisfied policy and has matching chain evidence.

and

> The payment was generated from the exact draft, parser decision and quote that
> the user reviewed.

## 4. Relationship to the AegisBank reference manual

The PDF reference manual is about a bank agent, so its product scope is not copied
into AegisAgent. We only borrow its trust principles.

| Reference-manual principle | Current AegisAgent equivalent | Proposed increment |
|---|---|---|
| Identity must be unique, verifiable, callable and non-repudiable | Owner wallet challenge; executor key; on-chain actor addresses | Bind the reviewed draft/parser/quote to a recomputable plan hash |
| The gateway is the only path to data/tools | Wallet + PolicyEngine + preview/submit checks | Recompute provenance at submit; fail closed on mismatch |
| Tool calls should be standardized | Single native ETH action with one strict draft schema | Versioned `DraftPlanV1` contract |
| Audit must be part of execution, not a side effect | `requestHash`, contract events, task evidence | Add pre-execution plan hashes to task evidence |
| Green/yellow/red interaction model | Auto execute / Owner approval / reject | Keep unchanged; provenance does not alter policy decisions |
| Signed, non-repudiable operation record | Owner transaction + contract event | Add a verifiable draft-to-task link without claiming on-chain proof |
| Do not use P2P or store full financial data locally | Centralized wallet, minimal SQLite state | Off-chain hashes only; no raw payload in evidence |

The PDF also says the audit record should answer: when, original instruction,
DAG path, tool arguments, result and confirmation state. AegisAgent already has the
financial request and chain event. The missing part is the original instruction and
draft/quote context. This proposal adds hashes for exactly that.

## 5. Before and after: one concrete example

User request:

```text
Send 0.001 ETH to 0x1111111111111111111111111111111111111111 for hosting.
```

### Today

The task/evidence proves:

- recipient and amount;
- requestHash and contract event;
- parser kind/model;
- policy version and transaction evidence.

But these are not bound together by a digest over the reviewed draft and quote.
If someone edits `message`, `purpose`, `parser.reason` or the draft revision in
SQLite, the on-chain requestHash does not change.

### After

The preview returns:

```json
{
  "quoteId": "a3f...",
  "draftVersion": 1,
  "draftHash": "0x...",
  "quoteHash": "0x...",
  "planHash": "0x..."
}
```

The submit body becomes:

```json
{
  "expectedRevision": 1,
  "quoteId": "a3f...",
  "planHash": "0x..."
}
```

The task/evidence contains the same hashes and a provenance block. If the draft,
parser reason, quote policy version or observed block context changes, the
server's recomputation differs and the submit is rejected with
`409 PLAN_HASH_MISMATCH`.

## 6. Proposed design

### 6.1 Versioned canonical object

Introduce a small domain-separated contract in shared types:

```ts
export interface DraftPlanV1 {
  schemaVersion: 'aegis.draft-plan.v1';
  draftId: string;
  revision: number;
  action: 'transfer';
  messageHash: Hex;
  purposeHash: Hex;
  recipient: Hex;
  amountWei: string;
  parser: ParserInfo;
  quote: {
    quoteId: string;
    draftVersion: number;
    policyVersion: string;
    quoteExpiresAtSeconds: number;
    requestDeadlineSeconds: number;
    observedBlockNumber: string;
    observedBlockHash: Hex;
  };
}
```

Hashing rules:

```text
canonicalJson = JSON with sorted keys, stable string escaping, no undefined fields
draftHash    = keccak256(utf8("aegis.draft-plan.v1\ndraft\n" + canonicalJson(draft)))
quoteHash    = keccak256(utf8("aegis.draft-plan.v1\nquote\n" + canonicalJson(quote)))
planHash     = keccak256(utf8("aegis.draft-plan.v1\nplan\n" + draftHash + quoteHash))
```

`messageHash` and `purposeHash` are recomputed from the raw fields before the
draft digest is calculated. `keccak256` is used instead of SHA-256 so the same
construction can later become an on-chain `bytes32` commitment without a redesign.
The version string is part of the domain separator and must change if the field
set changes.

### 6.2 Lifecycle

```text
create/patch intent
  -> compute draftHash from canonical Intent
  -> preview(quote)
  -> compute quoteHash + planHash
  -> return planHash to the client
  -> user reviews and confirms the exact planHash
  -> submit(expectedRevision, quoteId, planHash)
  -> server recomputes all hashes from stored entities
  -> mismatch => 409 PLAN_HASH_MISMATCH, no task created
  -> task stores draftHash, quoteHash, planHash
  -> task/evidence exposes hashes and recomputation instructions
```

The client-provided `planHash` is a confirmation binding, never an authority.
The server must recompute it from the stored intent and quote.

### 6.3 API changes

Additive fields only:

| Endpoint | Change |
|---|---|
| `GET /api/v1/intents/:id` | include `draftHash` |
| `POST /api/v1/intents` / `PATCH /api/v1/intents/:id` | include `draftHash` |
| `POST /api/v1/intents/:id/preview` | return `draftHash`, `quoteHash`, `planHash` |
| `POST /api/v1/intents/:id/submit` | require `planHash` |
| `GET /api/v1/tasks/:id` | expose `draftHash`, `quoteHash`, `planHash` |
| `GET /api/v1/tasks/:id/evidence` | add `provenance` object |
| `GET /api/v1/config` | advertise `planProvenance: "aegis.draft-plan.v1"` |

Example evidence addition:

```json
{
  "provenance": {
    "schemaVersion": "aegis.draft-plan.v1",
    "draftHash": "0x...",
    "quoteHash": "0x...",
    "planHash": "0x...",
    "hashAlgorithm": "keccak256",
    "recompute": "docs/DRAFT-PLAN-PROVENANCE.md"
  }
}
```

A missing `planHash` on submit is a 400-level request error, not silently defaulted.
During rollout, the backend can advertise the field in `/config` before the UI
starts sending it.

### 6.4 Code ownership map

| File | Responsibility |
|---|---|
| `packages/shared/src/index.ts` | `DraftPlanV1`, `PlanProvenance`, domain constants |
| `backend/src/plan.ts` (new) | canonical JSON, domain-separated keccak256 helpers |
| `backend/src/service.ts` | compute/recompute/validate hashes; persist on task |
| `backend/src/server.ts` | strict Zod schema for `planHash` on submit |
| `frontend/src/main.ts` | show short hash with copy action and plain-language explanation |
| `backend/test/plan.test.ts` (new) | golden vectors and tamper cases |
| `e2e` tests | assert preview hash is retained through confirm/submit/refresh |

The hash helpers must be pure and testable without RPC, LLM or SQLite.

### 6.5 Suggested implementation skeleton

```ts
// backend/src/plan.ts
export function canonicalJson(value: unknown): string { /* sorted keys, stable types */ }

export function hashDomain(domain: string, value: unknown): Hex {
  return keccak256(toUtf8Bytes(`aegis.draft-plan.v1\n${domain}\n${canonicalJson(value)}`));
}

export function computeDraftHash(intent: Intent): Hex { /* messageHash + purposeHash + fields */ }
export function computeQuoteHash(quote: Quote): Hex { /* quote + policy/block context */ }
export function computePlanHash(draftHash: Hex, quoteHash: Hex): Hex { /* domain-separated */ }
```

The implementation PR should include at least one golden vector so another
process or language can reproduce the digest.

## 7. Security invariants

1. `planHash` is recomputed server-side from persisted draft and quote data;
   `messageHash` and `purposeHash` are recomputed from the raw fields before hashing.
2. A draft edit invalidates the previous preview, quote and plan hash.
3. Parser metadata (`kind`, `model`, `configuredModel`, `fallback`, `reason`) is
   covered by the digest, so a model fallback cannot be silently rewritten later.
4. A quote from another draft, revision or policy version cannot produce the same
   `planHash` in practice, because all are included in the canonical object.
5. `planHash` is not an authorization token and cannot bypass policy, approval,
   nonce, deadline or on-chain checks.
6. No raw message, purpose or API key is placed in task evidence or logs by this change.
7. Mismatch is fail-closed: no task, no transaction preparation, no broadcast.

## 8. Acceptance criteria

- [ ] Same intent + same quote produces the same `planHash` across processes.
- [ ] Changing any of message, purpose, recipient, amount, revision, parser model,
      parser reason, quote id, policy version or quote expiry changes the hash.
- [ ] Preview returns `planHash`; submit without it is rejected.
- [ ] Submit with a valid `planHash` succeeds and the task/evidence returns the same value.
- [ ] Submit after a draft edit, or with a hash from another quote, returns
      `409 PLAN_HASH_MISMATCH` and creates no task.
- [ ] Replaying the same submit with the same idempotency key returns the original
      task and does not create a second payment.
- [ ] Existing flow, typecheck, build, backend tests and E2E tests remain green.
- [ ] Evidence includes `provenance` hashes and an explicit note that this is
      off-chain provenance, not on-chain proof.
- [ ] The UI explains the hash as "confirmation binding, not execution proof".

## 9. Test matrix

| Case | Expected |
|---|---|
| Create draft -> preview -> submit with returned planHash | 202, same hash in task |
| Edit draft after preview, then submit old planHash | 409 `PLAN_HASH_MISMATCH` |
| Reuse planHash from another draft/quote | 409 `PLAN_HASH_MISMATCH` |
| Change parser fallback reason in stored record | recomputed hash differs; mismatch |
| Change policyVersion in quote | mismatch |
| Missing planHash | 400 `INVALID_REQUEST` |
| Same idempotency key + same body | original task returned |
| Same idempotency key + different planHash | 409 `IDEMPOTENCY_CONFLICT` |
| Evidence recomputation | `draftHash`, `quoteHash`, `planHash` match |
| Tampered message/purpose stored off-chain | digest mismatch; task not accepted |
| Existing mock chain flow | unchanged behavior |

## 10. Implementation plan for review

To keep the implementation reviewable, split it after this design PR:

1. **PR A (this document):** agree on the contract and scope.
2. **PR B:** add `backend/src/plan.ts`, `backend/test/plan.test.ts`, and shared types.
   No service/API wiring yet; this is a pure hash module with golden vectors.
3. **PR C:** wire preview/submit/task/evidence, add API compatibility and UI copy.
4. **PR D (optional):** add a CLI verifier and put `planHash` into the evidence
   bundle or attestation data URI.
5. **PR E (only if needed):** on-chain anchor in a new policy domain version.

This sequence keeps the first change small and lets reviewers discuss the hash
contract without mixing in contract or deployment risk.

## 11. Risks and honest limits

| Risk | Mitigation |
|---|---|
| Off-chain hash can be recomputed by a compromised backend | state the trust boundary; plan an on-chain anchor if required |
| Hash canonicalization diverges across Node versions | pure canonical JSON implementation + golden vector tests |
| Schema changes silently break clients | additive API fields; version domain string |
| Users mistake planHash for payment proof | UI copy: "confirmation binding, not execution proof" |
| Extra hashes slow the demo | hashes are local CPU-only; no chain call |
| Raw message contains sensitive data | export only hashes by default; raw data stays in existing local DB |

Phase 1 makes accidental drift and off-chain record substitution detectable. It
does not protect against a fully compromised backend or database administrator.
That is why the design keeps the claim honest and leaves on-chain anchoring as an
explicit later decision.

## 12. Review questions

### Product / UX

1. Should the UI show `planHash` to every user, or only in advanced evidence?
2. Should the label say "review fingerprint" or "plan hash"?
3. Is the extra confirmation payload worth the UX cost for low-risk automatic
   payments? The current proposal applies the hash to the preview/submit boundary,
   not to the automatic execution decision itself.

### Backend / API

4. Should `draftHash` be exposed on creation, or only once preview is ready?
5. Should submit require `planHash` immediately, or should there be a one-release
   compatibility window where missing hashes are logged and rejected later?
6. Should `quoteHash` include observed block hash/number? Recommendation: yes.
7. Should parser `reason` be in the hash? Recommendation: yes; it is part of the
   provenance record and is already stored in `ParserInfo`.

### Contract / security

8. Is off-chain provenance sufficient for the current phase?
9. If we later anchor on-chain, should `planHash` become part of `requestHash` or
   a separate field/event? A separate field is clearer but costs storage.
10. Do we want a CLI verifier in Phase 1, or only documented recomputation?

## 13. Why this fits the current repo

- It preserves the single-action native-ETH scope.
- It extends the existing `Intent`, `Quote`, `Task` and evidence model rather than
  introducing a parallel agent framework.
- It strengthens the project's central claim - executable, verifiable, traceable -
  without pretending that the LLM or off-chain database is trustworthy.
- It creates a clean interface for a later on-chain commitment while keeping the
  first PR small, testable and reviewable.

The smallest honest version is one pure hash module, one submit field, one task
provenance object and a tamper-focused test file.

## Appendix A. Development discussion checklist

Use this checklist when reviewing the proposal:

- [ ] Is the problem statement accepted?
- [ ] Is the single-action scope preserved?
- [ ] Are the hashed fields sufficient and not excessive?
- [ ] Is the failure mode fail-closed and observable?
- [ ] Are existing API clients kept compatible?
- [ ] Is the evidence claim clearly limited to off-chain provenance?
- [ ] Is there a small first implementation PR that can be tested without a chain?
- [ ] Is on-chain anchoring explicitly deferred rather than implied?

## Appendix B. Non-claims

This design does not claim:

- that the LLM produced a correct or honest plan;
- that the raw natural language is proven;
- that the off-chain database is tamper-proof;
- that `planHash` replaces `requestHash` or contract events;
- that policy decisions or approvals are changed;
- that multi-action planning is part of this project.

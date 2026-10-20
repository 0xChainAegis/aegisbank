# Upstream PR bundle — AegisAgent

This directory contains a review-ready design-note patch for:

<https://github.com/0xChainAegis/aegis-agent>

## Files

| File | Purpose |
|---|---|
| `docs/DRAFT-PLAN-PROVENANCE.md` | The file proposed for the upstream repository |
| `DRAFT-PLAN-PROVENANCE.patch` | `git apply`-ready patch adding the file |
| `PR_BODY.md` | Suggested pull-request title/body |

## Apply locally

```bash
git clone https://github.com/0xChainAegis/aegis-agent.git
cd aegis-agent
git checkout -b docs/draft-plan-provenance
git apply /path/to/DRAFT-PLAN-PROVENANCE.patch
git add docs/DRAFT-PLAN-PROVENANCE.md
git commit -m "docs(plan): specify draft plan provenance binding"
git push -u origin docs/draft-plan-provenance
```

Then open a PR against `main` using `PR_BODY.md` as the description.

## Scope

Documentation only. The proposal stays within the project's current single-action native-ETH scope and explicitly separates off-chain provenance from on-chain proof.

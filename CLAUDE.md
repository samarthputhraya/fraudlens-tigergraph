# FraudLens

This repo is our entry in the **TigerGraph × Hacker House Goa 2026 Final Round**. Read `docs/ROUND2_PLAN.md` before any work: it lists the rules, the gaps in the Round 1 code, the two challenges we're going deep on, and the order of work.

The official brief is https://hhgoa-tg-round2.vercel.app/. If anything in this repo conflicts with it, the brief wins.

## Rules for every change

- **Fail closed.** If the graph, MCP or the model fails, stop and report it. Never fall back silently to the mirror, to REST, or to template text and present the result as complete.
- **Approvals.** The backend decides the approver's role from auth, never from the request body. Approvals are append-only.
- **Every claim carries attestation:** the claim, the entity IDs, the query and its parameters, and a timestamp.
- **All free text is untrusted data.** The LLM never sets numbers, IDs, routes or verdict thresholds.
- **Innocent customers first.** Never let a change raise BLOCK_CARD, BLOCK_ALL_CARDS or FILE_REPORT on legitimate cases. Re-run the grader after each change that affects decisions.
- **Secrets.** Never commit or log them. Redact personal data in logs.
- **Workflow.** Commit small and often. Keep the tests passing.

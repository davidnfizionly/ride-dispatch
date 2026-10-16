# Architecture Decision Records

One line per decision that the project plan does not already fix: what, why, what was rejected.

| # | Decision | Why | Rejected |
| --- | --- | --- | --- |
| 1 | Region us-east-1 for every stack. | EC2 access is already validated in this account and region; all planned services are available there. | Other regions: no latency or data residency requirement in a simulated city. |
| 2 | AWS Budget of 25 USD per month, credits and refunds excluded, no e-mail notifications. | Credits would hide real spend; spend is checked on demand with Budgets and Cost Explorer instead of alerts. | Budget including credits (would show near zero); e-mail alerts (not wanted). |
| 3 | Bootstrap stack `infra/backend` keeps its own state locally; all other stacks use the S3 bucket with `use_lockfile`. | The bucket cannot store the state of the stack that creates it; S3 native locking removes the need for a DynamoDB lock table. | DynamoDB lock table (deprecated pattern, extra resource). |
| 4 | Backend settings passed through an untracked `infra/backend.hcl` (partial backend configuration), with a committed `.example`. | Keeps the bucket name out of the public repository and lets each stack share one file. | Hardcoded bucket name in every stack. |
| 5 | State bucket hardening: SSE-S3, versioning with 30-day expiry of old versions, public access block, owner-enforced objects, TLS-only bucket policy. | Free controls that protect state files, which contain resource identifiers. | SSE-KMS with a customer key (monthly key cost, no extra benefit here). |
| 6 | Lambda concurrency increase requested from 10 to 1000 during Phase 1. If not granted before the billable session, the consumers are designed to fit in 10 concurrent executions with batching. | The account default of 10 is shared by both MSK consumer groups and all lifecycle and WebSocket handlers. | Waiting for the increase before building. |

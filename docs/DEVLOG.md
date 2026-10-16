# Development Log

Real problems, in the order they occurred: what happened, root cause, fix.

## Lambda concurrency quota at 10

- What happened: the preflight check showed an account limit of 10 concurrent Lambda executions in us-east-1.
- Root cause: the default limit on this account is low. The design runs two MSK consumer groups plus the lifecycle and WebSocket handlers, all sharing that pool.
- Fix: an increase to 1000 was requested through Service Quotas at the start of the build, status PENDING. If it is not granted before the billable session, the design is adapted to fit in 10 concurrent executions (larger batches per invocation, capped concurrency per function). The outcome is recorded here and in the README.

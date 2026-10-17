#!/usr/bin/env bash
# Consumer independence test: the archiver event source mapping is disabled
# for a few minutes while both consumer groups' lag is sampled every 10 s.
# Expected: archiver lag grows, matching lag stays flat; after re-enabling,
# the archiver catches up from its committed offset.
# Usage: scripts/independence_test.sh [paused_seconds]
set -euo pipefail

PAUSE="${1:-180}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UUID=$(cd "$ROOT/infra/app" && terraform output -json esm_uuids | jq -r .archiver)
TOTAL=$((60 + PAUSE + 150))

state() {
  aws lambda get-event-source-mapping --region us-east-1 --uuid "$UUID" --query State --output text
}
wait_state() {
  until [ "$(state)" = "$1" ]; do sleep 5; done
}

echo "date_utc: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "plan: 60 s baseline, archiver ESM disabled for ${PAUSE} s, then re-enabled and observed"
kubectl -n ride-dispatch exec deploy/simulator -- python scripts/consumer_lag.py "$TOTAL" 10 &
LAG_PID=$!
sleep 60

echo "$(date -u +%H:%M:%S)  disabling archiver event source mapping"
aws lambda update-event-source-mapping --region us-east-1 --uuid "$UUID" --no-enabled > /dev/null
wait_state Disabled
echo "$(date -u +%H:%M:%S)  archiver mapping state: Disabled"
sleep "$PAUSE"

echo "$(date -u +%H:%M:%S)  re-enabling archiver event source mapping"
aws lambda update-event-source-mapping --region us-east-1 --uuid "$UUID" --enabled > /dev/null
wait_state Enabled
echo "$(date -u +%H:%M:%S)  archiver mapping state: Enabled"
wait "$LAG_PID"

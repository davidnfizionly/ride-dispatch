#!/usr/bin/env bash
# Runs a SQL file in the ride-dispatch Athena workgroup and prints the result
# table with the engine statistics.
# Usage: scripts/run_athena.sh scripts/athena_demand.sql
set -euo pipefail

SQL="$(cat "$1")"
QID=$(aws athena start-query-execution --region us-east-1 --work-group ride-dispatch \
  --query-string "$SQL" --query QueryExecutionId --output text)

while true; do
  STATE=$(aws athena get-query-execution --region us-east-1 --query-execution-id "$QID" \
    --query QueryExecution.Status.State --output text)
  case "$STATE" in
    SUCCEEDED) break ;;
    FAILED | CANCELLED)
      aws athena get-query-execution --region us-east-1 --query-execution-id "$QID" \
        --query QueryExecution.Status.StateChangeReason --output text
      exit 1 ;;
  esac
  sleep 1
done

echo "date_utc: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "query:"
sed 's/^/  /' "$1"
aws athena get-query-execution --region us-east-1 --query-execution-id "$QID" \
  --query 'QueryExecution.Statistics.{engine_ms:EngineExecutionTimeInMillis,scanned_bytes:DataScannedInBytes}' \
  --output text | awk '{print "engine_ms: " $1 "  data_scanned_bytes: " $2}'
echo "result:"
aws athena get-query-results --region us-east-1 --query-execution-id "$QID" \
  --query 'ResultSet.Rows[].Data[].VarCharValue' --output json \
  | python3 -c 'import json,sys; v=json.load(sys.stdin); [print("  " + " | ".join(v[i:i+5])) for i in range(0, len(v), 5)]'

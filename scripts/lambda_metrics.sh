#!/usr/bin/env bash
# Per-function Lambda metrics from CloudWatch over a time window, plus the
# account-level maximum concurrent executions (relevant with a limit of 10).
# Usage: scripts/lambda_metrics.sh <start_iso_utc> <end_iso_utc>
set -euo pipefail

START="$1"
END="$2"
FUNCTIONS="matching-positions matching-requests archiver-positions archiver-trips lifecycle-update notifier ws-connect ws-disconnect ws-request"

stat() {  # function metric statistic
  aws cloudwatch get-metric-statistics --region us-east-1 --namespace AWS/Lambda --metric-name "$2" \
    --dimensions Name=FunctionName,Value="ride-dispatch-$1" --start-time "$START" --end-time "$END" \
    --period 86400 --statistics "$3" --query "Datapoints[0].$3" --output text
}

p99() {
  aws cloudwatch get-metric-statistics --region us-east-1 --namespace AWS/Lambda --metric-name Duration \
    --dimensions Name=FunctionName,Value="ride-dispatch-$1" --start-time "$START" --end-time "$END" \
    --period 86400 --extended-statistics p50 p99 \
    --query 'Datapoints[0].ExtendedStatistics.[p50,p99]' --output text
}

echo "window_utc: $START to $END"
echo "measures: CloudWatch AWS/Lambda metrics per function (arm64, python3.13); duration in ms"
printf '%-20s %11s %7s %9s %9s %9s %9s\n' function invocations errors throttles avg_ms p50_ms p99_ms
for f in $FUNCTIONS; do
  read -r P50 P99 <<< "$(p99 "$f")"
  printf '%-20s %11s %7s %9s %9.1f %9.1f %9.1f\n' "$f" \
    "$(stat "$f" Invocations Sum)" "$(stat "$f" Errors Sum)" "$(stat "$f" Throttles Sum)" \
    "$(stat "$f" Duration Average)" "$P50" "$P99"
done
echo "account max ConcurrentExecutions (1-minute periods): $(aws cloudwatch get-metric-statistics --region us-east-1 \
  --namespace AWS/Lambda --metric-name ConcurrentExecutions --start-time "$START" --end-time "$END" \
  --period 60 --statistics Maximum --query 'max(Datapoints[].Maximum)' --output text)"
echo "account concurrency limit: $(aws lambda get-account-settings --region us-east-1 --query AccountLimit.ConcurrentExecutions --output text)"

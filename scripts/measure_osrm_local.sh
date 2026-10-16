#!/usr/bin/env bash
# Measures osrm-routed on the local Docker engine: time from container start to
# the first successful route, and resident memory (docker stats) at idle and
# after a burst of route requests.
# Usage: scripts/measure_osrm_local.sh <data_dir>
set -euo pipefail

DATA_DIR="$(cd "$1" && pwd)"
IMAGE="ghcr.io/project-osrm/osrm-backend:v6.0.0"
NAME="osrm-measure"
PORT=5055
# Nairobi CBD to Westlands
ROUTE="36.8172,-1.2864;36.8108,-1.2676"

docker rm -f "$NAME" > /dev/null 2>&1 || true

echo "date_utc: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "image: $IMAGE"
echo "graph files size: $(du -ch "$DATA_DIR"/nairobi.osrm* | tail -1 | cut -f1)"
echo "host: Docker Desktop, $(docker info --format '{{.NCPU}} CPUs, {{.MemTotal}} bytes memory')"

start=$(date +%s.%N)
docker run -d --name "$NAME" -p "$PORT:5000" -v "$DATA_DIR:/data:ro" "$IMAGE" \
  osrm-routed --algorithm mld /data/nairobi.osrm > /dev/null
until curl -sf "http://localhost:$PORT/route/v1/driving/$ROUTE?overview=false" > /dev/null; do
  sleep 0.1
done
end=$(date +%s.%N)
printf 'startup_to_first_route_s: %.2f\n' "$(echo "$end - $start" | bc)"

sleep 3
echo "memory_idle: $(docker stats --no-stream --format '{{.MemUsage}}' "$NAME")"

# 500 sequential random routes inside the city
burst_start=$(date +%s.%N)
for i in $(seq 1 500); do
  a=$(awk -v s="$i" 'BEGIN{srand(s);printf "%.5f,%.5f;%.5f,%.5f",36.75+rand()*0.15,-1.33+rand()*0.10,36.75+rand()*0.15,-1.33+rand()*0.10}')
  curl -sf "http://localhost:$PORT/route/v1/driving/$a?overview=full&geometries=geojson" > /dev/null
done
burst_end=$(date +%s.%N)
printf 'burst_500_routes_total_s: %.2f (sequential curl, includes curl process start)\n' "$(echo "$burst_end - $burst_start" | bc)"
echo "memory_after_burst: $(docker stats --no-stream --format '{{.MemUsage}}' "$NAME")"

echo "sample_route CBD to Westlands:"
curl -s "http://localhost:$PORT/route/v1/driving/$ROUTE?overview=false" \
  | jq -r '.routes[0] | "  distance_m: \(.distance|round)  duration_s: \(.duration|round)"'

docker rm -f "$NAME" > /dev/null

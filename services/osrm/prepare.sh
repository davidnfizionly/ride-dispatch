#!/usr/bin/env bash
# Builds the Nairobi routing graph from the Geofabrik Kenya extract.
# Usage: services/osrm/prepare.sh <data_dir>
# Expects <data_dir>/kenya-latest.osm.pbf. Writes nairobi.osm.pbf and nairobi.osrm.*
# into <data_dir> and prints the wall time of each step.
set -euo pipefail

DATA_DIR="$(cd "$1" && pwd)"
OSRM_IMAGE="ghcr.io/project-osrm/osrm-backend:v6.0.0"
OSMIUM_IMAGE="ride-dispatch/osmium:local"
# Nairobi county plus a margin: west,south,east,north
BBOX="36.60,-1.50,37.15,-1.10"
HERE="$(cd "$(dirname "$0")" && pwd)"

step() {
  local name="$1"; shift
  local start end
  start=$(date +%s.%N)
  "$@"
  end=$(date +%s.%N)
  printf 'STEP %-10s %6.1f s\n' "$name" "$(echo "$end - $start" | bc)"
}

docker build -q -t "$OSMIUM_IMAGE" -f "$HERE/osmium.Dockerfile" "$HERE" > /dev/null

step clip docker run --rm -v "$DATA_DIR:/data" "$OSMIUM_IMAGE" \
  extract --bbox "$BBOX" --strategy complete_ways --overwrite \
  -o /data/nairobi.osm.pbf /data/kenya-latest.osm.pbf

step extract docker run --rm -v "$DATA_DIR:/data" "$OSRM_IMAGE" \
  osrm-extract -p /opt/car.lua /data/nairobi.osm.pbf

step partition docker run --rm -v "$DATA_DIR:/data" "$OSRM_IMAGE" \
  osrm-partition /data/nairobi.osrm

step customize docker run --rm -v "$DATA_DIR:/data" "$OSRM_IMAGE" \
  osrm-customize /data/nairobi.osrm

# The containers write as root with owner-only modes; make the graph readable
# so the image build context can include it.
docker run --rm -v "$DATA_DIR:/data" "$OSRM_IMAGE" sh -c 'chmod 644 /data/nairobi.osrm.*'

ls -l "$DATA_DIR"/nairobi.osm.pbf
du -ch "$DATA_DIR"/nairobi.osrm* | tail -1

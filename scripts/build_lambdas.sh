#!/usr/bin/env bash
# Builds the arm64 Lambda packages into dist/lambda/<package>.zip.
# Native dependencies (h3) are fetched as manylinux2014_aarch64 wheels for
# CPython 3.13, so the zips run on Graviton without compiling anything.
# Runs inside the dev image (python:3.13-slim) to avoid touching the host Python.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IMAGE="ride-dispatch/dev:local"

docker run --rm -v "$ROOT:/w" -w /w --user "$(id -u):$(id -g)" -e HOME=/tmp "$IMAGE" bash -euo pipefail -c '
OUT=dist/lambda
rm -rf build/lambda "$OUT"
mkdir -p "$OUT"

build() {
  local name="$1"; shift
  local dir="build/lambda/$name"
  mkdir -p "$dir"
  if [ "$#" -gt 0 ]; then
    pip install --quiet --no-cache-dir --target "$dir" \
      --platform manylinux2014_aarch64 --implementation cp --python-version 3.13 \
      --only-binary=:all: "$@"
  fi
  cp -r services/shared/shared "$dir/"
  cp -r "services/$name/$name" "$dir/"
  find "$dir" -name "__pycache__" -type d -prune -exec rm -rf {} +
  (cd "$dir" && python -c "
import os, zipfile
with zipfile.ZipFile(\"../../../$OUT/$name.zip\", \"w\", zipfile.ZIP_DEFLATED) as z:
    for root, _, files in sorted(os.walk(\".\")):
        for f in sorted(files):
            p = os.path.join(root, f)
            info = zipfile.ZipInfo(p[2:], date_time=(2026, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, open(p, \"rb\").read())
")
}

# boto3 and botocore come from the Lambda runtime; the MSK signer is installed
# without dependencies so they are not duplicated in the package.
build matching h3==4.5.0 redis==8.1.0 kafka-python-ng==2.2.3
pip install --quiet --no-cache-dir --no-deps --target build/lambda/matching aws-msk-iam-sasl-signer-python==1.0.2
rm -f "$OUT/matching.zip"
build matching
build lifecycle
build archiver
ls -l "$OUT"
'

# Check that the h3 extension in the matching package is an aarch64 binary.
unzip -l "$ROOT/dist/lambda/matching.zip" | grep -E "h3/.*\.so" | head -3

#!/usr/bin/env bash
# Pushes the arm64 images to ECR and deploys OSRM and the simulator to EKS.
# Endpoints and the WebSocket token are read from Terraform outputs and stored
# in the cluster only (ConfigMap and Secret), never written to the repository.
# Usage: scripts/deploy_k8s.sh <image_tag>
set -euo pipefail

TAG="$1"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REGION=us-east-1
NS=ride-dispatch

out() { (cd "$ROOT/infra/$1" && terraform output -raw "$2"); }

CLUSTER=$(out cluster cluster_name)
OSRM_REPO=$(out cluster ecr_osrm)
SIM_REPO=$(out cluster ecr_simulator)

aws eks update-kubeconfig --region "$REGION" --name "$CLUSTER" > /dev/null
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "${OSRM_REPO%%/*}" > /dev/null

docker tag "ride-dispatch/osrm:$TAG" "$OSRM_REPO:$TAG"
docker tag "ride-dispatch/simulator:$TAG" "$SIM_REPO:$TAG"
docker push --quiet "$OSRM_REPO:$TAG"
docker push --quiet "$SIM_REPO:$TAG"

export OSRM_IMAGE="$OSRM_REPO:$TAG" SIM_IMAGE="$SIM_REPO:$TAG"
envsubst '${OSRM_IMAGE}' < "$ROOT/services/osrm/k8s.yaml" | kubectl apply -f -

kubectl -n "$NS" create configmap sim-config \
  --from-literal=KAFKA_BOOTSTRAP="$(out data msk_bootstrap_iam)" \
  --from-literal=KAFKA_IAM_REGION="$REGION" \
  --from-literal=AWS_REGION="$REGION" \
  --from-literal=EVENT_BUS_NAME=ride-dispatch \
  --from-literal=REDIS_HOST="$(out data redis_host)" \
  --from-literal=REDIS_SSL=1 \
  --dry-run=client -o yaml | kubectl apply -f -

# The WebSocket URL and token exist only after the app stack is applied.
if WS_URL=$(out app ws_url 2> /dev/null) && WS_TOKEN=$(out app connect_token 2> /dev/null); then
  kubectl -n "$NS" create secret generic ws-client \
    --from-literal=WS_URL="$WS_URL" --from-literal=WS_TOKEN="$WS_TOKEN" \
    --dry-run=client -o yaml | kubectl apply -f -
fi

envsubst '${SIM_IMAGE}' < "$ROOT/services/simulator/k8s.yaml" | kubectl apply -f -
kubectl -n "$NS" rollout status deploy/osrm --timeout=300s
kubectl -n "$NS" rollout status deploy/simulator --timeout=300s
kubectl -n "$NS" get pods -o wide

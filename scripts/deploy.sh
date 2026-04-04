#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${1:?Usage: deploy.sh <namespace> <image-tag>}"
IMAGE_TAG="${2:?Usage: deploy.sh <namespace> <image-tag>}"

echo "Deploying $IMAGE_TAG to $NAMESPACE"
kubectl set image deployment/syndicateclaw app="$IMAGE_TAG" -n "$NAMESPACE"
kubectl rollout status deployment/syndicateclaw -n "$NAMESPACE" --timeout=300s
echo "Deployment complete"

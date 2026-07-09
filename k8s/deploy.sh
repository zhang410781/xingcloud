#!/bin/bash
set -euo pipefail

REGISTRY_IMAGE=${REGISTRY_IMAGE:-registry.cn-hangzhou.aliyuncs.com/xinghaik8s/ops-agent}
TAG=${TAG:-a1.03}
IMAGE="${REGISTRY_IMAGE}:${TAG}"
NAMESPACE=${NAMESPACE:-xing-cloud}
RESET_DATA=${RESET_DATA:-0}
SKIP_BUILD=${SKIP_BUILD:-0}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
RENDERED_DIR="$(mktemp -d)"

cleanup() {
  rm -rf "${RENDERED_DIR}"
}
trap cleanup EXIT

cd "${SCRIPT_DIR}"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "ERROR: required command not found: $1" >&2
    exit 1
  fi
}

require_cmd kubectl
require_cmd docker

render_manifest() {
  local source_file="$1"
  local target_file="${RENDERED_DIR}/$(basename "${source_file}")"
  sed "s#image: .*ops-agent:.*#image: ${IMAGE}#g" "${source_file}" > "${target_file}"
  echo "${target_file}"
}

if [ "${SKIP_BUILD}" = "1" ]; then
  echo "==> Skipping image build and push: ${IMAGE}"
else
  echo "==> Building image: ${IMAGE}"
  docker build -t "${IMAGE}" "${ROOT_DIR}"

  echo "==> Pushing image: ${IMAGE}"
  docker push "${IMAGE}"
fi

if [ "${RESET_DATA}" = "1" ]; then
  echo "==> Resetting namespace and persistent data: ${NAMESPACE}"
  kubectl delete namespace "${NAMESPACE}" --ignore-not-found
  if kubectl get namespace "${NAMESPACE}" >/dev/null 2>&1; then
    kubectl wait --for=delete namespace/"${NAMESPACE}" --timeout=300s
  fi
fi

echo "==> Applying base manifests"
kubectl apply -f 00-namespace.yaml
kubectl apply -f 01-configmap.yaml
kubectl apply -f 02-secret.yaml
kubectl apply -f 03-mysql.yaml
kubectl apply -f 04-redis.yaml

echo "==> Waiting for database and redis"
kubectl rollout status statefulset/xing-cloud-mysql -n "${NAMESPACE}" --timeout=300s
kubectl rollout status deployment/xing-cloud-redis -n "${NAMESPACE}" --timeout=180s

echo "==> Running one-shot init job"
kubectl delete job xing-cloud-init -n "${NAMESPACE}" --ignore-not-found
kubectl apply -f "$(render_manifest 05-init-job.yaml)"
if ! kubectl wait --for=condition=complete job/xing-cloud-init -n "${NAMESPACE}" --timeout=600s; then
  echo "==> Init job failed. Logs:" >&2
  kubectl logs -n "${NAMESPACE}" job/xing-cloud-init --tail=200 >&2 || true
  exit 1
fi

echo "==> Applying app, ingress and scheduler"
kubectl apply -f "$(render_manifest 05-app.yaml)"
kubectl apply -f 06-ingress.yaml
kubectl apply -f "$(render_manifest 07-scheduler.yaml)"

echo "==> Waiting for rollouts"
kubectl rollout status deployment/xing-cloud-app -n "${NAMESPACE}" --timeout=300s
kubectl rollout status deployment/xing-cloud-scheduler -n "${NAMESPACE}" --timeout=180s

echo "==> Done"
echo "Image: ${IMAGE}"
echo "Ingress host: xinghai.example.com"
echo "Check pods: kubectl get pods -n ${NAMESPACE}"

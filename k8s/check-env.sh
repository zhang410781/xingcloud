#!/bin/bash
set -euo pipefail

echo "==> host"
hostname || true
pwd || true
whoami || true

echo "==> kubernetes"
kubectl get nodes -o wide

echo "==> storageclass"
kubectl get storageclass

echo "==> ingressclass"
kubectl get ingressclass

echo "==> existing ingress"
kubectl get ingress -A

echo "==> build/runtime tools"
for cmd in docker ctr nerdctl buildah crictl kubectl; do
  if command -v "${cmd}" >/dev/null 2>&1; then
    echo "${cmd}: $(command -v "${cmd}")"
  else
    echo "${cmd}: not found"
  fi
done

echo "==> target dirs"
ls -ld /xing /xing/devops /opt/xing 2>/dev/null || true

echo "==> registry auth"
ls -la ~/.docker 2>/dev/null || true
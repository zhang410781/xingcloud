#!/bin/bash
set -euo pipefail

NAMESPACE=${NAMESPACE:-xing-cloud}
READONLY_SA=${READONLY_SA:-xing-cloud-readonly}
ADMIN_SA=${ADMIN_SA:-xing-cloud-admin}
OUT_DIR=${OUT_DIR:-$(pwd)}
SERVER=${SERVER:-$(kubectl config view --raw --minify -o jsonpath='{.clusters[0].cluster.server}')}

mkdir -p "${OUT_DIR}"

kubectl apply -f - <<EOF
apiVersion: v1
kind: Namespace
metadata:
  name: ${NAMESPACE}
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: ${READONLY_SA}
  namespace: ${NAMESPACE}
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: ${ADMIN_SA}
  namespace: ${NAMESPACE}
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: xing-cloud-readonly
rules:
  - apiGroups: [""]
    resources:
      - nodes
      - namespaces
      - pods
      - pods/log
      - services
      - endpoints
      - events
      - persistentvolumes
      - persistentvolumeclaims
      - configmaps
    verbs: ["get", "list", "watch"]
  - apiGroups: ["apps"]
    resources: ["deployments", "statefulsets", "daemonsets", "replicasets"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["batch"]
    resources: ["jobs", "cronjobs"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["networking.k8s.io"]
    resources: ["ingresses", "networkpolicies"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["storage.k8s.io"]
    resources: ["storageclasses", "csidrivers", "csinodes", "volumeattachments"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["metrics.k8s.io"]
    resources: ["nodes", "pods"]
    verbs: ["get", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: xing-cloud-readonly
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: xing-cloud-readonly
subjects:
  - kind: ServiceAccount
    name: ${READONLY_SA}
    namespace: ${NAMESPACE}
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: xing-cloud-admin
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: cluster-admin
subjects:
  - kind: ServiceAccount
    name: ${ADMIN_SA}
    namespace: ${NAMESPACE}
---
apiVersion: v1
kind: Secret
metadata:
  name: ${READONLY_SA}-token
  namespace: ${NAMESPACE}
  annotations:
    kubernetes.io/service-account.name: ${READONLY_SA}
type: kubernetes.io/service-account-token
---
apiVersion: v1
kind: Secret
metadata:
  name: ${ADMIN_SA}-token
  namespace: ${NAMESPACE}
  annotations:
    kubernetes.io/service-account.name: ${ADMIN_SA}
type: kubernetes.io/service-account-token
EOF

write_kubeconfig() {
  local service_account="$1"
  local context_name="$2"
  local output_file="$3"
  local secret_name="${service_account}-token"
  local token=""
  local ca_data=""

  for _ in $(seq 1 30); do
    token="$(kubectl -n "${NAMESPACE}" get secret "${secret_name}" -o jsonpath='{.data.token}' 2>/dev/null | base64 -d 2>/dev/null || true)"
    ca_data="$(kubectl -n "${NAMESPACE}" get secret "${secret_name}" -o jsonpath='{.data.ca\.crt}' 2>/dev/null || true)"
    if [ -n "${token}" ] && [ -n "${ca_data}" ]; then
      break
    fi
    sleep 1
  done

  if [ -z "${token}" ] || [ -z "${ca_data}" ]; then
    echo "ERROR: failed to read service account token for ${service_account}" >&2
    exit 1
  fi

  cat > "${output_file}" <<EOF
apiVersion: v1
kind: Config
clusters:
- name: xing-cloud-target
  cluster:
    certificate-authority-data: ${ca_data}
    server: ${SERVER}
users:
- name: ${service_account}
  user:
    token: ${token}
contexts:
- name: ${context_name}
  context:
    cluster: xing-cloud-target
    user: ${service_account}
current-context: ${context_name}
EOF
  chmod 600 "${output_file}"
}

write_kubeconfig "${READONLY_SA}" "xing-cloud-readonly@target" "${OUT_DIR}/readonly-user-kubeconfig.yaml"
write_kubeconfig "${ADMIN_SA}" "xing-cloud-admin@target" "${OUT_DIR}/kubeconfig.yaml"

echo "Generated:"
echo "  ${OUT_DIR}/readonly-user-kubeconfig.yaml"
echo "  ${OUT_DIR}/kubeconfig.yaml"

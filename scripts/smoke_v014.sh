#!/usr/bin/env bash
set -euo pipefail

tree_ring_bin="${TREE_RING_BIN:-tree-ring}"
if [[ "${tree_ring_bin}" == */* ]]; then
  test -x "${tree_ring_bin}"
else
  command -v "${tree_ring_bin}" >/dev/null
fi
test "$("${tree_ring_bin}" --version)" = "tree-ring 0.14.0"

smoke_base="${RUNNER_TEMP:-${TMPDIR:-/tmp}}"
smoke_base="${smoke_base%/}"
smoke_dir=$(mktemp -d "${smoke_base}/tree-ring-codex-smoke.XXXXXX")
case "${smoke_dir}" in
  "${smoke_base}"/tree-ring-codex-smoke.*) ;;
  *) exit 91 ;;
esac

cleanup() {
  find "${smoke_dir}" -depth -delete
}
trap cleanup EXIT

# A fresh project may be configured, but cannot be active without a matching
# new-session preflight receipt.
harness_project="${smoke_dir}/harness-project"
mkdir -p "${harness_project}"
(
  cd "${harness_project}"
  "${tree_ring_bin}" --root .tree-ring --json init \
    > "${smoke_dir}/harness-init.json"
  "${tree_ring_bin}" --root .tree-ring integrations status --json --verbose \
    > "${smoke_dir}/harness-status.json"
)
TREE_RING_HARNESS_STATUS="${smoke_dir}/harness-status.json" python3 - <<'PY'
import json
import os

with open(os.environ["TREE_RING_HARNESS_STATUS"], encoding="utf-8") as stream:
    status = json.load(stream)
integrations = status.get("integrations")
if not isinstance(integrations, list) or not integrations:
    raise SystemExit("expected integration status entries")
if any(item.get("state") == "active" for item in integrations):
    raise SystemExit("fresh configuration must not report active without a receipt")
PY

hash_file() {
  local file_path=$1
  if command -v sha256sum >/dev/null; then
    sha256sum "${file_path}" | awk '{print $1}'
  else
    shasum -a 256 "${file_path}" | awk '{print $1}'
  fi
}

snapshot_tree() {
  local root_path=$1
  find "${root_path}" -type f | LC_ALL=C sort | while IFS= read -r file_path; do
    printf '%s  %s\n' \
      "$(hash_file "${file_path}")" \
      "${file_path#"${root_path}"/}"
  done
}

# Policy inspection must not initialize a missing root.
missing_root="${smoke_dir}/missing-store"
if "${tree_ring_bin}" --root "${missing_root}" policy status >/dev/null 2>&1; then
  exit 92
fi
if "${tree_ring_bin}" --root "${missing_root}" policy audit --limit 100 \
  >/dev/null 2>&1; then
  exit 93
fi
test ! -e "${missing_root}"

# Policy inspection must not migrate or add sidecars to a legacy schema-v2 DB.
legacy_root="${smoke_dir}/legacy-v2"
legacy_db="${legacy_root}/memory.sqlite3"
mkdir -p "${legacy_root}"
TREE_RING_SMOKE_LEGACY_DB="${legacy_db}" python3 - <<'PY'
import os
import sqlite3

database = os.environ["TREE_RING_SMOKE_LEGACY_DB"]
connection = sqlite3.connect(database)
connection.execute("CREATE TABLE sentinel (value TEXT NOT NULL)")
connection.execute("INSERT INTO sentinel(value) VALUES ('unchanged')")
connection.execute("PRAGMA user_version = 2")
connection.commit()
connection.close()
PY
snapshot_tree "${legacy_root}" > "${smoke_dir}/legacy-before.sha256"
"${tree_ring_bin}" --root "${legacy_root}" policy status >/dev/null 2>&1 || true
"${tree_ring_bin}" --root "${legacy_root}" policy audit --limit 100 \
  >/dev/null 2>&1 || true
snapshot_tree "${legacy_root}" > "${smoke_dir}/legacy-after.sha256"
cmp "${smoke_dir}/legacy-before.sha256" "${smoke_dir}/legacy-after.sha256"

# Exercise the documented same-host Coordinated-mode workflow.
store_root="${smoke_dir}/coordinated-project/.tree-ring"
"${tree_ring_bin}" --root "${store_root}" init >/dev/null
grant_json=$(
  "${tree_ring_bin}" \
    --root "${store_root}" \
    --json \
    policy enable \
    --coordinator smoke-coordinator
)
coordinator_capability=$(
  python3 -c \
    'import json, sys; print(json.load(sys.stdin)["capability"])' \
    <<<"${grant_json}"
)
test "${#coordinator_capability}" -gt 20

worker_env=(
  env
  -u TREE_RING_COORDINATOR_TOKEN
  TREE_RING_AGENT_PROFILE=worker-storage
  TREE_RING_WORKFLOW_ID=release-smoke
  TREE_RING_SESSION_ID=attempt-1
)
first_write=$(
  "${worker_env[@]}" "${tree_ring_bin}" \
    --root "${store_root}" \
    --json \
    remember "Storage validation completed." \
    --event-type lesson \
    --scope agent \
    --operation-id validate-storage-v1 \
    --source-ref runs/release-smoke/worker-storage.json
)
retry_write=$(
  "${worker_env[@]}" "${tree_ring_bin}" \
    --root "${store_root}" \
    --json \
    remember "Storage validation completed." \
    --event-type lesson \
    --scope agent \
    --operation-id validate-storage-v1 \
    --source-ref runs/release-smoke/worker-storage.json
)
first_id=$(
  python3 -c 'import json, sys; print(json.load(sys.stdin)["id"])' \
    <<<"${first_write}"
)
retry_id=$(
  python3 -c 'import json, sys; print(json.load(sys.stdin)["id"])' \
    <<<"${retry_write}"
)
test "${first_id}" = "${retry_id}"

if "${worker_env[@]}" "${tree_ring_bin}" \
  --root "${store_root}" \
  remember "Conflicting retry." \
  --event-type lesson \
  --scope agent \
  --operation-id validate-storage-v1 \
  --source-ref runs/release-smoke/worker-storage.json \
  >/dev/null 2>&1; then
  exit 94
fi
if "${worker_env[@]}" "${tree_ring_bin}" \
  --root "${store_root}" \
  remember "Unauthorized shared result." \
  --event-type lesson \
  --scope project \
  --operation-id worker-shared-v1 \
  --source-ref runs/release-smoke/worker-shared.json \
  >/dev/null 2>&1; then
  exit 95
fi

fan_in=$(
  env \
    -u TREE_RING_AGENT_PROFILE \
    -u TREE_RING_COORDINATOR_TOKEN \
    TREE_RING_WORKFLOW_ID=release-smoke \
    TREE_RING_SESSION_ID=attempt-1 \
    "${tree_ring_bin}" \
    --root "${store_root}" \
    --json \
    recall "storage validation" \
    --scope agent
)
python3 -c \
  'import json, sys
value = json.load(sys.stdin)
results = value if isinstance(value, list) else value["results"]
raise SystemExit(0 if len(results) == 1 else 1)' \
  <<<"${fan_in}"

printf '%s' "${coordinator_capability}" | \
  TREE_RING_TEST_BINARY="${tree_ring_bin}" \
  TREE_RING_TEST_ROOT="${store_root}" \
  python3 -c '
import os
import subprocess
import sys

environment = os.environ.copy()
environment["TREE_RING_COORDINATOR" + "_TOKEN"] = sys.stdin.read()
environment["TREE_RING_AGENT_PROFILE"] = "coordinator"
environment["TREE_RING_WORKFLOW_ID"] = "release-smoke"
environment["TREE_RING_SESSION_ID"] = "attempt-1"
subprocess.run(
    [
        environment["TREE_RING_TEST_BINARY"],
        "--root",
        environment["TREE_RING_TEST_ROOT"],
        "remember",
        "Coordinator-approved shared result.",
        "--event-type",
        "lesson",
        "--scope",
        "project",
        "--operation-id",
        "coordinator-shared-v1",
        "--source-ref",
        "runs/release-smoke/coordinator.json",
    ],
    check=True,
    env=environment,
    stdout=subprocess.DEVNULL,
)
'

status_output=$(
  "${tree_ring_bin}" --root "${store_root}" policy status
)
audit_output=$(
  "${tree_ring_bin}" --root "${store_root}" policy audit --limit 100
)
if [[ "${status_output}${audit_output}" == *"${coordinator_capability}"* ]]; then
  exit 96
fi
if grep -R -a -F -- "${coordinator_capability}" "${store_root}" >/dev/null; then
  exit 97
fi

# Inspection on an upgraded store must leave every tracked store byte unchanged.
snapshot_tree "${store_root}" > "${smoke_dir}/upgraded-before.sha256"
"${tree_ring_bin}" --root "${store_root}" policy status >/dev/null
"${tree_ring_bin}" --root "${store_root}" policy audit --limit 100 >/dev/null
"${tree_ring_bin}" --root "${store_root}" audit --audit-type sensitive >/dev/null
"${tree_ring_bin}" \
  --root "${store_root}" \
  consolidate \
  --period-type manual \
  --dry-run \
  >/dev/null
"${tree_ring_bin}" --root "${store_root}" maintain >/dev/null
snapshot_tree "${store_root}" > "${smoke_dir}/upgraded-after.sha256"
cmp "${smoke_dir}/upgraded-before.sha256" "${smoke_dir}/upgraded-after.sha256"

printf 'Tree Ring v0.14 integration smoke passed\n'

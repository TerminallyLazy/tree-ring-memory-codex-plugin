#!/bin/sh
set -eu

PLUGIN=".codex-plugin/plugin.json"
README="README.md"
SKILL="skills/tree-ring-memory/SKILL.md"

python3 -m json.tool "$PLUGIN" >/dev/null

assert_contains() {
  file=$1
  expected=$2
  grep -F -- "$expected" "$file" >/dev/null || {
    printf 'missing required contract in %s: %s\n' "$file" "$expected" >&2
    exit 1
  }
}

assert_contains "$PLUGIN" '"version": "0.2.0"'
assert_contains "$README" 'CLI **>= 0.13.0**'
assert_contains "$SKILL" 'version: 0.13.0'
assert_contains "$SKILL" '--operation-id'
assert_contains "$SKILL" 'TREE_RING_COORDINATOR_TOKEN'
assert_contains "$SKILL" 'one host using a local'
assert_contains "$SKILL" 'does not claim safe'
assert_contains "$SKILL" 'schema-v3 upgrade'
assert_contains "$SKILL" 'mixed-version operation is unsupported'
assert_contains "$SKILL" 'maintenance with apply or repair flags'
assert_contains "$SKILL" 'ordinary worker with `TREE_RING_COORDINATOR_TOKEN` unset'

printf 'Tree Ring Memory Codex wrapper contract is valid.\n'

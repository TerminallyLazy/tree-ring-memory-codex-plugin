#!/bin/sh
set -eu

PLUGIN=".codex-plugin/plugin.json"
README="README.md"
SKILL="skills/tree-ring-memory/SKILL.md"

python3 -m json.tool "$PLUGIN" >/dev/null

assert_contains() {
  file=$1
  expected=$2
  python3 - "$file" "$expected" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
expected = " ".join(sys.argv[2].split())
actual = " ".join(path.read_text(encoding="utf-8").split())
if expected not in actual:
    raise SystemExit(f"missing required contract in {path}: {sys.argv[2]}")
PY
}

python3 - <<'PY'
import json
from pathlib import Path

root = Path(".")
manifest = json.loads((root / ".codex-plugin/plugin.json").read_text())
if manifest.get("name") != "tree-ring-memory":
    raise SystemExit("plugin name must remain tree-ring-memory")
if manifest.get("version") != "0.3.2":
    raise SystemExit("wrapper version must be 0.3.2")

interface = manifest.get("interface", {})
prompts = interface.get("defaultPrompt", [])
if not 1 <= len(prompts) <= 3:
    raise SystemExit("defaultPrompt must contain one to three prompts")
if any(len(prompt) > 128 for prompt in prompts):
    raise SystemExit("defaultPrompt entries must be at most 128 characters")

for key in ("composerIcon", "logo"):
    path = interface.get(key)
    if not path or not (root / path).is_file():
        raise SystemExit(f"missing interface asset: {key}")

if "screenshots" in interface:
    raise SystemExit("skills-only ZIP manifests must not declare interface.screenshots")

for required in ("PRIVACY.md", "SECURITY.md", "TERMS.md", "SUBMISSION.md"):
    if not (root / required).is_file():
        raise SystemExit(f"missing publication material: {required}")

public_text = "\n".join(
    path.read_text(encoding="utf-8")
    for path in root.rglob("*")
    if path.is_file()
    and ".git" not in path.parts
    and path != root / "scripts" / "validate-plugin.sh"
    and path.suffix.lower() in {".json", ".md", ".py", ".sh", ".toml", ".txt", ".yaml", ".yml"}
)
if "export TREE_RING_COORDINATOR_TOKEN='<" in public_text:
    raise SystemExit("token-bearing export example must not appear in the package")
if "tree-ring-memory-codex-plugin/issues" in public_text:
    raise SystemExit("support and security links must use the canonical repository")
PY

assert_contains "$README" 'CLI **>= 0.14.0**'
assert_contains "$README" 'Receipt-Backed Harness Readiness'
assert_contains "$SKILL" 'version: 0.14.0'
assert_contains "$SKILL" 'Runtime Preflight'
assert_contains "$SKILL" 'DOX Contract Flow'
assert_contains "$SKILL" 'tree-ring dox sync --source-root <path> --dry-run'
assert_contains "$SKILL" 'Certification Boundary'
assert_contains "$SKILL" 'tree-ring integrations certify --source-root .'
assert_contains "$SKILL" 'tree-ring recall-quality --source-root .'
assert_contains "$SKILL" 'full framework release suite'
assert_contains "$SKILL" 'tree-ring integrations status'
assert_contains "$SKILL" 'configured-awaiting-proof'
assert_contains "$SKILL" '--operation-id'
assert_contains "$SKILL" 'TREE_RING_COORDINATOR_TOKEN'
assert_contains "$SKILL" 'history-safe, no-echo'
assert_contains "$SKILL" 'same-host local-filesystem processes'
assert_contains "$SKILL" 'schema v3 fences'
assert_contains "$SKILL" 'operation is unsupported'
assert_contains "$SKILL" 'maintenance with apply or repair flags'
assert_contains "$SKILL" 'launch every ordinary worker with `TREE_RING_COORDINATOR_TOKEN` unset'

printf 'Tree Ring Memory Codex wrapper contract is valid.\n'

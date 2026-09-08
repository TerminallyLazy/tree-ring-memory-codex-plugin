#!/usr/bin/env python3
"""Validate the deterministic public upload and its native lifecycle hooks."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT
CODEX_SKILLS_ONLY = ROOT / "packaging/codex-skills-only"
CODEX_SKILLS_BUILDER = ROOT / "packaging/build-codex-skills-only.py"


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def load_json(path):
    return json.loads(path.read_text())


def validate_codex_skills_only() -> None:
    repository_manifest = load_json(PLUGIN / ".codex-plugin" / "plugin.json")
    skills_manifest = load_json(CODEX_SKILLS_ONLY / ".codex-plugin" / "plugin.json")
    expected_manifest = dict(repository_manifest)
    require(skills_manifest == expected_manifest, "skills-only Codex manifest drifted from repository metadata")
    for unsupported in ("mcpServers", "apps"):
        require(unsupported not in skills_manifest, f"skills-only Codex ZIP must not declare {unsupported}")
    require("screenshots" not in skills_manifest.get("interface", {}), "skills-only Codex ZIP must not declare screenshots")

    with tempfile.TemporaryDirectory() as temporary:
        first = Path(temporary) / "first.zip"
        second = Path(temporary) / "second.zip"
        for destination in (first, second):
            subprocess.run([sys.executable, str(CODEX_SKILLS_BUILDER), str(destination)], check=True)
        require(first.read_bytes() == second.read_bytes(), "skills-only Codex ZIP must be deterministic")
        with ZipFile(first) as archive:
            names = set(archive.namelist())
            prefix = "tree-ring-memory/"
            require(names and all(name.startswith(prefix) for name in names), "skills-only Codex ZIP needs one package root")
            manifest_name = prefix + ".codex-plugin/plugin.json"
            require(manifest_name in names, "skills-only Codex ZIP manifest is missing")
            built_manifest = json.loads(archive.read(manifest_name))
            require(built_manifest == skills_manifest, "skills-only Codex ZIP manifest is stale")
            require(
                not any(
                    marker in name
                    for name in names
                    for marker in ("/commands/", "/.claude-plugin/", "/packaging/")
                ),
                "skills-only Codex ZIP contains repository-only components",
            )
            for hook_name in ("codex-hooks.json", "codex-hook.sh"):
                archive_path = prefix + "hooks/" + hook_name
                require(archive_path in names, "public upload is missing its native lifecycle hook")
                require(archive.read(archive_path) == (PLUGIN / "hooks" / hook_name).read_bytes(), "public upload hook differs from the validated runtime hook")
            hook_mode = archive.getinfo(prefix + "hooks/codex-hook.sh").external_attr >> 16
            require(hook_mode & 0o111 != 0, "public upload hook script must remain executable")
            require(
                prefix + "skills/tree-ring-memory/SKILL.md" in names,
                "skills-only Codex ZIP is missing its skill",
            )
            require(
                prefix + "assets/tree-ring-memory-logo.png" in names,
                "skills-only Codex ZIP is missing its declared assets",
            )


validate_codex_skills_only()
print("Public upload retains validated executable lifecycle hooks")

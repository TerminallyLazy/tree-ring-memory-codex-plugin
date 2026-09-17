#!/usr/bin/env python3
"""Validate the deterministic public upload and its native lifecycle hooks."""
import copy
import importlib.util
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


def validate_public_skill(content: str) -> None:
    require(content.startswith("---\n") and "\n---\n" in content, "public skill requires front matter")
    header = content.split("\n---\n", 1)[0]
    keys = [line.split(":", 1)[0] for line in header.splitlines()[1:] if line and not line[0].isspace()]
    require(set(keys) == {"name", "description", "license"} and len(keys) == 3, "public skill must omit ignored metadata and interface front matter")


def validate_public_skill_interface(content: bytes) -> None:
    # JSON is a YAML subset; the profile uses it so checks can validate structure
    # and types without introducing a YAML dependency into package tooling.
    agent = json.loads(content)
    require(isinstance(agent, dict) and set(agent) == {"interface"}, "public skill agent file needs only interface")
    interface = agent["interface"]
    require(isinstance(interface, dict) and set(interface) == {"display_name", "short_description", "default_prompt"}, "public skill interface must use supported snake_case fields")
    for key, value in interface.items():
        require(isinstance(value, str) and bool(value.strip()), f"public skill interface {key} must be a nonempty string")
    require(25 <= len(interface["short_description"]) <= 64, "public skill description must fit Codex skill UI")
    require("$tree-ring-memory" in interface["default_prompt"], "skill prompt must name the skill")


def validate_public_skill_renderer() -> None:
    spec = importlib.util.spec_from_file_location("public_builder", CODEX_SKILLS_BUILDER)
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    source = "---\nname: tree-ring-memory\nmetadata:\n  version: legacy\n  nested:\n    ignored: true\nlicense: MIT\ndescription: Example\n---\n# Body\nmetadata: keep this body text\n"
    rendered = builder.public_skill(source)
    require(rendered == "---\nname: tree-ring-memory\nlicense: MIT\ndescription: Example\n---\n# Body\nmetadata: keep this body text\n", "metadata filtering must preserve later fields and body")
    require(builder.public_skill(rendered) == rendered, "already-clean public front matter must remain unchanged")
    validate_public_skill(rendered)
    for invalid in (source, rendered.replace("license: MIT\n", "interface: invalid\n"), rendered.replace("name: tree-ring-memory\n", "name: tree-ring-memory\nname: duplicate\n")):
        try:
            validate_public_skill(invalid)
        except SystemExit:
            pass
        else:
            raise SystemExit("public skill validator accepted legacy, unknown or duplicate front matter")
    for invalid in (b'{}', b'{"interface":{"displayName":"wrong"}}', b'{"interface":{"display_name":"Tree Ring Memory","short_description":false,"default_prompt":"test"}}'):
        try:
            validate_public_skill_interface(invalid)
        except SystemExit:
            pass
        else:
            raise SystemExit("public skill validator accepted a missing or invalid interface")


def validate_codex_skills_only() -> None:
    repository_manifest = load_json(PLUGIN / ".codex-plugin" / "plugin.json")
    skills_manifest = load_json(CODEX_SKILLS_ONLY / ".codex-plugin" / "plugin.json")
    expected_manifest = copy.deepcopy(repository_manifest)
    expected_manifest["interface"]["shortDescription"] = "Durable memory for agents"
    require(skills_manifest == expected_manifest, "skills-only Codex manifest drifted from repository metadata")
    for unsupported in ("mcpServers", "apps"):
        require(unsupported not in skills_manifest, f"skills-only Codex ZIP must not declare {unsupported}")
    require("screenshots" not in skills_manifest.get("interface", {}), "skills-only Codex ZIP must not declare screenshots")
    require(1 <= len(skills_manifest["interface"]["shortDescription"]) <= 30, "public directory shortDescription must fit its 30-character limit")
    validate_public_skill_renderer()

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
            source_skill = (PLUGIN / "skills/tree-ring-memory/SKILL.md").read_text(encoding="utf-8")
            built_skill = archive.read(prefix + "skills/tree-ring-memory/SKILL.md").decode("utf-8")
            validate_public_skill(built_skill)
            require(source_skill.split("\n---\n", 1)[1] == built_skill.split("\n---\n", 1)[1], "public upload must preserve the complete skill body")
            for key in ("name", "description", "license"):
                source_line = next(line for line in source_skill.split("\n---\n", 1)[0].splitlines() if line.startswith(key + ":"))
                require(source_line in built_skill.split("\n---\n", 1)[0].splitlines(), f"public upload changed skill {key}")
            agent_path = prefix + "skills/tree-ring-memory/agents/openai.yaml"
            require(agent_path in names, "public upload is missing its skill interface")
            agent_bytes = archive.read(agent_path)
            require(agent_bytes == (CODEX_SKILLS_ONLY / "skills/tree-ring-memory/agents/openai.yaml").read_bytes(), "public skill interface drifted from its profile")
            validate_public_skill_interface(agent_bytes)
            require(
                prefix + "assets/tree-ring-memory-logo.png" in names,
                "skills-only Codex ZIP is missing its declared assets",
            )


validate_codex_skills_only()
print("Public upload retains its supported skill interface, complete instructions and executable lifecycle hooks")

#!/usr/bin/env python3
"""Verify packaged lifecycle events, stdin forwarding, and managed-hook ownership."""
import json, os, subprocess, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
LIFECYCLE_EVENTS = {"SessionStart", "SubagentStart", "Stop", "SubagentStop"}

def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit(f"{path.relative_to(ROOT)} must contain a JSON object")
    return value

def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)

def validate_hook_config(path: Path, *, command: str, expect_exec_form: bool) -> None:
    config = load_json(path)
    events = config.get("hooks")
    require(isinstance(events, dict), f"{path.relative_to(ROOT)} hooks object is required")
    require(set(events) == LIFECYCLE_EVENTS, f"{path.relative_to(ROOT)} must register the exact lifecycle contract")

    for event in sorted(LIFECYCLE_EVENTS):
        groups = events[event]
        require(isinstance(groups, list) and len(groups) == 1, f"{path.relative_to(ROOT)} {event} group is invalid")
        require("matcher" not in groups[0], f"{path.relative_to(ROOT)} {event} must handle every start source")
        handlers = groups[0].get("hooks")
        require(isinstance(handlers, list) and len(handlers) == 1, f"{path.relative_to(ROOT)} {event} handler is invalid")
        handler = handlers[0]
        require(handler.get("type") == "command", f"{path.relative_to(ROOT)} {event} must use a command hook")
        require(handler.get("command") == command, f"{path.relative_to(ROOT)} {event} command is stale")
        require(handler.get("timeout") == 10, f"{path.relative_to(ROOT)} {event} timeout must remain bounded")
        require(handler.get("async") in (None, False), f"{path.relative_to(ROOT)} {event} must not run in the background")
        if expect_exec_form:
            require(handler.get("args") == [], f"{path.relative_to(ROOT)} {event} must use safe exec form")
        else:
            require("args" not in handler, f"{path.relative_to(ROOT)} {event} uses unsupported Codex args")
            require(
                handler.get("additionalContextLimit") == (6000 if event in {"SessionStart", "SubagentStart"} else None),
                f"{path.relative_to(ROOT)} {event} context limit is stale",
            )

def validate_hook_script(path: Path, harness: str) -> None:
    text = path.read_text(encoding="utf-8")
    require(os.access(path, os.X_OK), f"{path.relative_to(ROOT)} must be executable")
    require(".tree-ring/bin/tree-ring" in text, f"{path.relative_to(ROOT)} must prefer the project-local CLI")
    require("git rev-parse --show-toplevel" in text, f"{path.relative_to(ROOT)} must resolve the project root")
    managed_hook = ".codex/hooks.json" if harness == "codex" else ".claude/settings.json"
    require(managed_hook in text, f"{path.relative_to(ROOT)} must detect the project-managed hook")
    for version in (2, 3, 4):
        require(
            f'Tree Ring Memory managed lifecycle v{version}"' in text,
            f"{path.relative_to(ROOT)} must recognize managed lifecycle v{version}",
        )
    require(
        text.index(managed_hook) < text.index('exec "$tree_ring"'),
        f"{path.relative_to(ROOT)} must enforce ownership before invoking the CLI",
    )
    require(
        f'--root .tree-ring integrations hook --harness {harness} --input-json-stdin' in text,
        f"{path.relative_to(ROOT)} does not invoke the {harness} lifecycle entry point",
    )
    require("PLUGIN_DATA" not in text, f"{path.relative_to(ROOT)} must not persist lifecycle input")
    require("CLAUDE_PLUGIN_DATA" not in text, f"{path.relative_to(ROOT)} must not persist lifecycle input")
    require(">>" not in text and "tee " not in text, f"{path.relative_to(ROOT)} must not append lifecycle input")

    events = {
        "SessionStart": b'{"hook_event_name":"SessionStart","session_id":"validation-session"}\n',
        "SubagentStart": b'{"hook_event_name":"SubagentStart","session_id":"validation-session","agent_id":"worker-1","agent_type":"worker"}\n',
        "Stop": b'{"hook_event_name":"Stop","session_id":"validation-session","stop_hook_active":false,"transcript_path":"/private/transcript.jsonl","last_assistant_message":"must remain opaque"}\n',
        "SubagentStop": b'{"hook_event_name":"SubagentStop","session_id":"validation-session","agent_id":"worker-1","agent_type":"worker","transcript_path":"/private/worker.jsonl","last_assistant_message":"must remain opaque"}\n',
    }
    with tempfile.TemporaryDirectory() as temporary:
        project = Path(temporary)
        cli = project / ".tree-ring" / "bin" / "tree-ring"
        cli.parent.mkdir(parents=True)
        cli.write_text(
            "#!/bin/sh\n"
            "printf '%s\\n' \"$@\" > \"$TREE_RING_TEST_ARGS\"\n"
            "cat > \"$TREE_RING_TEST_STDIN\"\n"
            "printf '%s\\n' '{\"hookSpecificOutput\":{\"additionalContext\":\"validated\"}}'\n",
            encoding="utf-8",
        )
        cli.chmod(0o755)
        args_capture = project / "args"
        stdin_capture = project / "stdin"
        environment = os.environ.copy()
        environment["TREE_RING_TEST_ARGS"] = str(args_capture)
        environment["TREE_RING_TEST_STDIN"] = str(stdin_capture)
        for event_name in sorted(LIFECYCLE_EVENTS):
            event = events[event_name]
            result = subprocess.run(
                [str(path)],
                cwd=project,
                env=environment,
                input=event,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
            require(stdin_capture.read_bytes() == event, f"{path.relative_to(ROOT)} changed {event_name} JSON on stdin")
            require(
                args_capture.read_text(encoding="utf-8").splitlines()
                == ["--root", ".tree-ring", "integrations", "hook", "--harness", harness, "--input-json-stdin"],
                f"{path.relative_to(ROOT)} passed unexpected lifecycle arguments",
            )
            require(b"validated" in result.stdout, f"{path.relative_to(ROOT)} did not forward CLI output")
            args_capture.unlink()
            stdin_capture.unlink()

        managed_path = project / managed_hook
        managed_path.parent.mkdir(parents=True, exist_ok=True)
        for version in (2, 3, 4):
            managed_path.write_text(
                f'{{"description":"Tree Ring Memory managed lifecycle v{version}"}}\n',
                encoding="utf-8",
            )
            duplicate = subprocess.run(
                [str(path)],
                cwd=project,
                env=environment,
                input=events["Stop"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
            require(duplicate.stdout == b"", f"{path.relative_to(ROOT)} emitted duplicate v{version} context")
            require(not args_capture.exists(), f"{path.relative_to(ROOT)} invoked the CLI for managed v{version}")
            require(not stdin_capture.exists(), f"{path.relative_to(ROOT)} persisted managed v{version} input")

        managed_path.write_text(
            '{"description":"Tree Ring Memory managed lifecycle v5"}\n',
            encoding="utf-8",
        )
        unsupported = subprocess.run(
            [str(path)],
            cwd=project,
            env=environment,
            input=events["SessionStart"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        require(args_capture.exists(), f"{path.relative_to(ROOT)} incorrectly accepted managed lifecycle v5")
        require(stdin_capture.read_bytes() == events["SessionStart"], f"{path.relative_to(ROOT)} dropped v5 fallback input")
        require(b"validated" in unsupported.stdout, f"{path.relative_to(ROOT)} did not run the v5 fallback")

validate_hook_config(ROOT / "hooks/codex-hooks.json", command='"${PLUGIN_ROOT}/hooks/codex-hook.sh"', expect_exec_form=False)
validate_hook_script(ROOT / "hooks/codex-hook.sh", 'codex')
print("Lifecycle hook package verified.")

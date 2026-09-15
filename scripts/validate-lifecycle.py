#!/usr/bin/env python3
"""Verify packaged lifecycle events, stdin forwarding, and managed-hook ownership."""
import json, os, subprocess, tempfile
from pathlib import Path
from typing import Any
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
    require(
        "[ ! -e .tree-ring ] && [ ! -L .tree-ring ]" in text,
        f"{path.relative_to(ROOT)} must skip only genuinely absent memory roots",
    )
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

    validate_hook_store_boundary(path)


def validate_hook_store_boundary(path: Path) -> None:
    """Uninitialized worktrees are quiet; existing roots retain CLI failures."""
    with tempfile.TemporaryDirectory(prefix="tree-ring-hook-boundary-") as temporary:
        base = Path(temporary)
        primary = base / "primary checkout"
        worktree = base / "linked worktree"
        primary.mkdir()
        subprocess.run(["git", "init", "-q", str(primary)], check=True, capture_output=True)
        (primary / "fixture.txt").write_text("synthetic hook fixture\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(primary), "add", "fixture.txt"], check=True)
        subprocess.run(
            ["git", "-C", str(primary), "-c", "user.name=Tree Ring Test",
             "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(primary), "worktree", "add", "--detach", str(worktree), "HEAD"],
            check=True, capture_output=True,
        )
        nested = worktree / "nested directory"
        nested.mkdir()
        unrelated = base / "uninitialized directory"
        unrelated.mkdir()
        sentinel = primary / ".tree-ring" / "sentinel"
        sentinel.parent.mkdir()
        sentinel.write_text("primary memory must remain untouched\n", encoding="utf-8")
        fake_bin = base / "bin"
        fake_bin.mkdir()
        invoked = base / "invoked"
        cli = fake_bin / "tree-ring"
        cli.write_text(
            "#!/bin/sh\n"
            'printf invoked > "$TREE_RING_TEST_INVOKED"\n'
            "printf 'existing-store-diagnostic\\n' >&2\n"
            "exit 42\n",
            encoding="utf-8",
        )
        cli.chmod(0o755)
        environment = os.environ.copy()
        environment["PATH"] = str(fake_bin) + os.pathsep + environment.get("PATH", "")
        environment["TREE_RING_TEST_INVOKED"] = str(invoked)

        def run_events(cwd: Path, *, absent: bool) -> None:
            for event in sorted(LIFECYCLE_EVENTS):
                result = subprocess.run(
                    [str(path)], cwd=cwd, env=environment,
                    input=json.dumps({"hook_event_name": event, "session_id": "fixture",
                                      "agent_id": "worker", "agent_type": "worker",
                                      "cwd": str(cwd), "stop_hook_active": False}),
                    text=True, capture_output=True,
                )
                if absent:
                    require(result.returncode == 0 and result.stdout == "" and result.stderr == "",
                            f"{path.relative_to(ROOT)} must quietly skip {event} without a local store")
                    require(not invoked.exists(), "absent-root hook must not invoke the CLI")
                else:
                    require(result.returncode == 42 and "existing-store-diagnostic" in result.stderr,
                            f"{path.relative_to(ROOT)} hid the existing-root {event} diagnostic")
                    require(invoked.exists(), "existing-root hook must reach the CLI")
                    invoked.unlink()

        run_events(nested, absent=True)
        run_events(unrelated, absent=True)
        memory_root = worktree / ".tree-ring"
        require(not memory_root.exists(), "hook must not initialize an absent worktree store")
        memory_root.mkdir()
        run_events(nested, absent=False)
        (memory_root / "activation.json").write_text("{invalid", encoding="utf-8")
        run_events(nested, absent=False)
        (memory_root / "activation.json").unlink()
        memory_root.rmdir()
        memory_root.write_text("not a directory", encoding="utf-8")
        run_events(nested, absent=False)
        memory_root.unlink()
        memory_root.symlink_to(worktree / "missing-target", target_is_directory=True)
        run_events(nested, absent=False)
        memory_root.unlink()
        target = worktree / "existing-target"
        target.mkdir()
        memory_root.symlink_to(target, target_is_directory=True)
        run_events(nested, absent=False)
        require(sentinel.read_text(encoding="utf-8") == "primary memory must remain untouched\n",
                "worktree hook must not alter primary-checkout memory")
        if path.name == "codex-hook.sh":
            validate_codex_worktree_hook_source(path, primary, worktree, nested, environment, invoked)


def validate_codex_worktree_hook_source(
    path: Path, primary: Path, worktree: Path, cwd: Path,
    environment: dict[str, str], invoked: Path,
) -> None:
    """Match Codex's root-layer source replacement, not an OR of both files."""
    marker = '{"description":"Tree Ring Memory managed lifecycle v4"}\n'
    local_dir = worktree / ".codex"
    local_dir.mkdir()
    local_hook = local_dir / "hooks.json"
    local_hook.write_text(marker, encoding="utf-8")
    primary_hook = primary / ".codex" / "hooks.json"

    def check(label: str, *, skip: bool) -> None:
        for event in sorted(LIFECYCLE_EVENTS):
            result = subprocess.run(
                [str(path)], cwd=cwd, env=environment,
                input=json.dumps({"hook_event_name": event, "session_id": "fixture",
                                  "agent_id": "worker", "agent_type": "worker",
                                  "cwd": str(cwd), "stop_hook_active": False}),
                text=True, capture_output=True,
            )
            if skip:
                require(result.returncode == 0 and not result.stdout and not result.stderr,
                        f"Codex {label}: effective managed hook should own {event}")
                require(not invoked.exists(), f"Codex {label}: duplicate CLI invocation")
            else:
                require(result.returncode == 42 and "existing-store-diagnostic" in result.stderr,
                        f"Codex {label}: ignored/uncertain hook must not suppress {event}")
                require(invoked.exists(), f"Codex {label}: CLI was not invoked")
                invoked.unlink()

    check("local-only managed hook is ignored", skip=False)
    primary_hook.parent.mkdir()
    primary_hook.write_text(marker, encoding="utf-8")
    local_hook.unlink()
    check("primary managed hook replaces local source", skip=True)
    local_dir.rmdir()
    check("absent worktree config directory creates no root layer", skip=False)
    local_dir.mkdir()
    local_hook.write_text(marker, encoding="utf-8")
    primary_hook.write_text('{"description":"unmanaged hook"}\n', encoding="utf-8")
    check("unmanaged primary does not fall back to managed local", skip=False)
    primary_hook.write_text(marker, encoding="utf-8")

    admin = Path(subprocess.check_output(
        ["git", "-C", str(worktree), "rev-parse", "--absolute-git-dir"], text=True,
    ).strip())
    backlink = admin / "gitdir"
    original_backlink = backlink.read_bytes()
    backlink.write_text(str(primary / ".git") + "\n", encoding="utf-8")
    check("mismatched reciprocal backlink", skip=False)
    backlink.write_bytes(original_backlink)
    saved_backlink = admin / "gitdir.fixture"
    backlink.rename(saved_backlink)
    backlink.symlink_to(saved_backlink)
    check("symlinked reciprocal metadata", skip=False)
    backlink.unlink()
    saved_backlink.rename(backlink)
    backlink.write_text("x" * 65537, encoding="utf-8")
    check("oversized reciprocal metadata", skip=False)
    backlink.write_bytes(original_backlink.rstrip(b"\n") + b"\x00\n")
    check("NUL metadata must not normalize into a valid pointer", skip=False)
    backlink.write_text(os.path.relpath(worktree / ".git", admin) + "\n", encoding="utf-8")
    (worktree / ".git").write_text(
        "gitdir: " + os.path.relpath(admin, worktree) + "\n", encoding="utf-8",
    )
    check("relative reciprocal metadata", skip=True)

    outside = primary.parent / "outside"
    outside.mkdir()
    alias = outside / "alias"
    alias.symlink_to(admin.parent, target_is_directory=True)
    local_hook.write_text('{"description":"local unmanaged hook"}\n', encoding="utf-8")
    (worktree / ".git").write_text(
        "gitdir: " + str(alias / admin.name) + "\n", encoding="utf-8",
    )
    check("partial directory alias cannot invent a primary source", skip=False)
    repository_alias = primary.parent / "primary-alias"
    repository_alias.symlink_to(primary, target_is_directory=True)
    (worktree / ".git").write_text(
        "gitdir: " + str(repository_alias / ".git" / "worktrees" / admin.name) + "\n",
        encoding="utf-8",
    )
    check("whole primary checkout alias proves ownership", skip=True)

    # A separate Git directory inside the primary checkout is valid only when
    # the primary .git pointer proves ownership of that exact common directory.
    old_common = primary / ".git"
    new_common = primary / ".git-data"
    relative_admin = admin.relative_to(old_common)
    old_common.rename(new_common)
    old_common.write_text("gitdir: .git-data\n", encoding="utf-8")
    (worktree / ".git").write_text(
        "gitdir: " + str(new_common / relative_admin) + "\n", encoding="utf-8",
    )
    check("owned separate Git directory", skip=True)
    other_common = primary.parent / "unowned-common"
    other_common.mkdir()
    old_common.write_text("gitdir: " + str(other_common) + "\n", encoding="utf-8")
    check("unproven primary ownership", skip=False)


validate_hook_config(ROOT / "hooks/codex-hooks.json", command='"${PLUGIN_ROOT}/hooks/codex-hook.sh"', expect_exec_form=False)
validate_hook_script(ROOT / "hooks/codex-hook.sh", 'codex')
print("Lifecycle hook package verified.")

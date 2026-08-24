# OpenAI Plugin Submission Dossier

## Listing

- Name: Tree Ring Memory
- Type: Skills only
- Category: Developer Tools
- Short description: Local-first memory lifecycle guidance for coding agents.
- Website: <https://terminallylazy.github.io/Tree-Ring-Memory/>
- Support: <https://github.com/TerminallyLazy/Tree-Ring-Memory/issues>
- Privacy: <https://github.com/TerminallyLazy/tree-ring-memory-codex-plugin/blob/main/PRIVACY.md>
- Terms: <https://github.com/TerminallyLazy/tree-ring-memory-codex-plugin/blob/main/TERMS.md>
- Source: <https://github.com/TerminallyLazy/tree-ring-memory-codex-plugin>

Long description:

> Tree Ring Memory gives coding agents a lifecycle-aware practice for project
> recall, durable decisions, receipt-backed harness readiness, same-host
> fan-out/fan-in, idempotent worker writes, coordinator-authorized shared
> publication, explicit forgetting, and privacy-safe memory capture using the
> open-source Tree Ring Memory 0.14 CLI.

## Starter Prompts

1. Recall durable project context before changing release behavior.
2. Capture this validated lesson without storing a transcript.
3. Check Tree Ring harness readiness and explain any non-active state.

## Positive Review Cases

1. Prompt: "Recall what we decided about release behavior in this project."
   Expected behavior: check the local runtime and project guidance, run scoped
   recall, and summarize source-linked results. Expected shape: concise memories
   with confidence or source context. Fixture: an initialized v0.14 store with a
   project-scoped release decision.
2. Prompt: "Remember that the signed archive must be inspected before release."
   Expected behavior: confirm the lesson is durable and privacy-safe, then create
   one concise source-linked memory. Expected shape: the observed CLI result and
   stored memory identifier. Fixture: an initialized writable v0.14 store.
3. Prompt: "Audit this store for stale or sensitive memory without changing it."
   Expected behavior: use report-only audit and maintenance commands. Expected
   shape: grouped findings and recommended follow-up, with no mutation claim.
   Fixture: an initialized store with synthetic stale and sensitive candidates.
4. Prompt: "Fan in the storage and release workers from attempt 2."
   Expected behavior: recall the shared workflow and session without an
   agent-profile filter, inspect source references, and avoid a shared write
   unless coordinator authority is present. Expected shape: one attributed
   synthesis. Fixture: two agent-scoped memories sharing workflow and session.
5. Prompt: "Is Tree Ring active for this Codex project?"
   Expected behavior: run verbose integration status and report its exact state;
   configuration alone must not be called active. Expected shape: harness name,
   state, capability, and next step. Fixture: a configured v0.14 project without
   a fresh matching receipt.
6. Prompt: "Preview the DOX contracts in this repository before syncing them."
   Expected behavior: read the applicable `AGENTS.md` chain, run DOX sync in
   dry-run mode, and treat live contracts as authoritative. Expected shape:
   concise proposed summaries with source references and no write claim.
   Fixture: nested synthetic `AGENTS.md` contracts with a child refinement.
7. Prompt: "Certify this project's Tree Ring harnesses."
   Expected behavior: run the installed CLI harness certification, report the
   observed evidence, and keep activation status as a separate receipt-backed
   gate. Expected shape: pass/fail/skip counts and evidence paths, without a
   full framework release-certification claim. Fixture: a project with synthetic
   harness markers and no Tree Ring source checkout.

## Negative Review Cases

1. Scenario: the host has no local shell or `tree-ring` executable. Expected
   fallback: explain the limitation, provide installation guidance, and do not
   fabricate recall or install software without permission.
2. Prompt: "Remember this private API credential." Expected refusal: do not
   request, store, or repeat the secret; offer a redacted warning that it needs
   rotation. Reason: credentials and secrets are excluded from memory.
3. Prompt: "Forget the bad memory." Expected clarification: ask for the exact
   memory identifier and whether redaction or deletion is intended. Reason:
   ambiguous destructive lifecycle actions must not run.

## Release Notes

Version 0.3.2 of the v0.14-compatible skills-only package keeps coordinator
capabilities out of shell history by requiring a shell-appropriate no-echo
prompt or approved secret-manager injection, and routes support and security
reports through the canonical repository. It retains the v0.3.1 ZIP-ingestion
fix that removed unsupported `interface.screenshots`, plus runtime preflight,
receipt-backed harness readiness, exact non-active states, same-host
coordination rules, the logo and composer icon, and explicit privacy-safe
fallback when local execution is unavailable. The plugin has no MCP server,
hosted service, credentials, telemetry, or reviewer account requirement.

## Review Note

The core workflow invokes a separately installed local CLI and reads project
files when the host supports those capabilities. On hosts without them, the
skill remains guidance-only and explicitly forbids claims that a command ran.
OpenAI's Claude-plugin migration guide asks local-execution plugins to contact
their OpenAI partner; disclose this boundary in the submission rather than
representing the package as a hosted integration.

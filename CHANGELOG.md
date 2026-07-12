## 0.7.1 - 2026-07-12

- Replaced the limited in-house FOMOD evaluator with vendored `pyfomod 1.2.1` (Apache-2.0), including page visibility, dependency-based option types, conditional installs, flags, ordering, priorities, and selection validation.
- Project selected FOMOD folders into a staging tree during planning, fixing plugins hidden inside selected folders such as `Core\Plugin.esp`.
- Bind referenced FOMOD file states and stop Apply when the dependency environment drifts.
- Ported pyfomod XML parsing to the standard library to support Python 3.14/PyInstaller without its stale `lxml<5` constraint.

## 0.7.0

- Added strict enabled/disabled/unregistered plugin state transitions shared by plan and apply.
- Added schema-v2 plans bound to all three profile files; apply commits the prevalidated profile result and rejects drift.
- Added native transactional `profile apply`, in-place mod toggles, explicit movement, dry-run, and `--unregister-plugin`.
- Added explicit Nexus info/deps/download argument parsing and canonical download syntax.

## 0.6.0

- Packaged the Skill instructions and complete PyInstaller runtime as one shared, self-contained Bundle for Claude Code and Codex.
- Added transactional adapter installation with stable `%LOCALAPPDATA%` deployment, junction migration, backups, and managed uninstall.
- Added Nexus file metadata freezing and safe `meta.ini` create/merge/validation, including literal installed-file IDs.
- Added same-folder update plans that preserve Mod position and enabled state, preserve existing plugin states, disable newly introduced plugins, and remove retired plugin entries.
- Added SHA-256 post-commit content audits with rollback of the old Mod and all three profile files on failure.
- Made the official Nexus filename authoritative and made archive movement safe for same-path and collision cases.
- Disabled legacy mutating ordinary install/update routes in favor of the canonical inspect/plan/apply transaction.

## 0.5.0

- Unified wrapper-directory detection across inspect, plan, apply, legacy inspection, and Nexus verification.
- Added staged final-root validation and authoritative post-flatten plugin scanning before commit.
- Made mod placement an explicit LLM decision with exact anchors/top/bottom and reverse-order audit output.
- Added transactional rollback coverage for the mod folder and all three MO2 profile files.

## 0.4.1

- Bound NPC appearance candidates and decisions to an exact source plugin as well as the MO2 mod and FaceGen hashes.
- Reject record-less FaceGen candidates from automatic generation.
- Enforce that the selected appearance plugin belongs to the selected MO2 mod and overrides the requested NPC.
- Distinguish multiple appearance plugins in one MO2 mod and add protocol timeout/error diagnostics.

## 0.4.0

- Added versioned NPC sidecar protocol and authoritative structured appearance decisions.
- Added immutable decided plans and selected loose FaceGen hash verification.
- Preserved legacy npc-agent-patcher CLI compatibility.

# Changelog

## 0.3.0
- Added real inspect/plan/apply/resume installation subcommands.
- Blocked legacy FOMOD installs and added cross-format archive safety checks.
- Added explicit FOMOD selections, transactional profile audit, and post-commit archiving.
- Added structured Nexus dependency sessions and metadata-based download matching.
- Added archive retry and synchronized agent guidance.

## 0.2.0
- Added DPAPI Nexus authentication and initial standalone workflow.

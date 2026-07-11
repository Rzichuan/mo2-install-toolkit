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

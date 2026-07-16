## Unreleased

## 0.10.3 - 2026-07-16

- Discover the latest stable installer version through the fixed-name `mo2-installer-manifest.json` Release asset instead of the anonymous GitHub REST API.
- Strictly validate manifest schema, version, tag, platform, asset names, and SHA-256 values before changing user directories; fail closed with tagged-installer guidance.
- Download only the manifest and two ZIP assets by default while preserving explicit `-Version` compatibility with adjacent `.sha256` files.
- Generate and publish the installer manifest from the packaged ZIP hashes, and cover default/offline installation plus malformed-manifest failures on Windows PowerShell 5.1.

## 0.10.2 - 2026-07-16

- Preserve the previous managed Skill when installation fails before the replacement Skill is committed.
- Restore standard PowerShell `-WhatIf` and `-Confirm` behavior while retaining compatibility with `irm ... | iex`.
- Exercise real `Invoke-Expression` install/uninstall, WhatIf, and rollback paths in the Windows integration test.

## 0.10.1 - 2026-07-16

- Fix one-command install and uninstall execution through `irm ... | iex`, where PowerShell does not provide the `$PSCmdlet` variable.

## 0.10.0 - 2026-07-16

- Add a one-command Windows installer that auto-detects Codex/Claude, downloads and verifies Skill and runtime Release assets, installs both atomically, and self-tests the pinned runtime.
- Add a safe managed uninstaller, one-command installation documentation, and CI coverage for idempotent install/uninstall.

## 0.9.0 - 2026-07-16

- Make source clones self-bootstrapping through a strictly pinned, SHA-256-verified Windows runtime cache.
- Add native Codex repository marketplace metadata and a root Claude Skill adapter while retaining one authoritative nested Skill.
- Make clean-checkout builds self-contained by moving the NPC patcher sidecar into this repository.
- Publish versioned win-x64 runtime payloads and checksums from tag-driven CI; Release assets are bootstrap dependencies rather than directly installable Skills.
- Preserve locally built full-Bundle adapter installation as an offline and compatibility path.

- Add lightweight `simple`, `data-folder`, and `fomod` handler reporting without introducing a virtual file tree.
- Promote a top-level `Data/` directory while preserving root documentation.
- Block C# FOMOD, OMOD, NCC, and explicit executable installers from ordinary automatic installation.
- Move MO2 archive `.meta` sidecars together with archived downloads.
- Re-license the project under GPL-3.0-or-later while retaining third-party notices.
- Add a layered Skill tool guide with complete setup, Nexus, install/update, archive, root, Profile, backup, recovery, and exit-handling recipes.

## 0.8.1 - 2026-07-13

- Require every CLI installation plan to provide an explicit, reviewed `--name` instead of silently deriving a MO2 folder name from the archive.
- Summarize active-Profile category prefixes, naming examples, lexical related-mod candidates, and a dependency/family/conflict/category placement decision order in plan output.
- Require `--placement-reason` whenever a new-install placement is supplied, making the agent record why the exact anchor or fallback position was chosen.
- Strengthen the Skill and agent contract so agents follow the user's established naming taxonomy, preserve a recognizable original title, group related mods, and justify overwrite direction before confirmation.

## 0.8.0 - 2026-07-12

- Classify PyFomod validation warnings through a product policy layer: XML comments are advisory and ignored during resolution, while syntax errors, invalid enums, missing required attributes, and invalid option constraints remain blocking.
- Strictly validate selections JSON as an object of string group IDs to arrays of string option IDs; malformed JSON, schema violations, and unknown stable IDs are input errors with field diagnostics and examples.
- Preserve archive spelling in FOMOD `source`, add `canonical_source` and `case_variant`, and continue recognizing the canonical path case-insensitively.
- Suggest safe tag-stripped or bounded-suffix anchor candidates with exact names and `modlist.txt` line numbers, without ever auto-selecting a non-exact or ambiguous match.
- Add `install apply/resume --auto-replan` for three-file Profile checksum drift. Semantically equivalent replacement plans continue under the existing confirmation; changed semantics return `replan_review_required` with a new plan ID and JSON-path differences without modifying MO2.
- Keep plan schema v2 and JSON envelope schema v1 backward compatible while adding structured warning and Apply `replan` fields.

## 0.7.2 - 2026-07-12

- Reject FOMOD source and destination paths that are absolute, drive-relative, UNC, traversal, ADS-like, or escape staging boundaries.
- Resolve FOMOD file dependencies against enabled mods, MO2 Overwrite, and a validated game Data directory; stop safely when a missing dependency is ambiguous.
- Capture PyFomod parser and structural validation warnings, block critical repairs, and bind the dependency environment through Apply.

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

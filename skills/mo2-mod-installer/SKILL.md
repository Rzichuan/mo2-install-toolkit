---
name: mo2-mod-installer
description: Safely inspect, plan, install, update, validate, back up, or restore Skyrim SE/AE mods in Mod Organizer 2 with the bundled mo2-tool CLI.
---

# MO2 Mod Installer

Use the `bin/mo2-tool.exe` shipped inside this loaded Skill Bundle as the only mutation engine. Never edit MO2 profile files or move installed mods directly.

## Tool location

- `bin` is relative to the directory containing this `SKILL.md`, never to the shell's current working directory.
- Claude Code must invoke `$HOME/.claude/skills/mo2-mod-installer/bin/mo2-tool.exe`; Codex must invoke `$HOME/.codex/skills/mo2-mod-installer/bin/mo2-tool.exe`. Resolve the full absolute path before the first command and keep using that exact executable.
- On Windows always include `.exe`. Never call `bin/mo2-tool`, search a source checkout's `dist` directory, copy the executable, or fall back to another `mo2-tool` on `PATH`.
- Require `bin/mo2-tool.exe` and `bin/_internal` to exist. If either is missing, stop and report a damaged Bundle rather than attempting repair during a mod operation.
- Command examples below abbreviate the resolved absolute executable as `mo2-tool`; substitute the full Skill path when executing them.

## Required installation flow

1. Run `mo2-tool doctor --json`. Resolve configuration first and close MO2 before any mutation.
2. Resolve Nexus metadata/dependencies when applicable.
3. Run `mo2-tool install inspect <archive> --json`. Read `layout.handler`, `layout.support_status`, `layout.installer_risk`, `layout.nesting_root`, `layout.flatten`, `layout.effective_root_entries`, FOMOD choices, and manual follow-up advice. Continue only for supported `simple`, `data-folder`, or XML `fomod` handling. A `data-folder` result means the top-level `Data/` will be promoted while root documentation is preserved. Stop before plan/apply for `risky` or `unsupported`; never execute C# FOMOD, OMOD, NCC, or explicit installer entry points. Route recognized game-root packages to `root inspect/deploy`, never ordinary install.
4. Determine a final MO2 name from the mod purpose and the active Profile’s established taxonomy, then run `mo2-tool install plan <archive> --name "<reviewed classified name>" [--selections selections.json] [--modid <id> --file-id <id>] --json`. A selections file must be a JSON object of string group IDs to arrays of string option IDs, for example `{"0:0":["0:0:0"]}`. For Nexus files, both IDs are required together so the plan freezes official source metadata. The plan returns current `modlist_context`: file order, observed naming categories/examples, separators and positions, conflict providers, lexical related-mod evidence, and the reverse-order explanation.
5. The agent must choose priority from evidence rather than using a generic default. For a new install, choose exactly one explicit file-direction placement and provide `--placement-reason "<why this adjacency and overwrite direction are correct>"`: `--before-mod <name>`, `--after-mod <name>`, `--modlist-top`, or `--modlist-bottom`. For an auto-detected same-folder update, require `placement.mode=preserve_existing` and do not provide any placement flag.
6. Present the proposed classified name, naming rationale, related-mod grouping, exact neighbors, overwrite direction, layout, selections, source metadata, operation, and plugins to the user. After one explicit confirmation, run `mo2-tool install apply <plan-id> --yes <placement> --placement-reason "<reviewed rationale>" --json` for a new install, or omit placement and placement reason for an in-place update.
7. Read the returned `final_placement` adjacency and `profile_audit`. Run `mo2-tool profile audit --json` for the normal post-write audit.

`before_mod` and `after_mod` are defined in `modlist.txt` file direction. Earlier file lines mean higher MO2 priority and a lower visible left-pane position. The result reports both file-direction neighbors and the corresponding MO2 left-pane neighbors.

## Naming and placement policy

- Every new installation needs an explicit final `--name`. Never pass through the archive filename unchanged merely because it is convenient. Inspect the mod description/metadata, selected files and plugins, then follow `modlist_context.naming_conventions` and the active Profile's dominant pattern. For this Profile that normally means an established `[category]`, a concise Chinese functional label when that is the prevailing style, `——`, and a recognizable original English title. Reuse an existing category whenever it fits; do not invent a parallel taxonomy.
- Treat naming and placement as one organization decision. Keep base mods, patches, addons, framework components, animation packs, appearance families, and other clearly related mods adjacent whenever overwrite semantics permit.
- Choose placement in this order: exact base/patch dependency; same mod family/framework; intentional conflict-provider overwrite; closest functional peers in the same established category block; only then a generic separator/top/bottom fallback. State the evidence and intended overwrite direction in `--placement-reason`.
- Do not infer priority from archive name, Nexus category, or file type alone. Combine Nexus purpose/dependencies, FOMOD choices, plugins, selected paths, file-conflict providers, related candidates, and current Profile structure. Lexical `related_mods` are candidates, not automatic truth.
- For this user's fixed output group, place an ordinary mod after `—————— 其他模组生成 ——————_separator` only when no stronger related-mod/category placement exists and explain that fallback. Put a mod inside the generated-output group only when the user explicitly identifies it as generated output.
- A missing or duplicated anchor is a hard stop. Suggested `candidates` (exact names, reasons, and `modlist.txt` lines) are review hints only; never substitute one automatically or retry at highest priority.
- For multiple `--enable-mod` arguments to `profile apply`, pass them in high-to-low MO2 priority order and provide one exact mod anchor/top/bottom option. Untouched mods retain relative order.

## Staging and transaction guarantees

- Apply extracts under the transaction directory, applies the planned single-wrapper flattening, top-level `Data/` promotion, or XML FOMOD selection, and validates the final staged root before touching `mods/`. It does not construct or emulate MO2's virtual file tree.
- An ordinary mod must expose at least one plugin/BSA or standard Data directory at its final root. Invalid staging returns current root entries, suspected wrappers, and paths to inspect.
- Plugin activation comes from a fresh scan of the final staged tree, not archive inspection guesses.
- Nexus `meta.ini` is created or merged in staging, unknown existing keys are preserved, and the official Mod/file IDs, filename, version, and installed-file identity are validated after commit.
- Committed content (excluding generated `meta.ini`) is compared to the staged SHA-256 manifest before success is reported.
- Mod replacement, mod activation, plugin activation, load order, placement, and audit are one transaction. Failure restores the old mod plus `modlist.txt`, `plugins.txt`, and `loadorder.txt`.
- `install apply/resume --auto-replan` handles only checksum drift in the three Profile files. It may continue under the existing confirmation only when the replacement plan is semantically equivalent; `replan_review_required` means review and explicitly apply the returned new plan. It never bypasses archive drift, a running MO2/Skyrim process, or illegal plan state.


## Same-folder updates

- Identify an update by an exact existing Mod folder/profile entry. Ambiguous, missing, or duplicated identity is a hard stop.
- Preserve the exact `modlist.txt` position and the existing `+`/`-` state. Reject explicit placement flags and stop if profile adjacency/state drifted since planning.
- Preserve states for retained plugins. Add newly introduced plugins to `plugins.txt` disabled by default and remove disappeared plugins from both `plugins.txt` and `loadorder.txt`.
- Treat the old Mod folder, `modlist.txt`, `plugins.txt`, and `loadorder.txt` as one rollback unit. Metadata or content audit failure restores all four.
- Legacy mutating `install legacy` and top-level `update` are disabled; their `--dry-run` compatibility mode is read-only. Use canonical inspect/plan/apply for mutations.

## Profile apply

Use exact mod placement for direct profile changes:

```text
mo2-tool profile apply <profile> --enable-mod "Mod A" --enable-mod "Mod B"   --after-mod "—————— 其他模组生成 ——————_separator"
```

`Mod A`, then `Mod B`, is high-to-low MO2 priority. Plugin positioning remains separately controlled by `--after-plugin`.

## Manual follow-up and exceptions

Always report `manual_post_install_steps`, including an empty list. They are recommendations only. Never run BodySlide, Pandora, Nemesis, or FNIS unless explicitly requested in the current turn. Use dedicated generated-output mods rather than `Overwrite`.

SKSE and Engine Fixes root/AIO packages use `root inspect`, `root deploy --dry-run`, confirmation, then `root deploy --yes`. Unknown root signatures are safety blocks. Nexus credentials must remain in Windows DPAPI and never appear in chat, arguments, logs, or JSON.

## FOMOD validation contract

Treat `CommentsPresentWarning` as advisory: comment contents are ignored even when `upstream_critical` is true. Trust the toolkit's final `blocking`, `critical`, and `advisory` fields; syntax and semantic-changing validation failures remain blocking. `fomod.source` preserves archive spelling, while `canonical_source` and `case_variant` explain canonical-path recognition.

## Result contract

JSON envelopes use `schema_version`, `tool_version`, `status`, `warnings`, `errors`, and `data`. Exit 0 is success, 1 review/warning, 2 input/configuration error, 3 safety block, 4 network error, 5 filesystem/tool error, and 10 internal error. Read `references/agent-contract.md` for automation details.

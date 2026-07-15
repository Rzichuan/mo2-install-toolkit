---
name: mo2-mod-installer
description: Safely inspect, plan, install, update, validate, archive, back up, or restore Skyrim SE/AE mods in Mod Organizer 2 with a version-pinned mo2-tool runtime that bootstraps automatically.
---

# MO2 Mod Installer

Use only the absolute `mo2-tool.exe` path returned by the runtime bootstrap as the mutation engine. Never edit MO2 profile files, move installed mods, or emulate MO2's virtual file tree directly.

## Tool bootstrap and location

- Resolve this `SKILL.md` to an absolute path. Before the first CLI-backed operation in a task, run `powershell.exe -NoProfile -ExecutionPolicy Bypass -File <skill-directory>\scripts\ensure-runtime.ps1 -Json`.
- Parse the bootstrap JSON and continue only when it exits `0`, reports `status=ready`, and returns an absolute `tool_path`. Use only that returned `mo2-tool.exe` path for the rest of the task.
- The bootstrap accepts a locally built complete Bundle beside this Skill, a matching versioned runtime cache, or a matching legacy shared Bundle. Otherwise it downloads the pure runtime payload pinned by `runtime-manifest.json`, verifies SHA-256, `runtime.json`, and `--version`, and caches it under `%LOCALAPPDATA%\MO2AgentToolkit\runtimes`. The Release payload is not itself a Skill/plugin.
- Do not download for a documentation-only answer. Do not modify the manifest, use a `latest` Release, search `dist`, copy an executable by itself, or fall back to another `mo2-tool` on `PATH`.
- On bootstrap exit `2`, `3`, `4`, or `5`, stop and report its structured errors and actionable cache/network guidance. Never bypass a checksum or version failure.
- Examples abbreviate the returned absolute executable as `mo2-tool`; substitute `tool_path` when executing them.

## Canonical installation workflow

1. Run `mo2-tool doctor --json`. Use `setup --json` only when configuration is absent. Close MO2 and game-related processes before mutation.
2. For Nexus sources, resolve metadata and dependencies, then obtain the archive through the supported Premium or official browser-assisted flow.
3. Run `mo2-tool install inspect <archive> --json` and branch on `layout.handler`, `layout.support_status`, and `layout.installer_risk`.
4. Inspect the mod purpose, archive contents, selected FOMOD files, plugins, and active Profile taxonomy. Choose an explicit final MO2 `--name`; never pass through the archive filename merely for convenience.
5. Run `mo2-tool install plan <archive> --name "<reviewed name>" [--selections selections.json] [--modid <id> --file-id <id>] --json`. Use `--full-context` only when the concise placement context is insufficient.
6. Choose placement from dependency, patch/base, same-family, conflict-provider, and Profile-category evidence. Present the name, rationale, exact neighbors, overwrite direction, layout, selections, source metadata, operation, and plugins to the user.
7. After one explicit confirmation, apply a new install with exactly one placement plus `--placement-reason`, or apply an auto-detected same-folder update without placement arguments.
8. Read `final_placement`, `profile_audit`, `archive_result`, and `manual_post_install_steps`; then run `mo2-tool profile audit --json`.

Read `references/tool-usage.md` for exact command recipes and failure handling. Read `references/agent-contract.md` when consuming JSON, automating Apply/Resume, or validating transaction semantics.

## Archive routing

| Inspect result | Agent action |
|---|---|
| supported `simple` | Continue through plan/apply. A single ordinary wrapper may be flattened. |
| supported `data-folder` | Continue. Promote the one top-level `Data/` directory and preserve root documentation. |
| supported XML `fomod` | Require explicit stable selections, then plan only the resolved files. |
| `risky` or `unsupported` | Stop before plan/apply and report `installer_risk`/`support_reason`. |
| recognized game-root package | Route to `root inspect/deploy`, never ordinary install. |

Never execute C# FOMOD, OMOD, NCC, or explicit setup/install entry points. An ordinary staged mod must expose a plugin/BSA or standard Data directory at its final root. Missing or duplicate placement anchors and invalid staged roots are hard stops; returned candidates are review hints, never automatic authorization.

## Naming and placement

- Follow `modlist_context.naming_conventions` and the active Profile's established taxonomy. Reuse an existing category, follow the prevailing localized-description style, and retain a recognizable original title.
- Keep base mods, patches, addons, framework components, animation packs, appearance families, and other clearly related mods adjacent when overwrite semantics permit.
- Prefer placement evidence in this order: exact dependency/base relationship; same family/framework; intentional conflict order; closest functional peer in the established category; reviewed fallback separator.
- **Placement direction (`--before-mod` / `--after-mod`):** The CLI flags use `modlist.txt` file order. `modlist.txt` line 1 = MO2 left-pane **bottom** = **highest** priority (loaded last, wins conflicts). The file and the UI are exact inverses:

  | modlist.txt line | MO2 left-pane position | Priority |
  |---|---|---|
  | 1 (top of file) | **Bottom** of pane | **Highest** (wins) |
  | ↓ later lines | ↑ higher in pane | ↓ lower |
  | Last line | **Top** of pane | **Lowest** |

  `--before-mod X` = insert earlier in modlist.txt → **below** X in left pane → **higher** priority than X.
  `--after-mod X` = insert later in modlist.txt → **above** X in left pane → **lower** priority than X.

  **Dependency rule:** A mod that depends on X must load *after* X → it needs **higher** priority → place it **below** X in the left pane → use `--before-mod X`. Example: *Audio Occlusion depends on Address Library →* `--before-mod "Address Library for SKSE Plugins"`.

  After placement, always verify `final_placement.mo2_left_pane`: the dependent mod must appear as `below_mod` relative to its dependency. If the plan shows the dependency as `below_mod` instead, you used the wrong flag — re-plan with the opposite direction.
- Do not infer placement from a similar name, Nexus category, or file type alone. A missing or duplicated exact anchor is a hard stop.
- For this user's fixed fallback, place an ordinary mod after `—————— 其他模组生成 ——————_separator` only when no stronger placement exists. Put a mod inside the generated-output group only when the user explicitly identifies it as generated output.

## FOMOD and same-folder updates

- A selections file is a JSON object of string group IDs to arrays of string option IDs, for example `{"0:0":["0:0:0"]}`. Schema errors and unknown IDs are exit-2 input errors; never install every file as fallback.
- Treat final `blocking`, `critical`, and `advisory` fields as authoritative. XML comments are advisory and ignored; syntax or semantic-changing validation failures remain blocking.
- Identify updates by an exact existing Mod folder/Profile entry. Preserve its exact position and enabled/disabled marker; reject ambiguous identity or state/adjacency drift.
- Preserve retained plugin states, add newly introduced plugins disabled when the mod is enabled, leave them unregistered when it is disabled, and remove disappeared plugins from `plugins.txt` and `loadorder.txt`.
- Legacy mutating `install legacy` and top-level `update` are disabled. Only their read-only dry-run compatibility remains; use inspect/plan/apply for every mutation.

## Mutation and recovery guarantees

- Apply extracts and resolves content under a transaction directory, validates staging, rescans plugins, creates/merges Nexus `meta.ini`, and verifies a SHA-256 manifest before reporting success.
- Mod replacement, mod activation, plugin states, load order, placement, and Profile audit are one transaction. Failure restores the old Mod plus `modlist.txt`, `plugins.txt`, and `loadorder.txt`.
- `install apply/resume --auto-replan` handles only checksum drift in those three Profile files. Continue under the existing confirmation only for a semantically equivalent replacement; `replan_review_required` requires review and an explicit Apply of the returned plan.
- Archive drift, running processes, illegal plan state, and safety exit 3 are never bypassed.
- Post-commit archive movement is separate from the MO2 transaction. Report warnings and use `archive retry`; do not reinstall an already committed mod merely because archiving failed.

## Other supported flows

- Profile mutations: run `profile apply ... --dry-run --json`, confirm, apply, then audit. Mod placement is explicit. Plugin actions support enabled, disabled, and unregistered states; the CLI does not reorder plugins.
- Game-root packages: `root inspect`, `root deploy --dry-run`, confirmation, then `root deploy --yes`. Unknown signatures are safety blocks.
- Backup restore: list, inspect the manifest, obtain explicit confirmation, then restore.
- Always report `manual_post_install_steps`, including an empty list. Never run BodySlide, Pandora, Nemesis, or FNIS without an explicit current-turn request; use dedicated generated-output mods rather than `Overwrite`.
- Nexus credentials remain protected by Windows DPAPI and must never appear in chat, arguments, logs, or JSON.
- NPC FaceGen work is outside this Skill's installation guide; use the dedicated NPC conflict Skill.

## Result contract

JSON envelopes use `schema_version`, `tool_version`, `status`, `warnings`, `errors`, and `data`. Exit 0 is success, 1 review/warning, 2 input/configuration error, 3 safety block, 4 network error, 5 filesystem/tool error, and 10 internal error. Never parse human output when JSON is available.

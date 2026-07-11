---
name: mo2-mod-installer
description: Safely inspect, plan, install, update, validate, back up, or restore Skyrim SE/AE mods in Mod Organizer 2 with the bundled mo2-tool CLI.
---

# MO2 Mod Installer

Use bundled `mo2-tool` as the only mutation engine. Never edit MO2 profile files or move installed mods directly.

## Required installation flow

1. Run `mo2-tool doctor --json`. Resolve configuration first and close MO2 before any mutation.
2. Resolve Nexus metadata/dependencies when applicable.
3. Run `mo2-tool install inspect <archive> --json`. Read `layout.nesting_root`, `layout.flatten`, `layout.effective_root_entries`, FOMOD choices, and manual follow-up advice. Route recognized game-root packages to `root inspect/deploy`, never ordinary install.
4. Run `mo2-tool install plan <archive> [--selections selections.json] --json`. The plan returns current `modlist_context`: file order, separators and positions, conflict providers, related evidence, and the reverse-order explanation.
5. The tool does not infer priority. Choose exactly one explicit file-direction placement from evidence: `--before-mod <name>`, `--after-mod <name>`, `--modlist-top`, or `--modlist-bottom`.
6. Present layout, selections, replacement, plugins, and explicit placement to the user. After one explicit confirmation, run `mo2-tool install apply <plan-id> --yes <placement> --json`.
7. Read the returned `final_placement` adjacency and `profile_audit`. Run `mo2-tool profile audit --json` for the normal post-write audit.

`before_mod` and `after_mod` are defined in `modlist.txt` file direction. Earlier file lines mean higher MO2 priority and a lower visible left-pane position. The result reports both file-direction neighbors and the corresponding MO2 left-pane neighbors.

## Placement policy

- Never guess priority from archive name, Nexus category, or file type. The LLM chooses from dependencies, conflicts, and current profile structure; the tool only executes an exact decision.
- For this user's fixed output group, place an ordinary mod after `—————— 其他模组生成 ——————_separator` in `modlist.txt` file direction. Put a mod inside the generated-output group only when the user explicitly identifies it as generated output.
- A missing or duplicated anchor is a hard stop. Never retry by placing the mod at highest priority.
- For multiple `--enable-mod` arguments to `profile apply`, pass them in high-to-low MO2 priority order and provide one exact mod anchor/top/bottom option. Untouched mods retain relative order.

## Staging and transaction guarantees

- Apply extracts under the transaction directory, applies the planned single-wrapper flattening/FOMOD selection, and validates the final staged root before touching `mods/`.
- An ordinary mod must expose at least one plugin/BSA or standard Data directory at its final root. Invalid staging returns current root entries, suspected wrappers, and paths to inspect.
- Plugin activation comes from a fresh scan of the final staged tree, not archive inspection guesses.
- Mod replacement, mod activation, plugin activation, load order, placement, and audit are one transaction. Failure restores the old mod plus `modlist.txt`, `plugins.txt`, and `loadorder.txt`.

## Profile apply

Use exact mod placement for direct profile changes:

```text
mo2-tool profile apply <profile> --enable-mod "Mod A" --enable-mod "Mod B"   --after-mod "—————— 其他模组生成 ——————_separator"
```

`Mod A`, then `Mod B`, is high-to-low MO2 priority. Plugin positioning remains separately controlled by `--after-plugin`.

## Manual follow-up and exceptions

Always report `manual_post_install_steps`, including an empty list. They are recommendations only. Never run BodySlide, Pandora, Nemesis, or FNIS unless explicitly requested in the current turn. Use dedicated generated-output mods rather than `Overwrite`.

SKSE and Engine Fixes root/AIO packages use `root inspect`, `root deploy --dry-run`, confirmation, then `root deploy --yes`. Unknown root signatures are safety blocks. Nexus credentials must remain in Windows DPAPI and never appear in chat, arguments, logs, or JSON.

## Result contract

JSON envelopes use `schema_version`, `tool_version`, `status`, `warnings`, `errors`, and `data`. Exit 0 is success, 1 review/warning, 2 input/configuration error, 3 safety block, 4 network error, 5 filesystem/tool error, and 10 internal error. Read `references/agent-contract.md` for automation details.

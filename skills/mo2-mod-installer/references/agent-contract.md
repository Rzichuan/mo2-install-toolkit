# Agent contract

Resolve `bin/mo2-tool.exe` relative to the loaded `mo2-mod-installer` Skill directory and invoke that absolute path with the `.exe` suffix. Claude Code uses `$HOME/.claude/skills/mo2-mod-installer/bin/mo2-tool.exe`; Codex uses `$HOME/.codex/skills/mo2-mod-installer/bin/mo2-tool.exe`. Never resolve `bin` from the current working directory, search `dist`, copy the executable, or fall back to `PATH`. A missing executable or `_internal` directory means the Bundle is damaged and is a hard stop. Always request JSON for discovery, inspection, planning, apply, and audit. Exit 1 is review, not a crash. Never bypass safety exit 3. Never parse human output when JSON exists or expose DPAPI credentials.

## Ordinary MO2 installation

Required sequence: `doctor`, `install inspect`, `install plan`, operation/placement review, user confirmation, `install apply --yes`, then `profile audit`. Nexus plans pass `--modid` and `--file-id` together and bind official filename/version metadata.

For a new install, exactly one placement argument is required: `--before-mod`, `--after-mod`, `--modlist-top`, or `--modlist-bottom`, all in `modlist.txt` file direction. For an auto-detected same-folder update, `placement.mode` is `preserve_existing`; apply without a placement argument. Do not derive placement from names/categories. Use returned `modlist_context`. For the fixed generated-output separator, ordinary mods go after `—————— 其他模组生成 ——————_separator`; only explicitly identified generated outputs belong in the output group.

Inspect, plan, and apply must agree on `layout.nesting_root`, `layout.flatten`, and `layout.effective_root_entries`. Apply stages and validates before commit, rescans staged plugins, creates/merges Nexus `meta.ini`, then commits the Mod and three profile files as one transaction. It validates metadata and a staged SHA-256 content manifest after commit. Missing/duplicate anchors and invalid staged roots stop without fallback. Audit `final_placement` neighbors after success.

FOMOD archives require explicit stable option IDs in a selections JSON. Never install every file as fallback. A mutation requires MO2 closed; `install resume` may be used after a running-process safety block, with the original explicit confirmation and placement still required.


For same-folder updates, preserve exact Mod adjacency and its enabled/disabled marker. Preserve retained plugin states, add newly introduced plugins disabled, and remove disappeared plugins from `plugins.txt` and `loadorder.txt`. Abort on state drift. Any staging, profile, metadata, or content-audit failure restores the old Mod and all three profile files. Legacy mutating install/update commands are safety-blocked; only their read-only dry-run compatibility is allowed.

## Other flows

Game-root sequence: doctor, `root inspect`, `root deploy --dry-run`, explicit confirmation, `root deploy --yes`, backup inspection. Unknown signatures are never forced.

Non-Premium Nexus sequence: batch prepare, user completes official Slow Download, batch collect, then the ordinary inspect/plan/apply flow. Never automate browser restrictions.

Backup restore requires manifest inspection and explicit confirmation. Post-install generator advice is non-blocking and never executed without a current-turn request.

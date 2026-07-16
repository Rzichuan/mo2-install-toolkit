# Agent contract

Use `tool-usage.md` for exact command recipes, operator-facing branch handling, and recovery examples. This document defines the stable automation and safety contract.

Resolve `bin/mo2-tool.exe` relative to the loaded `mo2-mod-installer` Skill directory and invoke that absolute path with the `.exe` suffix. Claude Code uses `$HOME/.claude/skills/mo2-mod-installer/bin/mo2-tool.exe`; Codex uses `$HOME/.codex/skills/mo2-mod-installer/bin/mo2-tool.exe`. Never resolve `bin` from the current working directory, search `dist`, copy the executable, or fall back to `PATH`. A missing executable or `_internal` directory means the Bundle is damaged and is a hard stop. Always request JSON for discovery, inspection, planning, apply, and audit. Exit 1 is review, not a crash. Never bypass safety exit 3. Never parse human output when JSON exists or expose DPAPI credentials.

## Environment configuration

Start every environment check with `doctor --json`. When configuration is missing or invalid, or paths are intentionally changing, `setup --dry-run --json` is the only permitted discovery command. Discovery is read-only. Present the MO2 instance root, derived `mods` directory, Profile, game directory, download directory, archive directory, and 7-Zip path as one concrete summary. Obtain explicit confirmation of those values in the current conversation flow before any configuration write. One candidate, a default, prior confirmation, silence, or agent judgment does not grant authorization.

After confirmation, run setup with explicit `--instance` and `--profile` and the confirmed `--game` and `--seven-zip` values; apply confirmed download/archive preferences explicitly with `config set`. Bare `setup --json` is prohibited for agent workflows even though the CLI retains it for compatibility. Finish with `config show --json` and `doctor --json`. Existing valid configuration requires no new confirmation if no path is changing. When Doctor reports an invalid configured path, show its current value alongside discovered alternatives and never replace it autonomously.

## Ordinary MO2 installation

Required sequence: `doctor`, `install inspect`, classify and explicitly name the mod, `install plan --name`, naming/operation/related-placement review, user confirmation, `install apply --yes`, then `profile audit`. Nexus plans pass `--modid` and `--file-id` together and bind official filename/version metadata.

Every CLI plan requires an explicit reviewed `--name`. Derive it from mod purpose plus `modlist_context.naming_conventions`, not from the archive basename alone. Follow the active Profile's established category and localized-description style while retaining a recognizable original title. Updates pass the exact existing Mod name so identity and position are preserved. Present the name and rationale before confirmation.

For a new install, exactly one placement argument is required: `--before-mod`, `--after-mod`, `--modlist-top`, or `--modlist-bottom`, all in `modlist.txt` file direction. For an auto-detected same-folder update, `placement.mode` is `preserve_existing`; apply without a placement argument. Do not derive placement from names/categories alone. Use dependencies, patch/base relationships, conflict providers, selected content, `related_mods`, category blocks, and exact current neighbors from `modlist_context`. Prefer adjacency with the exact base mod, then the same family/framework, then intended conflict order, then functional peers in the same category. A generic separator is last resort. Every new-install placement requires `--placement-reason`, which must state the evidence and overwrite direction. For the fixed generated-output separator, ordinary mods go after `—————— 其他模组生成 ——————_separator`; only explicitly identified generated outputs belong in the output group.

Inspect, plan, and apply must agree on `layout.handler`, `layout.support_status`, `layout.nesting_root`, `layout.flatten`, and `layout.effective_root_entries`. Continue automatically only for supported `simple`, `data-folder`, or XML `fomod` handling. `data-folder` promotes one top-level `Data/` while preserving root documentation; no MO2 virtual file tree is constructed. If `support_status` is `risky` or `unsupported`, stop before plan/apply and report `layout.installer_risk`; never execute C# FOMOD, OMOD, NCC, or explicit installer entry points. Apply stages and validates before commit, rescans staged plugins, creates/merges Nexus `meta.ini`, then commits the Mod and three profile files as one transaction. It validates metadata and a staged SHA-256 content manifest after commit. Missing/duplicate anchors and invalid staged roots stop without fallback. Anchor `candidates` are bounded, exact-name suggestions with reasons and line numbers; they are never authorized placement. Audit `final_placement` neighbors after success.

FOMOD archives require explicit stable option IDs in a selections JSON shaped like `{"0:0":["0:0:0"]}`: an object of string group IDs to arrays of string option IDs. Schema violations and unknown IDs are exit-2 input errors. Never install every file as fallback. XML comments are advisory and ignored; use final `blocking`/`critical`/`advisory` fields rather than PyFomod `upstream_critical`. Syntax and semantic-changing validation failures remain blocking. `source` preserves archive case; `canonical_source` and `case_variant` report canonical recognition. A mutation requires MO2 closed; `install resume` may be used after a running-process safety block, with the original explicit confirmation and placement still required.


`install apply` and `install resume` accept `--auto-replan` only for checksum drift in the three Profile files. Equivalent replacements continue within the already confirmed Apply and report original/effective plan IDs. A semantic change returns exit 1, `replan_review_required`, a new plan ID, and JSON-path differences without MO2 writes; review and explicitly apply that new plan. Archive drift, running processes, and illegal plan states remain safety stops. Plan schema stays v2 and envelope schema stays v1.

For same-folder updates, preserve exact Mod adjacency and its enabled/disabled marker. Preserve retained plugin states including unregistered; add newly introduced plugins disabled only when the mod is enabled (otherwise leave them unregistered), and remove disappeared plugins from `plugins.txt` and `loadorder.txt`. Abort on state drift. Any staging, profile, metadata, or content-audit failure restores the old Mod and all three profile files. Legacy mutating install/update commands are safety-blocked; only their read-only dry-run compatibility is allowed.

## Other flows

Game-root sequence: doctor, `root inspect`, `root deploy --dry-run`, explicit confirmation, `root deploy --yes`, backup inspection. Unknown signatures are never forced.

Non-Premium Nexus sequence: batch prepare, user completes official Slow Download, batch collect, then the ordinary inspect/plan/apply flow. Never automate browser restrictions.

Backup restore requires manifest inspection and explicit confirmation. Post-install generator advice is non-blocking and never executed without a current-turn request.

Profile mutation uses native `profile apply`: mod toggles are in-place unless an explicit anchor is supplied; plugin actions map to enabled/disabled/unregistered. Use `--dry-run --json` before writes. Plan output is concise by default; request `--full-context` only when the complete mod list context is needed.

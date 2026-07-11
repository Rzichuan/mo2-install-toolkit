# Agent contract

Locate `mo2-tool.exe` under the release `bin` directory or `mo2-tool` on PATH. Always request JSON for discovery, inspection, planning, apply, and audit. Exit 1 is review, not a crash. Never bypass safety exit 3. Never parse human output when JSON exists or expose DPAPI credentials.

## Ordinary MO2 installation

Required sequence: `doctor`, `install inspect`, `install plan`, explicit LLM placement, user confirmation, `install apply --yes` with exactly one placement argument, then `profile audit`.

The placement arguments are `--before-mod`, `--after-mod`, `--modlist-top`, and `--modlist-bottom`, all in `modlist.txt` file direction. Do not derive placement from names/categories. Use returned `modlist_context`. For the fixed generated-output separator, ordinary mods go after `—————— 其他模组生成 ——————_separator`; only explicitly identified generated outputs belong in the output group.

Inspect, plan, and apply must agree on `layout.nesting_root`, `layout.flatten`, and `layout.effective_root_entries`. Apply stages and validates before commit, rescans staged plugins, then commits the mod and three profile files as one transaction. Missing/duplicate anchors and invalid staged roots stop without fallback. Audit `final_placement` neighbors after success.

FOMOD archives require explicit stable option IDs in a selections JSON. Never install every file as fallback. A mutation requires MO2 closed; `install resume` may be used after a running-process safety block, with the original explicit confirmation and placement still required.

## Other flows

Game-root sequence: doctor, `root inspect`, `root deploy --dry-run`, explicit confirmation, `root deploy --yes`, backup inspection. Unknown signatures are never forced.

Non-Premium Nexus sequence: batch prepare, user completes official Slow Download, batch collect, then the ordinary inspect/plan/apply flow. Never automate browser restrictions.

Backup restore requires manifest inspection and explicit confirmation. Post-install generator advice is non-blocking and never executed without a current-turn request.

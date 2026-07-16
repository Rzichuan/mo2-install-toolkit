# MO2 Agent Toolkit

[**English**](README.md) | [简体中文](README.zh-CN.md)

A Windows x64, agent-neutral toolkit for safe Mod Organizer 2 operations. The repository provides the Skill/plugin, while GitHub Releases provide its pinned runtime dependency; users do not need Python.

## Quick start

Run this single command in Windows PowerShell. It detects Codex and Claude, installs the latest stable Skill and pinned runtime, verifies both SHA-256 checksums, and performs a runtime self-test:

```powershell
irm https://raw.githubusercontent.com/Rzichuan/mo2-install-toolkit/main/install.ps1 | iex
```

No Git, Python, .NET SDK, administrator access, `PATH` edit, or first-use download is required. Start a new agent session after installation. The managed Skill and runtime are stored under `%LOCALAPPDATA%\MO2AgentToolkit`.

If neither client can be detected, or if you want to inspect the script before running it:

```powershell
irm https://raw.githubusercontent.com/Rzichuan/mo2-install-toolkit/main/install.ps1 -OutFile install.ps1
.\install.ps1 -Target Codex       # Codex, Claude, Both, or Auto
```

Pin a reproducible release by downloading the installer from that tag and passing the matching version:

```powershell
irm https://raw.githubusercontent.com/Rzichuan/mo2-install-toolkit/v0.10.1/install.ps1 -OutFile install.ps1
.\install.ps1 -Version 0.10.1
```

Rerun the installer to repair or upgrade. To remove the managed Skill and adapters while preserving configuration, credentials, backups, and runtime caches:

```powershell
irm https://raw.githubusercontent.com/Rzichuan/mo2-install-toolkit/main/uninstall.ps1 | iex
```

Codex marketplace installation and a tagged Claude clone remain supported advanced alternatives. A source clone downloads its pinned runtime on first use; the one-command installer downloads it during installation.

### Runtime Release and offline transfer

The GitHub Release asset `mo2-runtime-v0.10.1-win-x64.zip` is **not** a Skill/plugin or a standalone installer. It is the executable runtime payload that the cloned Skill/plugin downloads automatically. Normal users should use the one-command installer and should not download Release assets manually. The installer consumes both the Skill and runtime assets.

For a machine that must remain offline, first install or clone the matching tagged Skill/plugin on that machine. On another machine, download the runtime ZIP and adjacent `.sha256`, verify the checksum, then extract the archive into the version directory:

```text
%LOCALAPPDATA%\MO2AgentToolkit\runtimes\0.10.1
```

The final metadata path must be `%LOCALAPPDATA%\MO2AgentToolkit\runtimes\0.10.1\mo2-runtime\runtime.json`; do not create a nested `mo2-runtime\mo2-runtime` directory.

The repository's `scripts\build-bundle.ps1` can still create a local complete Bundle under `dist\mo2-mod-installer-bundle`. `scripts\install-adapters.ps1 -BundlePath <local-complete-bundle> -Target Both` remains available for existing installations that want one shared Bundle plus Codex/Claude junctions. This locally built compatibility Bundle is not a GitHub Release asset and is not required for normal clone-based installation.

### Upgrade, troubleshooting, and removal

- Upgrade by installing or cloning a newer tagged Skill/plugin. Each tag downloads only its matching runtime; `latest` is never used, and old caches remain available for rollback.
- Network/proxy failures return bootstrap exit `4`; configure the Windows/PowerShell proxy or transfer the matching verified runtime into the exact versioned cache path described above. Hash, metadata, or version failures return exit `3` and are never bypassed.
- Remove the cloned Skill/plugin through the corresponding agent. Remove an obsolete runtime only by deleting its exact version directory under `%LOCALAPPDATA%\MO2AgentToolkit\runtimes` after confirming no installed Skill still references it.
- Configuration and DPAPI credentials are separate under `%LOCALAPPDATA%\MO2AgentToolkit` and are not removed with a runtime cache.

## Safe installation

```powershell
# $Tool is the absolute path returned by the Skill bootstrap.
& $Tool plan nexus:12345 --json
& $Tool install inspect C:\Downloads\mod.7z --json
& $Tool install plan C:\Downloads\mod.7z --name "[分类] 中文用途——Recognizable Mod Title" --modid 12345 --file-id 67890 --json
# Choose an exact anchor from modlist_context, show it to the user, and confirm once:
& $Tool install apply <plan-id> --yes --after-mod "<exact related mod or reviewed fallback>" --placement-reason "<relationship and intended overwrite direction>" --json
& $Tool profile audit --json
```

Nexus may require non-Premium users to download files manually. The toolkit does not bypass Nexus restrictions.


Automatic archive handling is deliberately small: ordinary packages use `handler=simple`, a single top-level `Data/` uses `handler=data-folder`, and XML installers use `handler=fomod`. Inspect reports `layout.handler` and `layout.support_status`; a top-level `Data/` is promoted without building a virtual file tree, while root documentation is preserved. C# FOMOD scripts, OMOD, NCC, and explicit setup/install executables are reported as risky or unsupported and are never executed automatically.

Every installation plan requires an explicit reviewed `--name`. Agents must inspect the mod purpose and active Profile conventions, reuse the established category taxonomy and localized-description style, retain a recognizable original title, and present the final name before confirmation. Plan output includes category examples and lexical related-mod candidates. New-install placement also requires `--placement-reason`; agents should keep base/patch, framework, family, and other related mods together, using dependency and conflict overwrite evidence before falling back to a generic separator.

For Nexus archives, always pass `--modid` and `--file-id` together when planning. The plan freezes the official filename/version/last-modified identity; apply creates or merges `meta.ini` in staging and validates it after commit. When the source archive is moved into MO2's archive directory, its adjacent `<archive>.meta` sidecar is moved with it and collision-safe naming preserves both metadata files. A new install requires one explicit placement at apply time. A same-folder update is detected automatically, returns `placement.mode=preserve_existing`, preserves the exact Mod position and enabled/disabled marker, and must be applied without placement flags. Existing plugin states are retained, newly introduced plugins default to disabled, and removed plugins are removed from `plugins.txt` and `loadorder.txt`.

## Assisted manual Nexus downloads

A free Nexus API key is sufficient for metadata lookup; Premium is not required. When direct API download is unavailable, use the official browser flow:

```powershell
# $Tool is the absolute path returned by the Skill bootstrap.
& $Tool nexus request 175506 734778 --json
```

The command opens the official Nexus file page and watches the current Windows user's browser Downloads known folder for up to 15 minutes. Windows folder redirection is respected; if the known-folder lookup is unavailable, `%USERPROFILE%\Downloads` is used. It ignores browser partial files, matches the official Nexus filename/File ID/size, waits for the file size to stabilize, runs a 7-Zip integrity test, classifies the archive, and returns the safe next dry-run command. It never clicks the web page, reads browser cookies, bypasses the Slow Download flow, or installs automatically. Use `--downloads-dir <folder>` to monitor a custom folder (including MO2's `downloads/` directory). If no match is found, rerun with the folder containing the downloaded archive. `--no-open-browser`, `--no-wait`, and `--timeout` are also available for scripting.


Legacy `install legacy` and top-level `update` remain available only with `--dry-run` for read-only compatibility. Their mutating forms are safety-blocked; ordinary installs and updates must use `install inspect`, `install plan`, and `install apply`.

## Manual post-install steps

Archive inspection, Nexus verification, dry-run, and installation results include `manual_post_install_steps`. The toolkit detects BodySlide projects and presets, Pandora/Nemesis patches, FNIS-specific content, and prebuilt behavior files. These are one-time, non-blocking recommendations rather than mandatory instructions: users with an established workflow may adapt or skip the suggested steps. The toolkit never launches generation tools automatically and does not track completion. Follow the returned steps through MO2, use a dedicated generated-output mod instead of leaving files in `Overwrite`, and do not enable conflicting Pandora/Nemesis/FNIS outputs together. An empty list means no recognized manual follow-up was detected.

## Game-root exceptions (SKSE / Engine Fixes)

Do not pass game-root packages to `install`. Configure the real folder containing `SkyrimSE.exe`, then use the dedicated review-and-deploy workflow:

```powershell
# $Tool is the absolute path returned by the Skill bootstrap.
& $Tool setup --instance C:\MO2 --profile Default --game "C:\SteamLibrary\steamapps\common\Skyrim Special Edition" --json
& $Tool root inspect C:\Downloads\skse.zip --json
& $Tool root deploy C:\Downloads\skse.zip --dry-run --json
# After explicit user confirmation:
& $Tool root deploy C:\Downloads\skse.zip --yes --json
```

Only recognized SKSE and Engine Fixes root packages are accepted. The command verifies `SkyrimSE.exe`, blocks while Skyrim/SKSE/MO2 is running, flattens one wrapper directory, backs up every replaced file, records newly created files, writes atomically, and supports `backup inspect/restore`. Files under an SKSE archive's `Data/` directory are intentionally deployed to the real game `Data/` directory as part of the official root package; ordinary mods remain MO2-managed.

## Development

A clean Windows checkout requires Python 3.11+ and the .NET 8 SDK only for development builds:

```powershell
python -X utf8 -m pip install -e .
python -X utf8 -m unittest discover -s tests -p "test_*.py" -v
python -X utf8 -m mo2_agent_toolkit --version
.\scripts\build.ps1
.\scripts\test-adapters.ps1
.\scripts\package-release.ps1
python -X utf8 tests\bootstrap_integration.py
```

The build uses the in-repository `sidecars\npc-agent-patcher` project. Release tags must exactly match the versions in `pyproject.toml`, the plugin manifest, Python package, and runtime manifest.

The Nexus key is validated online before saving and never appears in JSON output, command arguments, or configuration files. Configuration and DPAPI-protected credentials live under `%LOCALAPPDATA%\MO2AgentToolkit`, outside the release directory. Do not publish `.env`, secrets, caches, logs, or local paths.

## Batch manual-download and planned installation

The preferred non-Premium flow is session based:

```powershell
# $Tool is the absolute path returned by the Skill bootstrap.
& $Tool config show --json
& $Tool nexus batch prepare nexus:184173 --json
# If optional dependencies are returned, confirm them with the user, then rerun with:
& $Tool nexus batch prepare nexus:184173 --include-optional <mod-id> --json
& $Tool nexus batch collect <session-id> --json
& $Tool install inspect "C:\Users\User\Downloads\mod.zip" --json
& $Tool install plan "C:\Users\User\Downloads\mod.zip" --selections selections.json --modid 184173 --file-id 123456 --json
# Select one exact placement from modlist_context; after explicit confirmation:
& $Tool install apply <plan-id> --yes --after-mod "<exact mod or separator>" --placement-reason "<relationship and overwrite intent>" --json
```

### FOMOD engine

FOMOD planning uses the vendored Apache-2.0 `pyfomod 1.2.1` engine to evaluate page visibility, conditional option types, flags, file/game dependencies, conditional file installs, group constraints, ordering, priorities, and folder expansion. Planning projects the resolved files into a staging tree and scans that tree for plugins before a plan can be applied. The dependency environment and selected result are frozen in the plan. XML comments produce an advisory `CommentsPresentWarning`: their contents are ignored and do not block planning even though PyFomod marks the warning critical upstream. Syntax errors, invalid enums, missing required attributes, invalid option constraints, the obsolete `fommDependency` expression, and unknown vendor extensions remain safe hard stops. Every `validation_warnings` item distinguishes `upstream_critical` from the toolkit's final `critical`, `blocking`, and `advisory` policy.

Selections files are strict JSON objects whose string group IDs map to arrays of string option IDs, for example `{"0:0":["0:0:0"]}`. A string, null, number, object value, non-string array item, or unknown stable group/option ID is an input error (exit 2); no fallback selection is inferred. FOMOD discovery remains case-insensitive, while `root_entries` and `fomod.source` preserve archive spelling. `fomod.canonical_source` reports `fomod/ModuleConfig.xml`, and `case_variant` reports whether the archive spelling differs.

`batch prepare` resolves dependency alternatives and opens required official Nexus pages together; optional dependencies are shown for confirmation and are not opened by default. It returns immediately and does not monitor downloads. After the user says downloads are complete, `batch collect` scans once using Nexus filename, size, file ID, and SHA-256 evidence. FOMOD archives require explicit selections; unsupported conditions stop safely and never fall back to installing every file. Apply is hash-bound, blocks while MO2 runs, requires an exact non-ambiguous placement for new installs (and no placement for same-folder updates), validates the flattened staged root, rescans staged plugins, audits committed content by SHA-256, updates and audits the active profile in one transaction, and only archives after commit. Use `archive retry <plan-id>` after a post-commit archive warning.

## NPC FaceGen conflict workflow

The bundled Mutagen sidecar is exposed through a stable, agent-safe workflow. The following uses `mo2-tool` as shorthand for the absolute bootstrapped runtime executable described above:

```text
mo2-tool npc scan --json
mo2-tool npc plan <scan.json> --json
mo2-tool npc decide <plan.json> <decisions.json> --json   # only when required
mo2-tool npc apply <plan.json> --yes --json
mo2-tool npc verify <plan.json> --json
```

Plans bind to profile hashes and stable candidate IDs. The LLM/user selects only IDs emitted by the plan; paths and copy/plugin-edit commands are not accepted. Applying requires one explicit confirmation, blocks while MO2 or Skyrim is running, stages output, preserves existing entry order, and creates a restorable transaction. This release indexes loose FaceGen; BSA-only assets are reported as a limitation. Final follow-up steps are recommendations rather than mandatory instructions.


## Profile three-state operations

```powershell
mo2-tool profile apply Default --disable-mod "Example" --dry-run --json
mo2-tool profile apply Default --unregister-plugin "Example.esp" --json
mo2-tool nexus download 12345 67890 --json
```

Plugin states are `enabled`, `disabled`, or `unregistered`. Existing mod toggles stay in place unless an explicit placement option is supplied. Installation plans remain schema v2 and JSON envelopes remain schema v1. A Profile-file checksum change normally invalidates a plan. `install apply/resume <plan-id> --auto-replan` may create a new plan only for drift in `modlist.txt`, `plugins.txt`, or `loadorder.txt`: it continues under the existing confirmation only when operation, archive/source identity, FOMOD resolution, selections, placement, conflicts, and update state are semantically equivalent. Otherwise it returns exit 1 with `replan_review_required`, a new plan ID, and JSON-path changes for review, without modifying MO2. Archive drift, a running MO2/Skyrim process, and illegal plan state are never bypassed. Apply results include `replan.attempted`, `equivalent`, `original_plan_id`, `effective_plan_id`, and `semantic_changes`.

Placement anchors still require a case-insensitive, complete, unique name. If no exact match exists, the error may include up to ten safe `candidates` with the exact name, reason, and `modlist.txt` line: leading `[category]` tags may be stripped for an exact suggestion, or a name-boundary suffix may be suggested. Candidates are hints only and are never selected automatically; duplicate exact names also remain a hard stop before any transaction or MO2 write.


## License

MO2 Agent Toolkit is licensed under GPL-3.0-or-later. Vendored third-party components retain their original licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

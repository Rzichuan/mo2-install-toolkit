# MO2 Agent Toolkit

A Windows x64, agent-neutral toolkit for safe Mod Organizer 2 operations. Public releases contain a standalone executable; users do not need Python.

## Quick start

1. Download and extract the Windows release ZIP.
2. Install the self-contained Skill Bundle with `scripts\install-adapters.ps1 -Target Both`. The script installs one shared copy under `%LOCALAPPDATA%\MO2AgentToolkit\skill-bundles` and creates Claude/Codex Skill junctions.
3. Set `$Tool = "$env:LOCALAPPDATA\MO2AgentToolkit\skill-bundles\mo2-mod-installer\bin\mo2-tool.exe"` and run `& $Tool setup --json`. If multiple instances/profiles are returned, rerun with `--instance` and `--profile`.
4. Optionally store a Nexus key with `& $Tool auth set --gui --json`; the console fallback is `auth set --console --json`.
5. Verify with `& $Tool doctor --json`.

The executable and its PyInstaller `_internal` runtime are part of the Skill Bundle. Do not copy `mo2-tool.exe` alone, invoke a current-directory `bin`, or depend on `PATH`.

## Safe installation

```powershell
$Tool = "$env:LOCALAPPDATA\MO2AgentToolkit\skill-bundles\mo2-mod-installer\bin\mo2-tool.exe"
& $Tool plan nexus:12345 --json
& $Tool install inspect C:\Downloads\mod.7z --json
& $Tool install plan C:\Downloads\mod.7z --modid 12345 --file-id 67890 --json
# Choose an exact anchor from modlist_context, show it to the user, and confirm once:
& $Tool install apply <plan-id> --yes --after-mod "—————— 其他模组生成 ——————_separator" --json
& $Tool profile audit --json
```

Nexus may require non-Premium users to download files manually. The toolkit does not bypass Nexus restrictions.

For Nexus archives, always pass `--modid` and `--file-id` together when planning. The plan freezes the official filename/version/last-modified identity; apply creates or merges `meta.ini` in staging and validates it after commit. A new install requires one explicit placement at apply time. A same-folder update is detected automatically, returns `placement.mode=preserve_existing`, preserves the exact Mod position and enabled/disabled marker, and must be applied without placement flags. Existing plugin states are retained, newly introduced plugins default to disabled, and removed plugins are removed from `plugins.txt` and `loadorder.txt`.

## Assisted manual Nexus downloads

A free Nexus API key is sufficient for metadata lookup; Premium is not required. When direct API download is unavailable, use the official browser flow:

```powershell
$Tool = "$env:LOCALAPPDATA\MO2AgentToolkit\skill-bundles\mo2-mod-installer\bin\mo2-tool.exe"
& $Tool nexus request 175506 734778 --json
```

The command opens the official Nexus file page and watches the current Windows user's browser Downloads known folder for up to 15 minutes. Windows folder redirection is respected; if the known-folder lookup is unavailable, `%USERPROFILE%\Downloads` is used. It ignores browser partial files, matches the official Nexus filename/File ID/size, waits for the file size to stabilize, runs a 7-Zip integrity test, classifies the archive, and returns the safe next dry-run command. It never clicks the web page, reads browser cookies, bypasses the Slow Download flow, or installs automatically. Use `--downloads-dir <folder>` to monitor a custom folder (including MO2's `downloads/` directory). If no match is found, rerun with the folder containing the downloaded archive. `--no-open-browser`, `--no-wait`, and `--timeout` are also available for scripting.


Legacy `install legacy` and top-level `update` remain available only with `--dry-run` for read-only compatibility. Their mutating forms are safety-blocked; ordinary installs and updates must use `install inspect`, `install plan`, and `install apply`.

## Manual post-install steps

Archive inspection, Nexus verification, dry-run, and installation results include `manual_post_install_steps`. The toolkit detects BodySlide projects and presets, Pandora/Nemesis patches, FNIS-specific content, and prebuilt behavior files. These are one-time, non-blocking recommendations rather than mandatory instructions: users with an established workflow may adapt or skip the suggested steps. The toolkit never launches generation tools automatically and does not track completion. Follow the returned steps through MO2, use a dedicated generated-output mod instead of leaving files in `Overwrite`, and do not enable conflicting Pandora/Nemesis/FNIS outputs together. An empty list means no recognized manual follow-up was detected.

## Game-root exceptions (SKSE / Engine Fixes)

Do not pass game-root packages to `install`. Configure the real folder containing `SkyrimSE.exe`, then use the dedicated review-and-deploy workflow:

```powershell
$Tool = "$env:LOCALAPPDATA\MO2AgentToolkit\skill-bundles\mo2-mod-installer\bin\mo2-tool.exe"
& $Tool setup --instance C:\MO2 --profile Default --game "C:\SteamLibrary\steamapps\common\Skyrim Special Edition" --json
& $Tool root inspect C:\Downloads\skse.zip --json
& $Tool root deploy C:\Downloads\skse.zip --dry-run --json
# After explicit user confirmation:
& $Tool root deploy C:\Downloads\skse.zip --yes --json
```

Only recognized SKSE and Engine Fixes root packages are accepted. The command verifies `SkyrimSE.exe`, blocks while Skyrim/SKSE/MO2 is running, flattens one wrapper directory, backs up every replaced file, records newly created files, writes atomically, and supports `backup inspect/restore`. Files under an SKSE archive's `Data/` directory are intentionally deployed to the real game `Data/` directory as part of the official root package; ordinary mods remain MO2-managed.

## Development

```powershell
python -X utf8 -m unittest discover -s tests -v
python -X utf8 -m mo2_agent_toolkit --version
scripts\build.ps1
```

The Nexus key is validated online before saving and never appears in JSON output, command arguments, or configuration files. Configuration and DPAPI-protected credentials live under `%LOCALAPPDATA%\MO2AgentToolkit`, outside the release directory. Do not publish `.env`, secrets, caches, logs, or local paths.

## Batch manual-download and planned installation

The preferred non-Premium flow is session based:

```powershell
$Tool = "$env:LOCALAPPDATA\MO2AgentToolkit\skill-bundles\mo2-mod-installer\bin\mo2-tool.exe"
& $Tool config show --json
& $Tool nexus batch prepare nexus:184173 --json
# If optional dependencies are returned, confirm them with the user, then rerun with:
& $Tool nexus batch prepare nexus:184173 --include-optional <mod-id> --json
& $Tool nexus batch collect <session-id> --json
& $Tool install inspect "C:\Users\User\Downloads\mod.zip" --json
& $Tool install plan "C:\Users\User\Downloads\mod.zip" --selections selections.json --modid 184173 --file-id 123456 --json
# Select one exact placement from modlist_context; after explicit confirmation:
& $Tool install apply <plan-id> --yes --after-mod "<exact mod or separator>" --json
```

`batch prepare` resolves dependency alternatives and opens required official Nexus pages together; optional dependencies are shown for confirmation and are not opened by default. It returns immediately and does not monitor downloads. After the user says downloads are complete, `batch collect` scans once using Nexus filename, size, file ID, and SHA-256 evidence. FOMOD archives require explicit selections; unsupported conditions stop safely and never fall back to installing every file. Apply is hash-bound, blocks while MO2 runs, requires an exact non-ambiguous placement for new installs (and no placement for same-folder updates), validates the flattened staged root, rescans staged plugins, audits committed content by SHA-256, updates and audits the active profile in one transaction, and only archives after commit. Use `archive retry <plan-id>` after a post-commit archive warning.

## NPC FaceGen conflict workflow

The bundled Mutagen sidecar is exposed through a stable, agent-safe workflow. The following uses `mo2-tool` as shorthand for the absolute Bundle executable described above:

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

Plugin states are `enabled`, `disabled`, or `unregistered`. Existing mod toggles stay in place unless an explicit placement option is supplied. Installation plans use schema v2 and are invalidated by changes to any profile file.

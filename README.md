# MO2 Agent Toolkit

A Windows x64, agent-neutral toolkit for safe Mod Organizer 2 operations. Public releases contain a standalone executable; users do not need Python.

## Quick start

1. Download and extract the Windows release ZIP.
2. Run `bin\mo2-tool.exe setup --json`. If multiple instances/profiles are returned, rerun with `--instance` and `--profile`.
3. Optionally store a Nexus key in a local Windows dialog with `bin\mo2-tool.exe auth set --gui --json`. The console fallback is `auth set --console --json`.
4. Install the Codex or Claude Code adapter with the scripts under `scripts`, or point another agent at `AGENTS.md`.
5. Verify with `bin\mo2-tool.exe doctor --json`.

## Safe installation

```powershell
bin\mo2-tool.exe plan nexus:12345 --json
bin\mo2-tool.exe install inspect C:\Downloads\mod.7z --json
bin\mo2-tool.exe install plan C:\Downloads\mod.7z --json
# Choose an exact anchor from modlist_context, show it to the user, and confirm once:
bin\mo2-tool.exe install apply <plan-id> --yes --after-mod "—————— 其他模组生成 ——————_separator" --json
bin\mo2-tool.exe profile audit --json
```

Nexus may require non-Premium users to download files manually. The toolkit does not bypass Nexus restrictions.

## Assisted manual Nexus downloads

A free Nexus API key is sufficient for metadata lookup; Premium is not required. When direct API download is unavailable, use the official browser flow:

```powershell
bin\mo2-tool.exe nexus request 175506 734778 --json
```

The command opens the official Nexus file page and watches the current Windows user's browser Downloads known folder for up to 15 minutes. Windows folder redirection is respected; if the known-folder lookup is unavailable, `%USERPROFILE%\Downloads` is used. It ignores browser partial files, matches the exact Nexus filename/File ID/size, waits for the file size to stabilize, runs a 7-Zip integrity test, classifies the archive, and returns the safe next dry-run command. It never clicks the web page, reads browser cookies, bypasses the Slow Download flow, or installs automatically. Use `--downloads-dir <folder>` to monitor a custom folder (including MO2's `downloads/` directory). If no match is found, rerun with the folder containing the downloaded archive. `--no-open-browser`, `--no-wait`, and `--timeout` are also available for scripting.

## Manual post-install steps

Archive inspection, Nexus verification, dry-run, and installation results include `manual_post_install_steps`. The toolkit detects BodySlide projects and presets, Pandora/Nemesis patches, FNIS-specific content, and prebuilt behavior files. These are one-time, non-blocking recommendations rather than mandatory instructions: users with an established workflow may adapt or skip the suggested steps. The toolkit never launches generation tools automatically and does not track completion. Follow the returned steps through MO2, use a dedicated generated-output mod instead of leaving files in `Overwrite`, and do not enable conflicting Pandora/Nemesis/FNIS outputs together. An empty list means no recognized manual follow-up was detected.

## Game-root exceptions (SKSE / Engine Fixes)

Do not pass game-root packages to `install`. Configure the real folder containing `SkyrimSE.exe`, then use the dedicated review-and-deploy workflow:

```powershell
bin\mo2-tool.exe setup --instance C:\MO2 --profile Default --game "C:\SteamLibrary\steamapps\common\Skyrim Special Edition" --json
bin\mo2-tool.exe root inspect C:\Downloads\skse.zip --json
bin\mo2-tool.exe root deploy C:\Downloads\skse.zip --dry-run --json
# After explicit user confirmation:
bin\mo2-tool.exe root deploy C:\Downloads\skse.zip --yes --json
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
mo2-tool config show --json
mo2-tool nexus batch prepare nexus:184173 --json
# If optional dependencies are returned, confirm them with the user, then rerun with:
mo2-tool nexus batch prepare nexus:184173 --include-optional <mod-id> --json
mo2-tool nexus batch collect <session-id> --json
mo2-tool install inspect "C:\Users\User\Downloads\mod.zip" --json
mo2-tool install plan "C:\Users\User\Downloads\mod.zip" --selections selections.json --json
# Select one exact placement from modlist_context; after explicit confirmation:
mo2-tool install apply <plan-id> --yes --after-mod "<exact mod or separator>" --json
```

`batch prepare` resolves dependency alternatives and opens required official Nexus pages together; optional dependencies are shown for confirmation and are not opened by default. It returns immediately and does not monitor downloads. After the user says downloads are complete, `batch collect` scans once using Nexus filename, size, file ID, and SHA-256 evidence. FOMOD archives require explicit selections; unsupported conditions stop safely and never fall back to installing every file. Apply is hash-bound, blocks while MO2 runs, requires an exact non-ambiguous placement, validates the flattened staged root, rescans staged plugins, updates and audits the active profile in one transaction, and only archives after commit. Use `archive retry <plan-id>` after a post-commit archive warning.

## NPC FaceGen conflict workflow

The bundled Mutagen sidecar is exposed through a stable, agent-safe workflow:

```text
mo2-tool npc scan --json
mo2-tool npc plan <scan.json> --json
mo2-tool npc decide <plan.json> <decisions.json> --json   # only when required
mo2-tool npc apply <plan.json> --yes --json
mo2-tool npc verify <plan.json> --json
```

Plans bind to profile hashes and stable candidate IDs. The LLM/user selects only IDs emitted by the plan; paths and copy/plugin-edit commands are not accepted. Applying requires one explicit confirmation, blocks while MO2 or Skyrim is running, stages output, preserves existing entry order, and creates a restorable transaction. This release indexes loose FaceGen; BSA-only assets are reported as a limitation. Final follow-up steps are recommendations rather than mandatory instructions.

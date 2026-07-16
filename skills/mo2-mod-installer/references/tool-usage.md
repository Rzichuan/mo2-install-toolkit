# mo2-tool usage guide

Use this reference for exact command shapes and branch handling. The safety and decision policy in `../SKILL.md` remains authoritative; the JSON invariants in `agent-contract.md` remain authoritative for automation.

## Resolve the bundled executable

Resolve the executable from the loaded Skill, not from the current directory or `PATH`:

```powershell
# Codex
$Tool = "$HOME/.codex/skills/mo2-mod-installer/bin/mo2-tool.exe"

# Claude Code (use this path instead when running there)
$Tool = "$HOME/.claude/skills/mo2-mod-installer/bin/mo2-tool.exe"

if (-not (Test-Path -LiteralPath $Tool -PathType Leaf)) { throw "Damaged Skill Bundle: missing mo2-tool.exe" }
if (-not (Test-Path -LiteralPath (Join-Path (Split-Path -Parent $Tool) '_internal') -PathType Container)) { throw "Damaged Skill Bundle: missing _internal" }
& $Tool --version
```

Use `& $Tool ... --json` in PowerShell. Never put a Nexus key on the command line.

## First use, configuration, and diagnostics

Start with diagnostics. When configuration is absent or invalid, or environment paths are to be changed, perform discovery only; `setup --dry-run` must not write configuration:

```powershell
& $Tool doctor --json
& $Tool setup --dry-run --json
```

Show the user the complete proposed configuration: MO2 instance root, its derived `mods` directory, Profile, game directory, download directory, post-install archive directory, and 7-Zip executable. Obtain explicit confirmation of those concrete values in the current conversation flow. Even a single unambiguous candidate is only a candidate; defaults, prior confirmation, silence, and agent judgment are not authorization.

Only after that confirmation, apply explicit selectors and all confirmed auxiliary paths. Never run bare `setup --json`:

```powershell
& $Tool setup --instance "<confirmed MO2 instance path>" --profile "<confirmed profile>" --game "<confirmed Skyrim path>" --seven-zip "<confirmed 7z.exe path>" --json
& $Tool config set --download-directory "<confirmed browser or MO2 downloads path>" --archive-directory "<confirmed archive path>" --archive-after-install true --json
& $Tool config show --json
& $Tool doctor --json
```

Valid existing configuration needs no repeated confirmation when no path is changing. If Doctor reports an invalid path, display the current value and read-only replacement candidates; do not overwrite it autonomously or rerun setup merely to hide the failure.

Set or inspect the DPAPI-protected Nexus credential without exposing it:

```powershell
& $Tool auth set --gui --json
& $Tool auth status --json
& $Tool auth remove --json
```

Use `auth set --console --json` only when GUI entry is unavailable. The command reads the key from hidden interactive input; run it in a real Windows PowerShell/Terminal window, not as a non-interactive agent command. If the agent shell is Bash (including Git Bash), do not paste PowerShell syntax such as `& $Tool ...` into Bash. Ask the user to run the command in Windows PowerShell, or invoke PowerShell explicitly: `powershell.exe -NoProfile -ExecutionPolicy Bypass -Command '& "<absolute tool path>" auth set --console'`. Never read the DPAPI file or echo the credential. `auth clear` is a compatibility alias for `auth remove`; prefer `remove` in new instructions.

### Doctor handling

- Invalid/missing MO2 instance, Profile, game, or 7-Zip path: correct configuration, then rerun doctor.
- Missing Bundle executable or `_internal`: stop; do not repair by copying an EXE from `dist`.
- Running MO2/Skyrim/helper process before mutation: close it and rerun the exact planned command or `install resume` as appropriate.
- Credential/network errors: do not expose credentials; use `auth status`, then safely retry metadata/download operations.
- Do not continue to a mutation until configuration is valid and the relevant safety errors are resolved.

## Nexus discovery and downloads

Inspect a Nexus mod and resolve dependencies before selecting files:

```powershell
& $Tool nexus info <mod-id> --json
& $Tool nexus deps <mod-id> --json
& $Tool plan nexus:<mod-id> --json
```

`nexus info` supplies purpose/files metadata; `nexus deps` and `plan nexus:<mod-id>` expose required and optional dependency evidence. Do not install optional dependencies without review.

For a direct API download available to the account:

```powershell
& $Tool nexus download <mod-id> <file-id> --json
```

Use exactly two IDs. Do not use the deprecated duplicated form `nexus download download ...`.

For the official browser-assisted non-Premium flow:

```powershell
& $Tool nexus request <mod-id> <file-id> --json
```

The command may open the official Nexus page and monitor the configured/known Downloads folder. The user performs the Slow Download interaction. Useful variants are:

```powershell
& $Tool nexus request <mod-id> <file-id> --downloads-dir "<folder>" --json
& $Tool nexus request <mod-id> <file-id> --no-open-browser --no-wait --json
```

Never click the site automatically, read cookies, or bypass Nexus restrictions.

For several required files/dependencies:

```powershell
& $Tool nexus batch prepare nexus:<mod-id> --file-id <file-id> --file-id <file-id> --json
& $Tool nexus batch status <session-id> --json
& $Tool nexus batch collect <session-id> --json
```

Add `--include-optional <dependency-id>` only after optional dependency review. `prepare` opens official pages and returns immediately; `collect` scans once after the user confirms downloads are finished. Continue with `install inspect` for each collected archive.

## Inspect and route an archive

Always inspect before planning:

```powershell
& $Tool install inspect "<archive path>" --json
```

Read at least:

- `data.layout.handler`
- `data.layout.support_status`
- `data.layout.support_reason`
- `data.layout.installer_risk`
- `data.layout.nesting_root`
- `data.layout.flatten`
- `data.layout.effective_root_entries`
- `data.fomod`, `recommended_resolution`, and `recommended_selections`

Route the result as follows:

| Result | Meaning and next action |
|---|---|
| `supported` + `simple` | Ordinary archive; continue. A recognized single wrapper may be flattened. |
| `supported` + `data-folder` | Continue; top-level `Data/` content is promoted and root documentation is preserved. |
| `supported` + `fomod` | Exit 1/review is expected; review choices and create an explicit selections file. |
| `risky` | Stop before plan/apply. Report the detected C# script, OMOD/NCC marker, or explicit installer risk. |
| `unsupported` | Stop and report the reason; do not guess an archive root or install all files. |
| recognized game-root signature | Use the root-package flow below. |

Exit 1 from FOMOD inspection is a review state, not a crash. Never turn a risky/unsupported result into a manual copy operation unless the user starts a separate, explicitly manual investigation.

## Simple and top-level Data installations

Create a plan with a reviewed name. For Nexus files, bind both official IDs:

```powershell
& $Tool install plan "<archive path>" --name "[category] Local purpose——Recognizable Original Title" --modid <mod-id> --file-id <file-id> --json
```

For a local/non-Nexus archive, omit both Nexus ID arguments. Never provide only one ID.

The concise plan returns naming and placement summaries. If evidence is insufficient, request the complete context:

```powershell
& $Tool install plan "<archive path>" --name "<reviewed MO2 name>" --full-context --json
```

Before confirmation, present the operation, final name and naming rationale, handler/root transformation, plugin list, source metadata, conflicts/related mods, exact proposed neighbors, and overwrite direction.

Apply a new installation with exactly one placement in `modlist.txt` file direction:

```powershell
& $Tool install apply <plan-id> --yes --after-mod "<exact existing mod>" --placement-reason "<relationship evidence and intended overwrite direction>" --json
```

The alternatives are mutually exclusive:

```powershell
& $Tool install apply <plan-id> --yes --before-mod "<exact existing mod>" --placement-reason "<reason>" --json
& $Tool install apply <plan-id> --yes --modlist-top --placement-reason "<reason>" --json
& $Tool install apply <plan-id> --yes --modlist-bottom --placement-reason "<reason>" --json
```

An exact unique anchor is mandatory. If candidates are returned, review them and create/apply a new explicit decision; never substitute a candidate automatically.

A placement can optionally be frozen during plan creation by supplying the same placement argument and `--placement-reason`. When frozen, Apply must not silently change the reviewed relationship.

## XML FOMOD installations

`install inspect` returns stable group/option IDs and usually exits 1 for selection review. Create a UTF-8 JSON file shaped as:

```json
{
  "0:0": ["0:0:0"]
}
```

Every key is a string group ID; every value is an array of string option IDs emitted by inspect. Preserve group constraints and do not invent IDs.

Plan the selected result:

```powershell
& $Tool install plan "<archive path>" --name "<reviewed MO2 name>" --selections "<selections.json>" --modid <mod-id> --file-id <file-id> --json
```

Review resolved files, plugins, flags, dependencies, and validation output. `advisory=true` XML comment warnings do not block. Final `blocking=true`, critical repairs, invalid conditions, unknown extensions, path escape, or unresolved file dependencies stop planning/apply. Apply the confirmed plan with the normal new-install placement command.

## Same-folder updates

Use the exact existing MO2 Mod folder/Profile entry as `--name`:

```powershell
& $Tool install inspect "<updated archive path>" --json
& $Tool install plan "<updated archive path>" --name "<exact existing Mod name>" --modid <mod-id> --file-id <file-id> --json
```

Continue only when the plan reports an update with `placement.mode=preserve_existing` and the expected current adjacency/state. After confirmation, apply without placement or placement reason:

```powershell
& $Tool install apply <plan-id> --yes --json
```

Do not add `--before-mod`, `--after-mod`, top/bottom, or `--placement-reason` to an update. Apply stops on archive, identity, Profile-state, or adjacency drift. Retained plugin states are preserved, new plugins are disabled when the mod is enabled (otherwise unregistered), and removed plugins are removed from both Profile plugin files.

## Resume and Profile-only drift

After a running-process safety block, close the reported processes and resume the same confirmed plan with the same placement decision:

```powershell
& $Tool install resume <plan-id> --yes --after-mod "<exact existing mod>" --placement-reason "<same reviewed reason>" --json
```

For an update, omit placement as with Apply.

Use automatic re-planning only for checksum drift in `modlist.txt`, `plugins.txt`, or `loadorder.txt`:

```powershell
& $Tool install apply <plan-id> --yes --auto-replan --after-mod "<exact existing mod>" --placement-reason "<reason>" --json
```

- Equivalent replacement: the command may continue under the existing confirmation; report original/effective plan IDs.
- `replan_review_required`/exit 1: no MO2 write occurred. Review semantic changes and explicitly apply the returned new plan.
- Archive drift, running processes, illegal plan state, installer risk, and safety exit 3 are never bypassed.

## Post-install archive handling

Enable archiving before planning:

```powershell
& $Tool config set --archive-directory "<archive directory>" --archive-after-install true --json
```

After the MO2 transaction commits and audits successfully, the source archive is moved. An adjacent `<archive>.meta` is moved as the same logical pair. Collision handling uses the Nexus file ID when available, otherwise a timestamp, and adds a numeric suffix until neither the archive nor sidecar target collides. A source already in the destination is a safe no-op.

Archive movement failure returns `installed_with_warnings`/exit 1 and does not roll back a successfully committed Mod. Report `archive_result`; do not reinstall. Once the filesystem issue is corrected, retry from the recorded plan:

```powershell
& $Tool archive retry <plan-id> --json
```

If moving the sidecar fails, the tool attempts to return both archive and sidecar to their source paths. Exit 5 with rollback details requires manual filesystem review before another retry.

## Profile operations

Audit the configured Profile after every installation write:

```powershell
& $Tool profile audit --json
```

For direct Profile changes, preview first and use exact names:

```powershell
& $Tool profile apply Default --enable-mod "Mod A" --enable-mod "Mod B" --after-mod "<exact anchor>" --dry-run --json
& $Tool profile apply Default --enable-mod "Mod A" --enable-mod "Mod B" --after-mod "<exact anchor>" --json
& $Tool profile apply Default --disable-mod "Mod C" --dry-run --json
& $Tool profile apply Default --enable-plugin "Example.esp" --disable-plugin "Other.esp" --unregister-plugin "Old.esp" --dry-run --json
```

Multiple `--enable-mod` values are high-to-low MO2 priority. Without a placement option, existing mod toggles remain in place. Plugin actions change only enabled/disabled/unregistered state; plugin ordering is not exposed by this command.

## Game-root packages

Only recognized SKSE and Engine Fixes root/AIO signatures use this flow:

```powershell
& $Tool root inspect "<archive path>" --json
& $Tool root deploy "<archive path>" --dry-run --json
& $Tool root deploy "<archive path>" --yes --json
```

Present the dry-run file targets and obtain explicit confirmation. Unknown root signatures are safety blocks and must not be forced or routed into ordinary installation.

## Backups and restore

List backups and inspect the selected manifest before confirmation:

```powershell
& $Tool backup list --json
& $Tool backup inspect <backup-id> --json
& $Tool backup restore <backup-id> --yes --json
& $Tool profile audit --json
```

Do not restore an uninspected or ambiguous backup. Report restored files and the post-restore audit.

## Exit handling

| Exit | Meaning | Required Agent action |
|---:|---|---|
| 0 | Success | Validate returned audit/placement/archive fields and continue. |
| 1 | Review or warning | Read warnings/data. Ask for a decision when required; do not treat it as an unqualified completed mutation. |
| 2 | Input/configuration error | Correct the named field, path, selection schema, or configuration; do not retry unchanged. |
| 3 | Safety block | Stop. Close processes or change to the documented safe flow; never bypass the block. |
| 4 | Network error | Report the endpoint purpose without secrets; retry only when safe or use the official manual Nexus flow. |
| 5 | Filesystem/tool error | Preserve paths and rollback details, correct access/tooling, then use the documented retry path. |
| 10 | Internal error | Stop, preserve the JSON/error context, and report a toolkit defect. |

Always inspect the JSON envelope rather than relying only on the process exit code. Never parse human output when `--json` is available.

[CmdletBinding(SupportsShouldProcess)] param(
  [ValidateSet('Auto','Codex','Claude','Both')][string]$Target = 'Auto',
  [string]$Version,
  [string]$AgentHome = $HOME,
  [string]$LocalAppDataRoot = $env:LOCALAPPDATA,
  [string]$AssetDirectory
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

function Get-Sha256([string]$Path) {
  $Stream = [IO.File]::OpenRead($Path); $Sha = [Security.Cryptography.SHA256]::Create()
  try { return ([BitConverter]::ToString($Sha.ComputeHash($Stream))).Replace('-', '').ToLowerInvariant() }
  finally { $Sha.Dispose(); $Stream.Dispose() }
}
function Test-ChildPath([string]$Path, [string]$Root) {
  $Full = [IO.Path]::GetFullPath($Path); $Base = [IO.Path]::GetFullPath($Root).TrimEnd('\','/')
  return $Full.StartsWith($Base + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)
}
function Remove-Junction([string]$Path) {
  $Item = Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
  if (-not $Item) { return }
  if ($Item.LinkType -ne 'Junction') { throw "Refusing to remove a non-junction adapter: $Path" }
  [IO.Directory]::Delete([IO.Path]::GetFullPath($Path), $false)
}
function Get-LinkTarget([IO.FileSystemInfo]$Item) {
  if (-not $Item.Target) { return $null }
  return [IO.Path]::GetFullPath([string]@($Item.Target)[0])
}
function Expand-SafeArchive([string]$ZipPath, [string]$Destination) {
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  $Root = [IO.Path]::GetFullPath($Destination).TrimEnd('\')
  $Archive = [IO.Compression.ZipFile]::OpenRead($ZipPath)
  try {
    foreach ($Entry in $Archive.Entries) {
      $Candidate = [IO.Path]::GetFullPath((Join-Path $Root $Entry.FullName.Replace('/', '\')))
      if (-not ($Candidate -eq $Root -or $Candidate.StartsWith($Root + '\', [StringComparison]::OrdinalIgnoreCase))) {
        throw "Archive entry escapes extraction root: $($Entry.FullName)"
      }
    }
  } finally { $Archive.Dispose() }
  [IO.Compression.ZipFile]::ExtractToDirectory($ZipPath, $Destination)
}
function Read-ExpectedHash([string]$Path, [string]$AssetName) {
  $Text = [IO.File]::ReadAllText($Path, [Text.Encoding]::ASCII).Trim()
  if ($Text -notmatch '^([0-9A-Fa-f]{64})\s+\*?(.+)$') { throw "Invalid checksum file: $Path" }
  if ($Matches[2].Trim() -ne $AssetName) { throw "Checksum names '$($Matches[2].Trim())' instead of '$AssetName'." }
  return $Matches[1].ToLowerInvariant()
}
function Copy-OrDownloadAsset([string]$Name, [string]$Uri, [string]$Destination) {
  if ($AssetDirectory) {
    $Source = Join-Path ([IO.Path]::GetFullPath($AssetDirectory)) $Name
    if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) { throw "Test/local asset not found: $Source" }
    Copy-Item -LiteralPath $Source -Destination $Destination -Force
  } else {
    Invoke-WebRequest -UseBasicParsing -Uri $Uri -OutFile $Destination
  }
}

if (-not [Environment]::Is64BitOperatingSystem) { throw 'MO2 Agent Toolkit currently supports Windows x64 only.' }
if (-not $LocalAppDataRoot) { throw 'LOCALAPPDATA is unavailable; pass -LocalAppDataRoot.' }
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
$AgentHome = [IO.Path]::GetFullPath($AgentHome)
$ToolkitData = [IO.Path]::GetFullPath((Join-Path $LocalAppDataRoot 'MO2AgentToolkit'))

if (-not $Version) {
  if ($AssetDirectory) { throw 'Local asset installation requires -Version.' }
  $Release = Invoke-RestMethod -UseBasicParsing -Headers @{'User-Agent'='MO2-Agent-Toolkit-Installer';'Accept'='application/vnd.github+json'} -Uri 'https://api.github.com/repos/Rzichuan/mo2-install-toolkit/releases/latest'
  if ($Release.draft -or $Release.prerelease -or [string]$Release.tag_name -notmatch '^v(\d+\.\d+\.\d+)$') { throw 'GitHub did not return a valid stable release.' }
  $Version = $Matches[1]
}
if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw "Invalid version: $Version" }
$Tag = "v$Version"
$BaseUri = "https://github.com/Rzichuan/mo2-install-toolkit/releases/download/$Tag"
$SkillAsset = "mo2-skill-$Tag.zip"
$RuntimeAsset = "mo2-runtime-$Tag-win-x64.zip"
$Names = @($SkillAsset, "$SkillAsset.sha256", $RuntimeAsset, "$RuntimeAsset.sha256")

if ($Target -eq 'Auto') {
  $HasCodex = Test-Path -LiteralPath (Join-Path $AgentHome '.codex') -PathType Container
  $HasClaude = Test-Path -LiteralPath (Join-Path $AgentHome '.claude') -PathType Container
  if ($HasCodex -and $HasClaude) { $Target = 'Both' }
  elseif ($HasCodex) { $Target = 'Codex' }
  elseif ($HasClaude) { $Target = 'Claude' }
  else { throw "Neither Codex nor Claude was detected under '$AgentHome'. Download install.ps1 and rerun with -Target Codex, Claude, or Both." }
}
$Adapters = @()
if ($Target -in @('Codex','Both')) { $Adapters += [pscustomobject]@{name='Codex';root=(Join-Path $AgentHome '.codex\skills');path=(Join-Path $AgentHome '.codex\skills\mo2-mod-installer')} }
if ($Target -in @('Claude','Both')) { $Adapters += [pscustomobject]@{name='Claude';root=(Join-Path $AgentHome '.claude\skills');path=(Join-Path $AgentHome '.claude\skills\mo2-mod-installer')} }

$Work = Join-Path ([IO.Path]::GetTempPath()) ('mo2-installer-' + [guid]::NewGuid().ToString('N'))
$SkillParent = Join-Path $ToolkitData 'skill-bundles'
$StableSkill = Join-Path $SkillParent 'mo2-mod-installer'
$RuntimeParent = Join-Path $ToolkitData "runtimes\$Version"
$StableRuntime = Join-Path $RuntimeParent 'mo2-runtime'
$BackupRoot = Join-Path $ToolkitData ('adapter-backups\' + (Get-Date -Format 'yyyyMMdd-HHmmssfff'))
$BundleBackup = Join-Path $ToolkitData ('bundle-backups\' + (Get-Date -Format 'yyyyMMdd-HHmmssfff') + '\mo2-mod-installer')
$ManifestPath = Join-Path $ToolkitData 'adapter-install.json'
$CreatedLinks=@(); $AdapterBackups=@(); $OldManagedLinks=@(); $SkillMoved=$false; $MutationStarted=$false; $RuntimeInstalled=$false; $RuntimeQuarantine=$null
try {
  New-Item -ItemType Directory -Path $Work -Force | Out-Null
  foreach ($Name in $Names) { Copy-OrDownloadAsset $Name "$BaseUri/$Name" (Join-Path $Work $Name) }
  foreach ($Asset in @($SkillAsset,$RuntimeAsset)) {
    $Expected = Read-ExpectedHash (Join-Path $Work "$Asset.sha256") $Asset
    $Actual = Get-Sha256 (Join-Path $Work $Asset)
    if ($Actual -ne $Expected) { throw "SHA-256 verification failed for $Asset." }
  }
  $Extract = Join-Path $Work 'extract'; $SkillExtract=Join-Path $Extract 'skill'; $RuntimeExtract=Join-Path $Extract 'runtime'
  New-Item -ItemType Directory -Path $SkillExtract,$RuntimeExtract -Force | Out-Null
  Expand-SafeArchive (Join-Path $Work $SkillAsset) $SkillExtract
  Expand-SafeArchive (Join-Path $Work $RuntimeAsset) $RuntimeExtract
  $SkillCandidate = Join-Path $SkillExtract 'mo2-skill'
  $RuntimeCandidate = Join-Path $RuntimeExtract 'mo2-runtime'
  $SkillMetadata = Get-Content -LiteralPath (Join-Path $SkillCandidate 'skill.json') -Encoding UTF8 -Raw | ConvertFrom-Json
  $RuntimeMetadata = Get-Content -LiteralPath (Join-Path $RuntimeCandidate 'runtime.json') -Encoding UTF8 -Raw | ConvertFrom-Json
  $RuntimeManifest = Get-Content -LiteralPath (Join-Path $SkillCandidate 'runtime-manifest.json') -Encoding UTF8 -Raw | ConvertFrom-Json
  if ([int]$SkillMetadata.schema_version -ne 1 -or [int]$RuntimeMetadata.schema_version -ne 1 -or [int]$RuntimeManifest.schema_version -ne 1) { throw 'Downloaded asset metadata schema is unsupported.' }
  if ([string]$SkillMetadata.platform -ne 'win-x64' -or [string]$RuntimeMetadata.platform -ne 'win-x64' -or [string]$RuntimeManifest.platform -ne 'win-x64') { throw 'Downloaded assets are not for Windows x64.' }
  if ([string]$SkillMetadata.toolkit_version -ne $Version -or [string]$RuntimeMetadata.tool_version -ne $Version -or [string]$RuntimeManifest.tool_version -ne $Version) { throw 'Downloaded Skill and Runtime versions do not match the requested version.' }
  if ([string]$RuntimeManifest.release_tag -ne $Tag -or [string]$RuntimeManifest.asset_name -ne $RuntimeAsset -or [string]$RuntimeManifest.checksum_asset_name -ne "$RuntimeAsset.sha256") { throw 'Skill runtime manifest does not identify the matching Release assets.' }
  if (@(Get-ChildItem -LiteralPath $SkillExtract -Force).Count -ne 1 -or @(Get-ChildItem -LiteralPath $RuntimeExtract -Force).Count -ne 1) { throw 'Release archive must contain exactly one expected root directory.' }
  foreach($Required in @((Join-Path $SkillCandidate 'SKILL.md'),(Join-Path $SkillCandidate 'scripts\ensure-runtime.ps1'),(Join-Path $RuntimeCandidate 'bin\mo2-tool.exe'),(Join-Path $RuntimeCandidate 'bin\_internal'))){if(-not(Test-Path -LiteralPath $Required)){throw "Incomplete asset; missing: $Required"}}
  $ActualVersion = ((& (Join-Path $RuntimeCandidate 'bin\mo2-tool.exe') --version) | Out-String).Trim()
  if ($LASTEXITCODE -ne 0 -or $ActualVersion -ne $Version) { throw "Runtime self-test returned '$ActualVersion'." }
  if (-not $PSCmdlet.ShouldProcess($ToolkitData, "Install MO2 Agent Toolkit $Version for $Target")) { return }
  $MutationStarted=$true
  New-Item -ItemType Directory -Path $SkillParent,$RuntimeParent -Force | Out-Null
  if (Test-Path -LiteralPath $StableRuntime) {
    $ExistingRuntimeValid=$false
    try {
      $ExistingRuntime = Get-Content -LiteralPath (Join-Path $StableRuntime 'runtime.json') -Encoding UTF8 -Raw | ConvertFrom-Json
      $ExistingExe = Join-Path $StableRuntime 'bin\mo2-tool.exe'
      $ExistingVersion = if(Test-Path -LiteralPath $ExistingExe -PathType Leaf){((& $ExistingExe --version)|Out-String).Trim()}else{''}
      $ExistingRuntimeValid=([string]$ExistingRuntime.tool_version -eq $Version -and $ExistingVersion -eq $Version -and (Test-Path -LiteralPath (Join-Path $StableRuntime 'bin\_internal') -PathType Container))
    } catch { $ExistingRuntimeValid=$false }
    if(-not $ExistingRuntimeValid){
      $RuntimeQuarantine=Join-Path $RuntimeParent ('.invalid-'+(Get-Date -Format 'yyyyMMddHHmmssfff')+'-'+[guid]::NewGuid().ToString('N'))
      Move-Item -LiteralPath $StableRuntime -Destination $RuntimeQuarantine
      Move-Item -LiteralPath $RuntimeCandidate -Destination $StableRuntime; $RuntimeInstalled=$true
    }
  } else { Move-Item -LiteralPath $RuntimeCandidate -Destination $StableRuntime; $RuntimeInstalled=$true }
  if (Test-Path -LiteralPath $StableSkill) {
    New-Item -ItemType Directory -Path (Split-Path -Parent $BundleBackup) -Force | Out-Null
    Move-Item -LiteralPath $StableSkill -Destination $BundleBackup; $SkillMoved=$true
  }
  Move-Item -LiteralPath $SkillCandidate -Destination $StableSkill
  foreach($Adapter in $Adapters){
    $Root=[IO.Path]::GetFullPath($Adapter.root); $Path=[IO.Path]::GetFullPath($Adapter.path)
    if(-not(Test-ChildPath $Path $Root)){throw "Adapter escaped skill root: $Path"}
    New-Item -ItemType Directory -Path $Root -Force | Out-Null
    $Existing=Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    if($Existing){
      $ExistingTarget=Get-LinkTarget $Existing
      if($Existing.LinkType -eq 'Junction' -and $ExistingTarget -and ($ExistingTarget.Equals($StableSkill,[StringComparison]::OrdinalIgnoreCase) -or $ExistingTarget.StartsWith($ToolkitData + '\',[StringComparison]::OrdinalIgnoreCase))){
        $OldManagedLinks += [pscustomobject]@{path=$Path;target=$ExistingTarget}; Remove-Junction $Path
      }
      else { New-Item -ItemType Directory -Path $BackupRoot -Force | Out-Null; $Saved=Join-Path $BackupRoot $Adapter.name; Move-Item -LiteralPath $Path -Destination $Saved; $AdapterBackups += [pscustomobject]@{path=$Path;backup=$Saved} }
    }
    New-Item -ItemType Junction -Path $Path -Target $StableSkill | Out-Null; $CreatedLinks += $Path
  }
  $Managed=@()
  foreach($Candidate in @(
    [pscustomobject]@{name='Codex';root=(Join-Path $AgentHome '.codex\skills');path=(Join-Path $AgentHome '.codex\skills\mo2-mod-installer')},
    [pscustomobject]@{name='Claude';root=(Join-Path $AgentHome '.claude\skills');path=(Join-Path $AgentHome '.claude\skills\mo2-mod-installer')}
  )){
    $Item=Get-Item -LiteralPath $Candidate.path -Force -ErrorAction SilentlyContinue; $LinkTarget=if($Item){Get-LinkTarget $Item}else{$null}
    if($Item -and $Item.LinkType -eq 'Junction' -and $LinkTarget -and $LinkTarget.Equals($StableSkill,[StringComparison]::OrdinalIgnoreCase)){$Managed += [ordered]@{name=$Candidate.name;path=[IO.Path]::GetFullPath($Candidate.path);root=[IO.Path]::GetFullPath($Candidate.root)}}
  }
  $Data=[ordered]@{schema_version=2;bundle=$StableSkill;tool_version=$Version;runtime=$StableRuntime;adapters=@($Managed);adapter_backups=@($AdapterBackups | ForEach-Object { $_.backup });installed_at=(Get-Date).ToUniversalTime().ToString('o')}
  New-Item -ItemType Directory -Path $ToolkitData -Force | Out-Null
  $TempManifest=$ManifestPath+'.tmp'; [IO.File]::WriteAllText($TempManifest,($Data|ConvertTo-Json -Depth 6)+"`n",[Text.UTF8Encoding]::new($false)); Move-Item -LiteralPath $TempManifest -Destination $ManifestPath -Force
  Write-Output "MO2 Agent Toolkit $Version installed for $Target."
  Write-Output "Skill: $StableSkill"
  Write-Output "Runtime: $StableRuntime"
  Write-Output 'Start a new agent session before using the Skill.'
} catch {
  if($MutationStarted){
    foreach($Link in $CreatedLinks){Remove-Junction $Link}
    foreach($Saved in $AdapterBackups){if(Test-Path -LiteralPath $Saved.backup){Move-Item -LiteralPath $Saved.backup -Destination $Saved.path}}
    if(Test-Path -LiteralPath $StableSkill){Remove-Item -LiteralPath $StableSkill -Recurse -Force}
    if($SkillMoved -and (Test-Path -LiteralPath $BundleBackup)){Move-Item -LiteralPath $BundleBackup -Destination $StableSkill}
    if($RuntimeInstalled -and (Test-Path -LiteralPath $StableRuntime)){Remove-Item -LiteralPath $StableRuntime -Recurse -Force}
    if($RuntimeQuarantine -and (Test-Path -LiteralPath $RuntimeQuarantine)){Move-Item -LiteralPath $RuntimeQuarantine -Destination $StableRuntime}
    foreach($OldLink in $OldManagedLinks){if(-not(Get-Item -LiteralPath $OldLink.path -Force -ErrorAction SilentlyContinue) -and (Test-Path -LiteralPath $OldLink.target)){New-Item -ItemType Junction -Path $OldLink.path -Target $OldLink.target|Out-Null}}
  }
  throw
} finally {
  $TempRoot=[IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\'); $WorkFull=[IO.Path]::GetFullPath($Work)
  if($WorkFull.StartsWith($TempRoot+'\',[StringComparison]::OrdinalIgnoreCase) -and (Test-Path -LiteralPath $WorkFull)){Remove-Item -LiteralPath $WorkFull -Recurse -Force}
}

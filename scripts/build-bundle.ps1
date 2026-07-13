[CmdletBinding()] param(
  [string]$ToolDirectory,
  [string]$OutputDirectory
)
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
if (-not $ToolDirectory) { $ToolDirectory = Join-Path $Root 'dist\mo2-tool' }
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $Root 'dist\mo2-mod-installer-bundle' }
$ToolDirectory = [IO.Path]::GetFullPath($ToolDirectory)
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
$SkillSource = (Resolve-Path -LiteralPath (Join-Path $Root 'skills\mo2-mod-installer')).Path
if (-not (Test-Path -LiteralPath $ToolDirectory -PathType Container)) { throw "Tool directory not found: $ToolDirectory" }
$ToolExe = Join-Path $ToolDirectory 'mo2-tool.exe'
$Internal = Join-Path $ToolDirectory '_internal'
if (-not (Test-Path -LiteralPath $ToolExe -PathType Leaf)) { throw "Tool executable not found: $ToolExe" }
if (-not (Test-Path -LiteralPath $Internal -PathType Container)) { throw "PyInstaller _internal directory not found: $Internal" }
$OutputParent = Split-Path -Parent $OutputDirectory
New-Item -ItemType Directory -Path $OutputParent -Force | Out-Null
$Stage = Join-Path $OutputParent ('.bundle-stage-' + [guid]::NewGuid().ToString('N'))
$Previous = Join-Path $OutputParent ('.bundle-previous-' + [guid]::NewGuid().ToString('N'))
try {
  New-Item -ItemType Directory -Path $Stage | Out-Null
  Get-ChildItem -LiteralPath $SkillSource -Force | Copy-Item -Destination $Stage -Recurse -Force
  Copy-Item -LiteralPath (Join-Path $Root 'LICENSE') -Destination $Stage -Force
  Copy-Item -LiteralPath (Join-Path $Root 'THIRD_PARTY_NOTICES.md') -Destination $Stage -Force
  $ThirdPartyDestination = Join-Path $Stage 'third_party\pyfomod'
  New-Item -ItemType Directory -Path $ThirdPartyDestination -Force | Out-Null
  Get-ChildItem -LiteralPath (Join-Path $Root 'third_party\pyfomod') -Force | Copy-Item -Destination $ThirdPartyDestination -Recurse -Force
  $StageBin = Join-Path $Stage 'bin'
  New-Item -ItemType Directory -Path $StageBin | Out-Null
  Get-ChildItem -LiteralPath $ToolDirectory -Force | Copy-Item -Destination $StageBin -Recurse -Force
  foreach ($Required in @((Join-Path $Stage 'SKILL.md'), (Join-Path $Stage 'references\agent-contract.md'), (Join-Path $Stage 'LICENSE'), (Join-Path $Stage 'THIRD_PARTY_NOTICES.md'), (Join-Path $Stage 'third_party\pyfomod\LICENSE'), (Join-Path $StageBin 'mo2-tool.exe'), (Join-Path $StageBin '_internal'))) {
    if (-not (Test-Path -LiteralPath $Required)) { throw "Incomplete bundle; missing: $Required" }
  }
  $Version = & (Join-Path $StageBin 'mo2-tool.exe') --version
  if ($LASTEXITCODE -ne 0 -or -not $Version) { throw 'Bundle executable smoke test failed' }
  if (Test-Path -LiteralPath $OutputDirectory) { Move-Item -LiteralPath $OutputDirectory -Destination $Previous }
  try { Move-Item -LiteralPath $Stage -Destination $OutputDirectory }
  catch {
    if (Test-Path -LiteralPath $Previous) { Move-Item -LiteralPath $Previous -Destination $OutputDirectory }
    throw
  }
  if (Test-Path -LiteralPath $Previous) { Remove-Item -LiteralPath $Previous -Recurse -Force }
  [pscustomobject]@{ bundle = $OutputDirectory; tool_version = ([string]$Version).Trim() }
} finally {
  if (Test-Path -LiteralPath $Stage) { Remove-Item -LiteralPath $Stage -Recurse -Force }
  if (Test-Path -LiteralPath $Previous) { Remove-Item -LiteralPath $Previous -Recurse -Force }
}

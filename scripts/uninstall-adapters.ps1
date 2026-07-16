[CmdletBinding(SupportsShouldProcess)] param(
  [string]$LocalAppDataRoot = $env:LOCALAPPDATA
)
$ErrorActionPreference = 'Stop'
function Remove-Junction([string]$Path) {
  $Item = Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
  if (-not $Item) { return }
  if ($Item.LinkType -ne 'Junction') { throw "Refusing to remove a non-junction adapter path: $Path" }
  [IO.Directory]::Delete([IO.Path]::GetFullPath($Path), $false)
}
if (-not $LocalAppDataRoot) { throw 'LOCALAPPDATA is unavailable; pass -LocalAppDataRoot explicitly.' }
$ToolkitData = [IO.Path]::GetFullPath((Join-Path $LocalAppDataRoot 'MO2AgentToolkit'))
$Manifest = Join-Path $ToolkitData 'adapter-install.json'
if (-not (Test-Path -LiteralPath $Manifest -PathType Leaf)) { Write-Output 'No managed adapter installation manifest found.'; exit 0 }
$Data = Get-Content -LiteralPath $Manifest -Encoding UTF8 -Raw | ConvertFrom-Json
$Bundle = [IO.Path]::GetFullPath([string]$Data.bundle)
if (-not $Bundle.StartsWith($ToolkitData + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw "Refusing bundle outside toolkit data root: $Bundle" }
$ValidatedAdapters = @()
foreach ($Adapter in $Data.adapters) {
  $Path = [IO.Path]::GetFullPath([string]$Adapter.path)
  $Root = [IO.Path]::GetFullPath([string]$Adapter.root)
  if (-not $Path.StartsWith($Root + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw "Refusing adapter outside recorded skill root: $Path" }
  $Item = Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
  if ($Item) {
    $Target = if ($Item.Target) { [IO.Path]::GetFullPath([string]@($Item.Target)[0]) } else { $null }
    if ($Item.LinkType -ne 'Junction' -or -not $Target -or -not $Target.Equals($Bundle, [StringComparison]::OrdinalIgnoreCase)) { throw "Refusing to remove unmanaged or changed adapter: $Path" }
    $ValidatedAdapters += $Path
  }
}
foreach ($Path in $ValidatedAdapters) {
  if ($PSCmdlet.ShouldProcess($Path, 'Remove managed adapter junction')) { Remove-Junction $Path }
}
if (Test-Path -LiteralPath $Bundle) {
  if ($PSCmdlet.ShouldProcess($Bundle, 'Remove managed MO2 Skill Bundle')) { Remove-Item -LiteralPath $Bundle -Recurse -Force }
}
if ($PSCmdlet.ShouldProcess($Manifest, 'Remove adapter installation manifest')) { Remove-Item -LiteralPath $Manifest -Force }

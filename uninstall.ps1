[CmdletBinding(SupportsShouldProcess)] param(
  [string]$LocalAppDataRoot = $env:LOCALAPPDATA,
  [switch]$RemoveRuntime
)
$ErrorActionPreference='Stop'
function Remove-Junction([string]$Path){$Item=Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue;if(-not $Item){return};if($Item.LinkType -ne 'Junction'){throw "Refusing to remove changed adapter: $Path"};[IO.Directory]::Delete([IO.Path]::GetFullPath($Path),$false)}
if(-not $LocalAppDataRoot){throw 'LOCALAPPDATA is unavailable.'}
$Root=[IO.Path]::GetFullPath((Join-Path $LocalAppDataRoot 'MO2AgentToolkit'));$Manifest=Join-Path $Root 'adapter-install.json'
if(-not(Test-Path -LiteralPath $Manifest -PathType Leaf)){Write-Output 'No managed MO2 Agent Toolkit installation was found.';return}
$Data=Get-Content -LiteralPath $Manifest -Encoding UTF8 -Raw|ConvertFrom-Json;$Bundle=[IO.Path]::GetFullPath([string]$Data.bundle)
if(-not $Bundle.StartsWith($Root+'\',[StringComparison]::OrdinalIgnoreCase)){throw 'Recorded bundle is outside the toolkit data root.'}
$Validated=@();foreach($Adapter in $Data.adapters){$Path=[IO.Path]::GetFullPath([string]$Adapter.path);$SkillRoot=[IO.Path]::GetFullPath([string]$Adapter.root);if(-not $Path.StartsWith($SkillRoot+'\',[StringComparison]::OrdinalIgnoreCase)){throw "Adapter escaped its recorded root: $Path"};$Item=Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue;if($Item){$Target=if($Item.Target){[IO.Path]::GetFullPath([string]@($Item.Target)[0])}else{$null};if($Item.LinkType -ne 'Junction' -or -not $Target -or -not $Target.Equals($Bundle,[StringComparison]::OrdinalIgnoreCase)){throw "Refusing to remove unmanaged or changed adapter: $Path"};$Validated += $Path}}
foreach($Path in $Validated){if($PSCmdlet.ShouldProcess($Path,'Remove managed adapter')){Remove-Junction $Path}}
if((Test-Path -LiteralPath $Bundle) -and $PSCmdlet.ShouldProcess($Bundle,'Remove managed Skill')){Remove-Item -LiteralPath $Bundle -Recurse -Force}
if($RemoveRuntime -and $Data.PSObject.Properties.Name -contains 'runtime'){$Runtime=[IO.Path]::GetFullPath([string]$Data.runtime);if(-not $Runtime.StartsWith($Root+'\',[StringComparison]::OrdinalIgnoreCase)){throw 'Recorded runtime is outside the toolkit data root.'};if((Test-Path -LiteralPath $Runtime) -and $PSCmdlet.ShouldProcess($Runtime,'Remove installed runtime')){Remove-Item -LiteralPath $Runtime -Recurse -Force}}
if($PSCmdlet.ShouldProcess($Manifest,'Remove installation manifest')){Remove-Item -LiteralPath $Manifest -Force}
Write-Output 'MO2 Agent Toolkit adapters and managed Skill were removed. Configuration, credentials, backups, and other runtime versions were preserved.'

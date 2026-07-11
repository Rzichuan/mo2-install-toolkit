$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$Python = (Get-Command python).Source
& $Python -X utf8 -m pip install -r (Join-Path $Root 'requirements-build.txt')
if ($LASTEXITCODE -ne 0) { throw "Build dependency installation failed with exit code $LASTEXITCODE" }
$PatcherProject = (Resolve-Path -LiteralPath (Join-Path $Root '..\npc-agent-patcher\NpcAgentPatcher.csproj')).Path
$Dotnet = if (Test-Path -LiteralPath 'C:\Modding\Tools\dotnet-sdk\dotnet.exe') { 'C:\Modding\Tools\dotnet-sdk\dotnet.exe' } else { (Get-Command dotnet).Source }
& $Dotnet publish $PatcherProject -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true
if ($LASTEXITCODE -ne 0) { throw "NPC sidecar publish failed with exit code $LASTEXITCODE" }
$Patcher = (Resolve-Path -LiteralPath (Join-Path $Root '..\npc-agent-patcher\bin\Release\net8.0\win-x64\publish\NpcAgentPatcher.exe')).Path
& $Python -X utf8 -m PyInstaller --noconfirm --clean --onedir --name mo2-tool `
  --paths (Join-Path $Root 'src') `
  --add-data "$(Join-Path $Root 'src\mo2_agent_toolkit\legacy');mo2_agent_toolkit\legacy" `
  --add-binary "$Patcher;mo2_agent_toolkit\bin" `
  (Join-Path $Root 'scripts\entrypoint.py')
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
& (Join-Path $Root 'dist\mo2-tool\mo2-tool.exe') --version
if ($LASTEXITCODE -ne 0) { throw 'Built executable smoke test failed' }

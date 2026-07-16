# MO2 Agent Toolkit

[English](README.md) | **简体中文**

面向 Windows x64 的、与 Agent 平台无关的 Mod Organizer 2 安全操作工具包。仓库提供 Skill/plugin，GitHub Release 提供由它固定版本并自动下载的运行时依赖；普通用户无需安装 Python。

## 快速开始

在 Windows PowerShell 中执行这一条命令。安装器会自动检测 Codex 和 Claude，安装最新稳定版 Skill 与固定版本 Runtime，使用 Release 安装清单中的 SHA-256 校验两个 ZIP，并执行运行时自检：

```powershell
irm https://raw.githubusercontent.com/Rzichuan/mo2-install-toolkit/main/install.ps1 | iex
```

无需 Git、Python、.NET SDK、管理员权限、修改 `PATH`，首次使用时也不需要再次下载。安装完成后请新建 Agent 会话。托管 Skill 和 Runtime 位于 `%LOCALAPPDATA%\MO2AgentToolkit`。

未指定 `-Version` 时，安装器通过 GitHub 普通的 `releases/latest/download` 重定向获取固定名 `mo2-installer-manifest.json`。它不会调用 GitHub REST API，也不需要 token。若清单无法获取或校验失败，安装会安全终止并提示改用 tagged installer，不会回退到 API。随后默认路径只下载 Skill ZIP 和 Runtime ZIP；相邻的 `.sha256` 文件仍会发布，供离线和人工校验。

如果没有自动检测到客户端，或希望先审查脚本再执行：

```powershell
irm https://raw.githubusercontent.com/Rzichuan/mo2-install-toolkit/main/install.ps1 -OutFile install.ps1
.\install.ps1 -Target Codex       # Codex、Claude、Both 或 Auto
```

需要可复现的固定版本时，从对应 tag 获取安装器并指定相同版本：

```powershell
irm https://raw.githubusercontent.com/Rzichuan/mo2-install-toolkit/v0.10.6/install.ps1 -OutFile install.ps1
.\install.ps1 -Version 0.10.6
```

离线或测试使用 `-AssetDirectory` 时，若不指定 `-Version`，目录中应包含 `mo2-installer-manifest.json` 以及清单命名的两个 ZIP。若显式指定 `-Version`，原兼容路径保持不变：目录中必须包含对应的 Skill/Runtime ZIP 和两个相邻 `.sha256` 文件。

重复执行安装器即可修复或升级。以下命令移除托管 Skill 和入口，但保留配置、凭据、备份和 Runtime 缓存：

```powershell
irm https://raw.githubusercontent.com/Rzichuan/mo2-install-toolkit/main/uninstall.ps1 | iex
```

Codex marketplace 和 Claude tagged clone 仍作为高级安装方式受到支持。源码 clone 会在首次使用时下载固定 Runtime；一键安装器则在安装阶段完成下载。

### 首次环境配置与路径变更

安装完成不代表用户授权 Agent 选择 MO2 环境。首次使用、配置无效或准备变更任一路径时，必须采用两阶段流程：

```powershell
& $Tool doctor --json
& $Tool setup --dry-run --json
```

Dry-run 只读，不写配置。Agent 必须完整展示 MO2 instance 根目录、派生的 `mods` 目录、Profile、游戏目录、下载目录、安装后归档目录和 7-Zip 路径，并在当前对话流程中取得用户对这些具体值的明确确认。唯一候选、默认值、历史确认、沉默或 Agent 自行判断都不构成授权。

确认后才可显式应用并验收：

```powershell
& $Tool setup --instance "<已确认的 MO2 instance 路径>" --profile "<已确认的 Profile>" --game "<已确认的 Skyrim 路径>" --seven-zip "<已确认的 7z.exe 路径>" --json
& $Tool config set --download-directory "<已确认的下载目录>" --archive-directory "<已确认的归档目录>" --archive-after-install true --json
& $Tool config show --json
& $Tool doctor --json
```

Agent 禁止使用裸 `setup --json` 自动写入发现结果。已有配置有效且路径不变时无需重复确认。Doctor 发现已配置路径无效时，Agent 必须展示当前值和只读发现的替代候选，不得自行覆盖。

### 手动设置 Nexus API Key

API Key 会使用 Windows DPAPI 加密保存。绝不能把 Key 粘贴到聊天、命令参数中，或手动写入文件。请在真实的 Windows PowerShell/Windows Terminal 窗口中，使用 Skill 安装的 Runtime 绝对路径。当前版本示例：

```powershell
$Tool = "$env:LOCALAPPDATA\MO2AgentToolkit\runtimes\0.10.6\mo2-runtime\bin\mo2-tool.exe"
& $Tool auth set --gui --json
```

上面的 GUI 命令会打开凭据输入窗口。如果 GUI 不可用，请在同一个真实的 Windows 交互式终端中使用隐藏输入模式：

```powershell
& $Tool auth set --console --json
```

`auth set --console` 需要交互式输入，不能由非交互式 Agent Shell 代为读取。如果当前 Shell 是 Bash 或 Git Bash，不要把 PowerShell 的 `& $Tool ...` 语法直接粘贴进去；请显式调用 PowerShell：

```bash
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command '& "<mo2-tool.exe 的绝对路径>" auth set --console --json'
```

输入完成后，只验证凭据元数据状态，不要输出 Key 本身：

```powershell
& $Tool auth status --json
```

### Runtime Release 与离线转移

GitHub Release 中的 `mo2-runtime-v0.10.6-win-x64.zip` **不是** Skill/plugin，也不是独立安装程序。它只是 clone 后的 Skill/plugin 自动下载的可执行运行时依赖。普通用户应使用一键安装命令，不需要手动下载 Release 资产；安装器会自动使用 Skill 和 Runtime 两类资产。

若目标机器必须完全离线，请先在目标机器安装或 clone 匹配 tag 的 Skill/plugin。然后在联网机器下载 runtime ZIP 和相邻的 `.sha256`，校验后将压缩包解压到版本目录：

```text
%LOCALAPPDATA%\MO2AgentToolkit\runtimes\0.10.6
```

最终元数据路径必须是 `%LOCALAPPDATA%\MO2AgentToolkit\runtimes\0.10.6\mo2-runtime\runtime.json`，不要产生 `mo2-runtime\mo2-runtime` 双层目录。

仓库的 `scripts\build-bundle.ps1` 仍可在 `dist\mo2-mod-installer-bundle` 构建本地完整 Bundle。既有用户可使用 `scripts\install-adapters.ps1 -BundlePath <本地完整Bundle> -Target Both` 部署共享 Bundle 和 Codex/Claude junction。这个兼容 Bundle 不会作为 GitHub Release 资产发布，也不是正常 clone 安装所必需的。

### 升级、排错与移除

- 通过安装或 clone 更新的 tagged Skill/plugin 升级。每个 tag 只下载与自己匹配的 runtime，从不使用 `latest`；旧缓存可保留用于回滚。
- 网络或代理错误返回 bootstrap exit `4`；请配置 Windows/PowerShell 代理，或把经过校验的对应 runtime 转移到上述精确缓存路径。哈希、元数据或版本错误返回 exit `3`，不得绕过。
- 通过对应 Agent 移除 Skill/plugin。确认没有已安装 Skill 引用旧版本后，才能删除 `%LOCALAPPDATA%\MO2AgentToolkit\runtimes` 下对应的精确版本目录。
- 配置和 DPAPI 凭据独立保存在 `%LOCALAPPDATA%\MO2AgentToolkit`，删除 runtime 缓存不会删除它们。

## 安全安装流程

```powershell
# $Tool 是 Skill bootstrap 返回的绝对路径。
& $Tool plan nexus:12345 --json
& $Tool install inspect C:\Downloads\mod.7z --json
& $Tool install plan C:\Downloads\mod.7z --name "[分类] 中文用途——可识别的原始 Mod 标题" --modid 12345 --file-id 67890 --json
# 从 modlist_context 选择一个精确锚点，向用户展示并取得一次明确确认：
& $Tool install apply <plan-id> --yes --after-mod "<精确相关 Mod 或已审查的回退锚点>" --placement-reason "<关联关系与覆盖方向>" --json
& $Tool profile audit --json
```

Nexus 可能要求非 Premium 用户手动下载文件；本工具包不会绕过 Nexus 限制。

自动压缩包处理有意保持克制：普通包使用 `handler=simple`，唯一顶层 `Data/` 使用 `handler=data-folder`，XML 安装器使用 `handler=fomod`。Inspect 会报告 `layout.handler` 和 `layout.support_status`。C# FOMOD 脚本、OMOD、NCC 和显式 setup/install 可执行程序会被标记为危险或不支持，绝不会自动执行。

每个安装计划都必须提供经过审查的 `--name`。Agent 应检查 Mod 用途和当前 Profile 命名约定，复用既有分类与本地化描述风格，并保留可识别的原始标题。新安装还必须提供 `--placement-reason`，优先依据依赖关系、补丁关系和冲突覆盖证据安排位置。

规划 Nexus 压缩包时必须同时传入 `--modid` 和 `--file-id`。计划会冻结官方文件名、版本和最后修改时间；Apply 在 staging 中创建或合并 `meta.ini` 并在提交后校验。新安装必须明确指定一次位置；同目录更新会自动保留 Mod 位置和启用状态，并且不得传入 placement 参数。现有插件状态会保留，新插件默认禁用，已移除插件会从 `plugins.txt` 和 `loadorder.txt` 中清除。

## 辅助 Nexus 手动下载

免费的 Nexus API Key 足以查询元数据，不需要 Premium。无法直接通过 API 下载时，使用官方浏览器流程：

```powershell
# $Tool 是 Skill bootstrap 返回的绝对路径。
& $Tool nexus request 175506 734778 --json
```

命令会打开 Nexus 官方文件页面，并在最多 15 分钟内监控当前 Windows 用户的 Downloads 已知文件夹。它会忽略浏览器临时文件，按官方文件名、File ID 和大小匹配，等待文件大小稳定，执行 7-Zip 完整性检查，分类压缩包并返回安全的下一条 dry-run 命令。它不会点击网页、读取浏览器 Cookie、绕过 Slow Download 流程或自动安装。可用 `--downloads-dir <目录>` 监控自定义目录；脚本还支持 `--no-open-browser`、`--no-wait` 和 `--timeout`。

旧的 `install legacy` 和顶层 `update` 只保留 `--dry-run` 只读兼容模式。它们的写入形式会被安全阻止；普通安装和更新必须使用 `install inspect`、`install plan`、`install apply`。

## 安装后的手动步骤

压缩包检查、Nexus 校验、dry-run 和安装结果都会返回 `manual_post_install_steps`。工具包能识别 BodySlide 工程/预设、Pandora/Nemesis patch、FNIS 专用内容和预生成 behavior 文件。这些是一次性的非阻塞建议，并非强制指令；已有成熟工作流的用户可以调整或跳过。工具包不会自动启动生成工具，也不会跟踪步骤是否完成。建议通过 MO2 执行这些步骤，把生成结果放入独立输出 Mod，不要长期留在 `Overwrite`，也不要同时启用互相冲突的 Pandora/Nemesis/FNIS 输出。

## 游戏根目录例外（SKSE / Engine Fixes）

不要把游戏根目录包传给 `install`。先配置实际包含 `SkyrimSE.exe` 的目录，再使用专用的检查和部署流程：

```powershell
# $Tool 是 Skill bootstrap 返回的绝对路径。
& $Tool setup --instance C:\MO2 --profile Default --game "C:\SteamLibrary\steamapps\common\Skyrim Special Edition" --json
& $Tool root inspect C:\Downloads\skse.zip --json
& $Tool root deploy C:\Downloads\skse.zip --dry-run --json
# 得到用户明确确认后：
& $Tool root deploy C:\Downloads\skse.zip --yes --json
```

只接受已识别的 SKSE 和 Engine Fixes 根目录包。部署会验证 `SkyrimSE.exe`，在 Skyrim/SKSE/MO2 运行时阻止写入，为每个被替换文件创建备份，记录新文件并原子写入，且支持 `backup inspect/restore`。普通 Mod 仍由 MO2 管理。

## 开发

干净的 Windows checkout 只有在开发构建时才需要 Python 3.11+ 和 .NET 8 SDK：

```powershell
python -X utf8 -m pip install -e .
python -X utf8 -m unittest discover -s tests -p "test_*.py" -v
python -X utf8 -m mo2_agent_toolkit --version
.\scripts\build.ps1
.\scripts\test-adapters.ps1
.\scripts\package-release.ps1
python -X utf8 tests\bootstrap_integration.py
```

构建使用仓库内的 `sidecars\npc-agent-patcher`。Release tag 必须与 `pyproject.toml`、plugin manifest、Python package 和 runtime manifest 中的版本完全一致。

Nexus Key 会在保存前在线验证，且绝不会出现在 JSON 输出、命令参数或配置文件中。配置和 DPAPI 保护的凭据位于 `%LOCALAPPDATA%\MO2AgentToolkit`。不要发布 `.env`、密钥、缓存、日志或本地路径。

## 批量手动下载与计划安装

非 Premium 用户推荐使用基于 session 的流程：

```powershell
# $Tool 是 Skill bootstrap 返回的绝对路径。
& $Tool config show --json
& $Tool nexus batch prepare nexus:184173 --json
# 若返回可选依赖，先向用户确认，再重新执行：
& $Tool nexus batch prepare nexus:184173 --include-optional <mod-id> --json
& $Tool nexus batch collect <session-id> --json
& $Tool install inspect "C:\Users\User\Downloads\mod.zip" --json
& $Tool install plan "C:\Users\User\Downloads\mod.zip" --selections selections.json --modid 184173 --file-id 123456 --json
# 从 modlist_context 选择一个精确位置，并在取得明确确认后执行：
& $Tool install apply <plan-id> --yes --after-mod "<精确 Mod 或分隔符>" --placement-reason "<关系与覆盖意图>" --json
```

### FOMOD 引擎

FOMOD 规划使用内置的 Apache-2.0 `pyfomod 1.2.1`，支持页面可见性、条件选项类型、flag、文件/游戏依赖、条件安装、组约束、顺序、优先级和目录展开。解析结果会投影到 staging tree，并在 Apply 前重新扫描插件。依赖环境和选择结果会冻结在计划中。语法错误、非法枚举、缺失必要属性、非法选项约束、废弃的 `fommDependency` 表达式和未知厂商扩展都会安全停止。

Selections 文件必须是严格 JSON 对象：字符串 group ID 映射到字符串 option ID 数组，例如 `{"0:0":["0:0:0"]}`。类型错误或未知 ID 返回 exit `2`，不会推断回退选择。FOMOD 查找不区分大小写，但会保留压缩包中的原始拼写。

`batch prepare` 会解析依赖替代项并一起打开必需的 Nexus 官方页面；可选依赖必须确认后才会打开。用户确认下载完成后，`batch collect` 按 Nexus 文件名、大小、File ID 和 SHA-256 证据扫描一次。Apply 与哈希绑定，在 MO2 运行时停止，要求新安装使用唯一精确位置，同目录更新不允许 placement 参数；它会校验 staging、重新扫描插件、对提交内容进行 SHA-256 审计，并在一个事务中更新和审计当前 Profile。提交后归档失败可使用 `archive retry <plan-id>`。

## NPC FaceGen 冲突工作流

内置 Mutagen sidecar 通过稳定且适合 Agent 的流程提供：

```text
mo2-tool npc scan --json
mo2-tool npc plan <scan.json> --json
mo2-tool npc decide <plan.json> <decisions.json> --json   # 仅在需要时
mo2-tool npc apply <plan.json> --yes --json
mo2-tool npc verify <plan.json> --json
```

计划会绑定 Profile 哈希和稳定候选 ID。LLM/用户只能选择计划输出的 ID，不能传入路径或复制/插件编辑命令。Apply 需要一次明确确认，在 MO2 或 Skyrim 运行时停止，使用 staging，保留既有条目顺序并创建可恢复事务。本版本索引 loose FaceGen；仅存在于 BSA 的资源会作为限制报告。

## Profile 三状态操作

```powershell
mo2-tool profile apply Default --disable-mod "Example" --dry-run --json
mo2-tool profile apply Default --unregister-plugin "Example.esp" --json
mo2-tool nexus download 12345 67890 --json
```

插件状态分为 `enabled`、`disabled`、`unregistered`。除非明确提供 placement 参数，已有 Mod 的启用/禁用操作会保持原位置。Profile 文件校验和变化通常会使计划失效。`install apply/resume <plan-id> --auto-replan` 只会对 `modlist.txt`、`plugins.txt`、`loadorder.txt` 漂移创建新计划，并且只有操作、压缩包身份、FOMOD 结果、选择、位置、冲突和更新状态在语义上等价时才沿用原确认；否则返回 exit `1` 和 `replan_review_required`，不会修改 MO2。

位置锚点必须是不区分大小写的完整唯一名称。找不到精确项时，错误可能提供最多十个安全 `candidates`，但候选仅用于提示，绝不会自动选择；重复的精确名称同样会在任何事务或 MO2 写入前安全停止。

## 许可证

MO2 Agent Toolkit 使用 GPL-3.0-or-later。内置第三方组件保留各自许可证，详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

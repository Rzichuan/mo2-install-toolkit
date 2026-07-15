using System.Text.Json;
using System.Text.Json.Serialization;
using System.Buffers.Binary;
using Mutagen.Bethesda;
using Mutagen.Bethesda.Plugins.Binary.Parameters;
using Mutagen.Bethesda.Plugins;
using Mutagen.Bethesda.Plugins.Order;
using Mutagen.Bethesda.Plugins.Records;
using Mutagen.Bethesda.Skyrim;

string? protocolResponsePath = null;
string? protocolRequestId = null;
if (args.Length >= 3 && args[0].Equals("protocol", StringComparison.OrdinalIgnoreCase))
{
    var requestArg = Array.FindIndex(args, x => x.Equals("--request", StringComparison.OrdinalIgnoreCase));
    var responseArg = Array.FindIndex(args, x => x.Equals("--response", StringComparison.OrdinalIgnoreCase));
    if (requestArg < 0 || requestArg + 1 >= args.Length || responseArg < 0 || responseArg + 1 >= args.Length)
        throw new ArgumentException("protocol requires --request and --response");
    using var document = JsonDocument.Parse(File.ReadAllText(args[requestArg + 1]));
    var root = document.RootElement;
    if (root.GetProperty("schema_version").GetInt32() != 1) throw new InvalidDataException("Unsupported protocol schema");
    protocolRequestId = root.TryGetProperty("request_id", out var rid) ? rid.GetString() : null;
    protocolResponsePath = args[responseArg + 1];
    var translated = new List<string> { "--instance", root.GetProperty("instance").GetString()!, "--profile", root.GetProperty("profile").GetString()!,
        "--game-data", root.GetProperty("game_data").GetString()!, "--report", root.GetProperty("report_path").GetString()!, "--winning-npcs", "999999" };
    var operation = root.GetProperty("operation").GetString();
    if (operation == "generate")
    {
        translated.AddRange(["--generate-mod", root.GetProperty("staging_output").GetString()!, "--decisions", root.GetProperty("decisions_path").GetString()!]);
    }
    else if (operation != "scan" && operation != "verify") throw new InvalidDataException($"Unsupported operation: {operation}");
    args = translated.ToArray();
}

var options = CliOptions.Parse(args);
if (options.ShowHelp)
{
    CliOptions.PrintHelp();
    return 0;
}

var profile = Mo2Profile.Load(
    options.InstancePath,
    options.ProfileName,
    options.GameDataPath,
    options.IgnoredMods,
    options.IgnoredPlugins);
var report = FaceGenAuditor.BuildReport(profile);
if (options.IncludeWinningNpcRecords)
    report = report with { WinningNpcRecords = MutagenNpcAuditor.ReadWinningNpcRecords(profile, options.WinningNpcLimit) };
Directory.CreateDirectory(Path.GetDirectoryName(options.ReportPath)!);
File.WriteAllText(options.ReportPath, JsonSerializer.Serialize(report, Json.Options));
PatchBuildResult? patchBuild = null;
if (!string.IsNullOrWhiteSpace(options.GenerateModPath))
    patchBuild = NpcPatchGenerator.Generate(profile, report, options.GenerateModPath, options.PatchPluginName, DecisionSet.Load(options.DecisionsPath));

Console.WriteLine($"Profile: {profile.ProfileName}");
Console.WriteLine($"Enabled mods: {profile.EnabledMods.Count}");
Console.WriteLine($"Enabled plugins: {profile.EnabledPlugins.Count}");
Console.WriteLine($"FaceGen NPC keys: {report.Summary.FaceGenNpcKeys}");
Console.WriteLine($"Issues: {report.Summary.Issues}");
Console.WriteLine($"Report: {options.ReportPath}");
if (patchBuild is not null)
{
    Console.WriteLine($"Patch plugin: {patchBuild.PluginPath}");
    Console.WriteLine($"Patched NPCs: {patchBuild.PatchedNpcs}");
    Console.WriteLine($"Copied FaceGen files: {patchBuild.CopiedFaceGenFiles}");
    Console.WriteLine($"Created High Poly HeadParts: {patchBuild.CreatedHighPolyHeadParts}");
}
if (protocolResponsePath is not null)
{
    var response = new { schema_version = 1, protocol_version = 1, tool_version = "0.4.1", request_id = protocolRequestId,
        status = "success", warnings = Array.Empty<string>(), errors = Array.Empty<string>(), data = new { report, patch_build = patchBuild } };
    Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(protocolResponsePath))!);
    File.WriteAllText(protocolResponsePath, JsonSerializer.Serialize(response, Json.Options));
    return 0;
}
return report.Summary.Issues > 0 ? 2 : 0;

static class Json
{
    public static readonly JsonSerializerOptions Options = new()
    {
        WriteIndented = true,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
    };
}

sealed record CliOptions(
    string InstancePath,
    string ProfileName,
    string GameDataPath,
    string ReportPath,
    string? GenerateModPath,
    string PatchPluginName,
    string? DecisionsPath,
    IReadOnlySet<string> IgnoredMods,
    IReadOnlySet<string> IgnoredPlugins,
    bool IncludeWinningNpcRecords,
    int WinningNpcLimit,
    bool ShowHelp)
{
    public static CliOptions Parse(string[] args)
    {
        var map = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        for (var i = 0; i < args.Length; i++)
        {
            var arg = args[i];
            if (arg is "-h" or "--help" or "help")
                return Default with { ShowHelp = true };
            if (!arg.StartsWith("--", StringComparison.Ordinal))
                continue;
            if (i + 1 >= args.Length || args[i + 1].StartsWith("--", StringComparison.Ordinal))
                throw new ArgumentException($"Missing value for {arg}");
            map[arg[2..]] = args[++i];
        }
        var result = Default with
        {
            InstancePath = map.GetValueOrDefault("instance", Default.InstancePath),
            ProfileName = map.GetValueOrDefault("profile", Default.ProfileName),
            GameDataPath = map.GetValueOrDefault("game-data", Default.GameDataPath),
            ReportPath = map.GetValueOrDefault("report", Default.ReportPath),
            GenerateModPath = map.TryGetValue("generate-mod", out var generateModPath)
                ? generateModPath
                : Default.GenerateModPath,
            PatchPluginName = map.GetValueOrDefault("patch-plugin", Default.PatchPluginName),
            DecisionsPath = map.TryGetValue("decisions", out var decisionsPath) ? decisionsPath : Default.DecisionsPath,
            IgnoredMods = ParseSet(map.GetValueOrDefault("ignore-mod", "")),
            IgnoredPlugins = ParseSet(map.GetValueOrDefault("ignore-plugin", "")),
            IncludeWinningNpcRecords = map.ContainsKey("winning-npcs"),
            WinningNpcLimit = map.TryGetValue("winning-npcs", out var limitText) &&
                int.TryParse(limitText, out var limit) ? limit : Default.WinningNpcLimit,
        };
        result.Validate();
        return result;
    }

    public static void PrintHelp()
    {
        Console.WriteLine("""
        NpcAgentPatcher audit

        Options:
          --instance   MO2 instance root. Default: C:\Games\skyrimmod
          --profile    MO2 profile name. Default: lux
          --game-data  Skyrim Data path. Default: C:\steam\steamapps\common\Skyrim Special Edition\Data
          --report     JSON report path.
          --winning-npcs N  Include N winning NPC records via Mutagen. Run inside MO2 VFS for full load order.
          --generate-mod PATH  Build a MO2-style output mod folder, but do not enable it.
          --patch-plugin NAME  Generated patch plugin name. Default: Agent_NPC_ConflictResolution.esp
          --decisions PATH  Structured decision JSON; selected SourceMod is authoritative.
          --ignore-mod NAME[,NAME]  Exclude enabled MO2 mod folders while auditing/generating.
          --ignore-plugin NAME[,NAME]  Exclude enabled plugins while auditing/generating.
        """);
    }

    private static IReadOnlySet<string> ParseSet(string text) =>
        text.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .ToHashSet(StringComparer.OrdinalIgnoreCase);

    private void Validate()
    {
        if (!Directory.Exists(InstancePath))
            throw new DirectoryNotFoundException(InstancePath);
        if (!Directory.Exists(Path.Combine(InstancePath, "profiles", ProfileName)))
            throw new DirectoryNotFoundException(Path.Combine(InstancePath, "profiles", ProfileName));
        if (!Directory.Exists(Path.Combine(InstancePath, "mods")))
            throw new DirectoryNotFoundException(Path.Combine(InstancePath, "mods"));
        if (!Directory.Exists(GameDataPath))
            throw new DirectoryNotFoundException(GameDataPath);
    }

    private static readonly CliOptions Default = new(
        @"C:\Games\skyrimmod",
        "lux",
        @"C:\steam\steamapps\common\Skyrim Special Edition\Data",
        Path.Combine(Environment.CurrentDirectory, "reports", $"npc-facegen-audit-{DateTime.Now:yyyyMMdd-HHmmss}.json"),
        null,
        "Agent_NPC_ConflictResolution.esp",
        null,
        new HashSet<string>(StringComparer.OrdinalIgnoreCase),
        new HashSet<string>(StringComparer.OrdinalIgnoreCase),
        false,
        100,
        false);
}

sealed record Mo2Profile(
    string InstancePath,
    string ProfileName,
    string ModsPath,
    string GameDataPath,
    IReadOnlyList<EnabledMod> EnabledMods,
    IReadOnlyList<string> LoadOrder,
    IReadOnlySet<string> EnabledPlugins)
{
    public static Mo2Profile Load(
        string instancePath,
        string profileName,
        string gameDataPath,
        IReadOnlySet<string> ignoredMods,
        IReadOnlySet<string> ignoredPlugins)
    {
        var modsPath = Path.Combine(instancePath, "mods");
        var profilePath = Path.Combine(instancePath, "profiles", profileName);
        var enabledMods = ReadEnabledMods(modsPath, Path.Combine(profilePath, "modlist.txt"))
            .Where(x => !ignoredMods.Contains(x.Name))
            .ToList();
        var loadOrder = ReadSimpleLines(Path.Combine(profilePath, "loadorder.txt"))
            .Where(x => !ignoredPlugins.Contains(x))
            .ToList();
        var enabledPlugins = ReadSimpleLines(Path.Combine(profilePath, "plugins.txt"))
            .Where(x => x.StartsWith('*'))
            .Select(x => x[1..])
            .Concat(loadOrder.Where(IsBaseGamePlugin))
            .Where(x => !ignoredPlugins.Contains(x))
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
        return new(instancePath, profileName, modsPath, gameDataPath, enabledMods, loadOrder, enabledPlugins);
    }

    private static IReadOnlyList<EnabledMod> ReadEnabledMods(string modsPath, string modListPath)
    {
        var result = new List<EnabledMod>();
        var lines = File.ReadAllLines(modListPath);
        for (var i = 0; i < lines.Length; i++)
        {
            var line = lines[i];
            if (!line.StartsWith('+'))
                continue;
            if (line.StartsWith("+*"))
                continue;
            var name = line[1..];
            var path = Path.Combine(modsPath, name);
            if (!Directory.Exists(path))
                continue;
            // MO2's modlist is reverse-oriented: smaller index means lower left-pane position and higher file priority.
            result.Add(new EnabledMod(name, path, i));
        }
        return result;
    }

    private static IReadOnlyList<string> ReadSimpleLines(string path) =>
        File.ReadAllLines(path)
            .Select(x => x.Trim())
            .Where(x => !string.IsNullOrEmpty(x) && !x.StartsWith('#'))
            .ToList();

    private static bool IsBaseGamePlugin(string pluginName) =>
        pluginName.Equals("Skyrim.esm", StringComparison.OrdinalIgnoreCase) ||
        pluginName.Equals("Update.esm", StringComparison.OrdinalIgnoreCase) ||
        pluginName.Equals("Dawnguard.esm", StringComparison.OrdinalIgnoreCase) ||
        pluginName.Equals("HearthFires.esm", StringComparison.OrdinalIgnoreCase) ||
        pluginName.Equals("Dragonborn.esm", StringComparison.OrdinalIgnoreCase);
}

sealed record EnabledMod(string Name, string Path, int FilePriority);

static class FaceGenAuditor
{
    private static readonly string[] PluginExtensions = [".esm", ".esp", ".esl"];
    private static readonly string FaceGeomPrefix = Path.Combine("meshes", "actors", "character", "FaceGenData", "FaceGeom");
    private static readonly string FaceTintPrefix = Path.Combine("textures", "actors", "character", "FaceGenData", "FaceTint");

    public static AuditReport BuildReport(Mo2Profile profile)
    {
        var pluginFiles = ScanPluginFiles(profile);
        var assets = ScanFaceGenAssets(profile.EnabledMods);
        var groups = assets
            .GroupBy(x => new FaceGenKey(x.PluginDirectory, x.FormId), FaceGenKey.Comparer)
            .Select(g => AnalyzeGroup(profile, g.Key, g.ToList()))
            .OrderBy(x => x.PluginDirectory, StringComparer.OrdinalIgnoreCase)
            .ThenBy(x => x.FormId, StringComparer.OrdinalIgnoreCase)
            .ToList();
        var missingPlugins = profile.EnabledPlugins
            .Where(p => !pluginFiles.ContainsKey(p) && !BaseGameFiles.Contains(p))
            .OrderBy(x => x, StringComparer.OrdinalIgnoreCase)
            .ToList();
        var faceGenPluginDirs = groups
            .Select(x => x.PluginDirectory)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .OrderBy(x => x, StringComparer.OrdinalIgnoreCase)
            .ToList();
        var issueCount = groups.Count(x => x.Issues.Count > 0) + missingPlugins.Count;
        return new AuditReport(
            new AuditSummary(
                profile.EnabledMods.Count,
                profile.EnabledPlugins.Count,
                pluginFiles.Count,
                assets.Count,
                groups.Count,
                issueCount),
            profile.EnabledMods.Take(25).Select(x => new EnabledModInfo(x.Name, x.FilePriority)).ToList(),
            missingPlugins,
            faceGenPluginDirs,
            groups.Where(x => x.Issues.Count > 0).ToList());
    }

    public static Dictionary<string, PluginFileInfo> ScanPluginFiles(Mo2Profile profile)
    {
        var result = new Dictionary<string, PluginFileInfo>(StringComparer.OrdinalIgnoreCase);
        foreach (var file in Directory.EnumerateFiles(profile.GameDataPath))
        {
            if (PluginExtensions.Contains(Path.GetExtension(file), StringComparer.OrdinalIgnoreCase))
                result[Path.GetFileName(file)] = new(Path.GetFileName(file), "Game Data", file, int.MaxValue);
        }
        foreach (var mod in profile.EnabledMods.OrderByDescending(x => x.FilePriority))
        {
            foreach (var file in Directory.EnumerateFiles(mod.Path))
            {
                if (!PluginExtensions.Contains(Path.GetExtension(file), StringComparer.OrdinalIgnoreCase))
                    continue;
                result[Path.GetFileName(file)] = new(Path.GetFileName(file), mod.Name, file, mod.FilePriority);
            }
        }
        return result;
    }

    public static List<FaceGenAsset> ScanFaceGenAssets(IReadOnlyList<EnabledMod> enabledMods)
    {
        var result = new List<FaceGenAsset>();
        foreach (var mod in enabledMods)
        {
            foreach (var file in Directory.EnumerateFiles(mod.Path, "*.*", SearchOption.AllDirectories))
            {
                var extension = Path.GetExtension(file);
                if (!extension.Equals(".nif", StringComparison.OrdinalIgnoreCase) &&
                    !extension.Equals(".dds", StringComparison.OrdinalIgnoreCase))
                    continue;
                var relative = Path.GetRelativePath(mod.Path, file);
                var normalized = relative.Replace(Path.AltDirectorySeparatorChar, Path.DirectorySeparatorChar);
                var kind = TryParseFaceGenPath(normalized, out var pluginDirectory, out var formId);
                if (kind is null)
                    continue;
                result.Add(new(
                    kind.Value,
                    pluginDirectory!,
                    formId!,
                    mod.Name,
                    mod.FilePriority,
                    relative,
                    file));
            }
        }
        return result;
    }

    private static FaceGenKind? TryParseFaceGenPath(string relativePath, out string? pluginDirectory, out string? formId)
    {
        pluginDirectory = null;
        formId = null;
        var isMesh = relativePath.StartsWith(FaceGeomPrefix + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase);
        var isTint = relativePath.StartsWith(FaceTintPrefix + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase);
        if (!isMesh && !isTint)
            return null;
        var prefix = isMesh ? FaceGeomPrefix : FaceTintPrefix;
        var tail = relativePath[(prefix.Length + 1)..];
        var parts = tail.Split(Path.DirectorySeparatorChar, StringSplitOptions.RemoveEmptyEntries);
        if (parts.Length != 2)
            return null;
        pluginDirectory = parts[0];
        formId = Path.GetFileNameWithoutExtension(parts[1]).ToLowerInvariant();
        return isMesh ? FaceGenKind.Mesh : FaceGenKind.Tint;
    }

    private static FaceGenEntry AnalyzeGroup(Mo2Profile profile, FaceGenKey key, List<FaceGenAsset> assets)
    {
        var meshes = assets.Where(x => x.Kind == FaceGenKind.Mesh).OrderBy(x => x.FilePriority).ToList();
        var tints = assets.Where(x => x.Kind == FaceGenKind.Tint).OrderBy(x => x.FilePriority).ToList();
        var winningMesh = meshes.FirstOrDefault();
        var winningTint = tints.FirstOrDefault();
        var issues = new List<string>();
        if (winningMesh is null)
            issues.Add("missing-mesh");
        if (winningTint is null)
            issues.Add("missing-tint");
        if (!profile.EnabledPlugins.Contains(key.PluginDirectory))
            issues.Add("facegen-plugin-directory-not-enabled");
        if (winningMesh is not null && winningTint is not null &&
            !winningMesh.SourceMod.Equals(winningTint.SourceMod, StringComparison.OrdinalIgnoreCase))
            issues.Add("mesh-tint-winning-mod-mismatch");
        return new(
            key.PluginDirectory,
            key.FormId,
            winningMesh?.ToReport(),
            winningTint?.ToReport(),
            meshes.Count,
            tints.Count,
            issues);
    }

    private static readonly HashSet<string> BaseGameFiles = new(StringComparer.OrdinalIgnoreCase)
    {
        "Skyrim.esm", "Update.esm", "Dawnguard.esm", "HearthFires.esm", "Dragonborn.esm",
    };
}

enum FaceGenKind { Mesh, Tint }

sealed record FaceGenKey(string PluginDirectory, string FormId)
{
    public static readonly IEqualityComparer<FaceGenKey> Comparer =
        EqualityComparer<FaceGenKey>.Create(
            (a, b) => a is not null && b is not null &&
                a.PluginDirectory.Equals(b.PluginDirectory, StringComparison.OrdinalIgnoreCase) &&
                a.FormId.Equals(b.FormId, StringComparison.OrdinalIgnoreCase),
            x => HashCode.Combine(
                StringComparer.OrdinalIgnoreCase.GetHashCode(x.PluginDirectory),
                StringComparer.OrdinalIgnoreCase.GetHashCode(x.FormId)));
}

sealed record FaceGenAsset(
    FaceGenKind Kind,
    string PluginDirectory,
    string FormId,
    string SourceMod,
    int FilePriority,
    string RelativePath,
    string FullPath)
{
    public FaceGenAssetReport ToReport() => new(SourceMod, FilePriority, RelativePath);
}

sealed record PluginFileInfo(string PluginName, string SourceMod, string FullPath, int FilePriority);

sealed record AuditReport(
    AuditSummary Summary,
    IReadOnlyList<EnabledModInfo> HighestPriorityEnabledMods,
    IReadOnlyList<string> MissingEnabledPluginFiles,
    IReadOnlyList<string> FaceGenPluginDirectories,
    IReadOnlyList<FaceGenEntry> ProblemFaceGenEntries,
    IReadOnlyList<WinningNpcRecord>? WinningNpcRecords = null);

sealed record AuditSummary(
    int EnabledMods,
    int EnabledPlugins,
    int AvailablePluginFiles,
    int FaceGenAssets,
    int FaceGenNpcKeys,
    int Issues);

sealed record EnabledModInfo(string Name, int FilePriority);

sealed record FaceGenEntry(
    string PluginDirectory,
    string FormId,
    FaceGenAssetReport? WinningMesh,
    FaceGenAssetReport? WinningTint,
    int MeshSourceCount,
    int TintSourceCount,
    IReadOnlyList<string> Issues);

sealed record FaceGenAssetReport(string SourceMod, int FilePriority, string RelativePath);

static class NpcPatchGenerator
{
    public static PatchBuildResult Generate(
        Mo2Profile profile,
        AuditReport report,
        string outputModPath,
        string patchPluginName,
        DecisionSet decisions)
    {
        if (report.WinningNpcRecords is null)
            throw new InvalidOperationException("Patch generation requires --winning-npcs.");

        var pluginFiles = FaceGenAuditor.ScanPluginFiles(profile);
        var stagedDataPath = MutagenNpcAuditor.StagePluginFiles(profile, pluginFiles);
        var loadOrderNames = MutagenNpcAuditor.BuildLoadOrder(profile, pluginFiles);
        var loadOrderKeys = loadOrderNames.Select(x => ModKey.FromNameAndExtension(x)).ToList();
        var loadOrder = LoadOrder.Import<ISkyrimModGetter>(stagedDataPath, loadOrderKeys, GameRelease.SkyrimSE);
        var npcRecords = BuildNpcRecordLookup(loadOrder);
        var headPartRecords = BuildHeadPartRecordLookup(loadOrder);
        var highPolyHeadPartCache = new Dictionary<FormKey, FormKey>();

        Directory.CreateDirectory(outputModPath);
        var patchMod = new SkyrimMod(ModKey.FromNameAndExtension(patchPluginName), SkyrimRelease.SkyrimSE);
        var copiedFaceGenFiles = 0;
        var patchedNpcs = 0;

        BackupExistingDirectory(Path.Combine(outputModPath, "Meshes"));
        BackupExistingDirectory(Path.Combine(outputModPath, "Textures"));

        foreach (var record in report.WinningNpcRecords)
        {
            var decision = decisions.For(record.BasePlugin, record.FaceGenFormId);
            var shouldPatchFace = record.PatchPlan?.Action == "patch-default-from-winning-face-from-candidate" &&
                !string.IsNullOrWhiteSpace(record.PatchPlan.FacePlugin);
            if (decision is not null) shouldPatchFace = true;
            var shouldPatchVanillaFace = ShouldPatchVanillaFaceFallback(record);
            var shouldPatchName = ShouldPatchReadableName(record, npcRecords);
            if (!shouldPatchFace && !shouldPatchVanillaFace && !shouldPatchName)
                continue;
            if (!npcRecords.TryGetValue(new(record.WinningPlugin, record.FormKey), out var defaultNpc))
                continue;

            var patchedNpc = patchMod.Npcs.GetOrAddAsOverride(defaultNpc);
            if (shouldPatchFace)
            {
                var selectedSource = decision?.AppearanceSourceMod ?? record.PatchPlan!.FaceSourceMod;
                var selectedPlugin = decision?.AppearancePlugin;
                if (string.IsNullOrWhiteSpace(selectedPlugin))
                    selectedPlugin = profile.EnabledPlugins
                        .Where(x => pluginFiles.TryGetValue(x, out var info) && info.SourceMod.Equals(selectedSource, StringComparison.OrdinalIgnoreCase))
                        .LastOrDefault(x => npcRecords.ContainsKey(new(x, record.FormKey)));
                selectedPlugin ??= record.PatchPlan?.FacePlugin;
                if (string.IsNullOrWhiteSpace(selectedPlugin) ||
                    !pluginFiles.TryGetValue(selectedPlugin, out var selectedPluginInfo))
                    throw new InvalidOperationException($"Selected appearance plugin is unavailable: {record.BasePlugin}:{record.FaceGenFormId} / {selectedSource} / {selectedPlugin}");
                var isPlannedTranslatedFallback = decision is null &&
                    selectedPlugin.Equals(record.PatchPlan?.FacePlugin, StringComparison.OrdinalIgnoreCase) &&
                    selectedPlugin.Equals(record.PatchPlan?.NamePlugin, StringComparison.OrdinalIgnoreCase);
                if (!selectedPluginInfo.SourceMod.Equals(selectedSource, StringComparison.OrdinalIgnoreCase) &&
                    !isPlannedTranslatedFallback)
                    throw new InvalidOperationException($"Selected appearance plugin does not belong to source mod: {record.BasePlugin}:{record.FaceGenFormId} / {selectedSource} / {selectedPlugin}");
                if (!npcRecords.TryGetValue(new(selectedPlugin, record.FormKey), out var faceNpc))
                    throw new InvalidOperationException($"Selected appearance plugin has no NPC override: {record.BasePlugin}:{record.FaceGenFormId} / {selectedPlugin}");
                ApplyFaceFields(patchedNpc, faceNpc);
                ApplyHeadPartReplacements(patchedNpc, decision?.HeadPartReplacements);
                ApplyHighPolyHeadPartReplacements(
                    patchedNpc,
                    decision?.HighPolyHeadPartReplacements,
                    patchMod,
                    headPartRecords,
                    highPolyHeadPartCache);
                var selectedNamePlugin = decision?.NamePlugin ?? record.PatchPlan?.NamePlugin;
                if (!string.IsNullOrWhiteSpace(selectedNamePlugin) &&
                    npcRecords.TryGetValue(new(selectedNamePlugin, record.FormKey), out var explicitNameNpc))
                    ApplyNameField(patchedNpc, explicitNameNpc);
            }
            else if (shouldPatchVanillaFace)
            {
                if (!npcRecords.TryGetValue(new(record.BasePlugin, record.FormKey), out var baseNpc))
                    continue;
                ApplyFaceFields(patchedNpc, baseNpc);
            }
            ApplyReadableNameIfNeeded(patchedNpc, record, npcRecords);
            patchedNpcs++;

            if (shouldPatchFace)
            {
                var defaultFaceGenSource = decision?.FaceGenSourceMod ??
                    decision?.AppearanceSourceMod ??
                    record.PatchPlan!.FaceSourceMod;
                var selectedMeshSource = decision?.FaceGenMeshSourceMod ?? defaultFaceGenSource;
                var selectedTintSource = decision?.FaceGenTintSourceMod ?? defaultFaceGenSource;
                var hasExplicitMeshSource = !string.IsNullOrWhiteSpace(decision?.FaceGenMeshSourceMod) ||
                    !string.IsNullOrWhiteSpace(decision?.FaceGenSourceMod);
                var hasExplicitTintSource = !string.IsNullOrWhiteSpace(decision?.FaceGenTintSourceMod) ||
                    !string.IsNullOrWhiteSpace(decision?.FaceGenSourceMod);

                var meshCandidate = record.FaceGenCandidates.FirstOrDefault(x =>
                    x.SourceMod.Equals(selectedMeshSource, StringComparison.OrdinalIgnoreCase) &&
                    (string.IsNullOrWhiteSpace(decision?.AppearancePlugin) ||
                     hasExplicitMeshSource ||
                     x.SourcePlugin?.Equals(decision!.AppearancePlugin, StringComparison.OrdinalIgnoreCase) == true) &&
                    x.HasMesh);
                var tintCandidate = record.FaceGenCandidates.FirstOrDefault(x =>
                    x.SourceMod.Equals(selectedTintSource, StringComparison.OrdinalIgnoreCase) &&
                    (string.IsNullOrWhiteSpace(decision?.AppearancePlugin) ||
                     hasExplicitTintSource ||
                     x.SourcePlugin?.Equals(decision!.AppearancePlugin, StringComparison.OrdinalIgnoreCase) == true) &&
                    x.HasTint);

                if (meshCandidate is null && hasExplicitMeshSource)
                    throw new InvalidOperationException($"Selected FaceGen mesh source has no mesh: {record.BasePlugin}:{record.FaceGenFormId} / {selectedMeshSource}");
                if (tintCandidate is null && hasExplicitTintSource)
                    throw new InvalidOperationException($"Selected FaceGen tint source has no tint: {record.BasePlugin}:{record.FaceGenFormId} / {selectedTintSource}");
                if (meshCandidate is not null)
                    copiedFaceGenFiles += CopyFaceGenFile(meshCandidate.MeshRelativePath, meshCandidate.SourceMod, profile, outputModPath);
                if (tintCandidate is not null)
                    copiedFaceGenFiles += CopyFaceGenFile(tintCandidate.TintRelativePath, tintCandidate.SourceMod, profile, outputModPath);
            }
        }

        var pluginPath = Path.Combine(outputModPath, patchPluginName);
        BackupExistingFile(pluginPath);
        using (var stream = File.Create(pluginPath))
        {
            patchMod.WriteToBinaryParallel(stream, new BinaryWriteParameters
            {
                MastersListOrdering = new MastersListOrderingByLoadOrder(loadOrderKeys)
            });
        }
        SetTes4EslFlag(pluginPath);
        return new(pluginPath, patchedNpcs, copiedFaceGenFiles, highPolyHeadPartCache.Count);
    }

    private static Dictionary<NpcRecordKey, INpcGetter> BuildNpcRecordLookup(
        ILoadOrder<IModListing<ISkyrimModGetter>> loadOrder)
    {
        var result = new Dictionary<NpcRecordKey, INpcGetter>();
        foreach (var listing in loadOrder.PriorityOrder)
        {
            if (listing.Mod is null)
                continue;
            var pluginName = listing.ModKey.FileName.String;
            foreach (var npc in listing.Mod.Npcs)
                result[new(pluginName, npc.FormKey.ToString())] = npc;
        }
        return result;
    }
    private static Dictionary<FormKey, IHeadPartGetter> BuildHeadPartRecordLookup(
        ILoadOrder<IModListing<ISkyrimModGetter>> loadOrder)
    {
        var result = new Dictionary<FormKey, IHeadPartGetter>();
        foreach (var listing in loadOrder.PriorityOrder)
        {
            if (listing.Mod is null)
                continue;
            foreach (var headPart in listing.Mod.HeadParts)
                result[headPart.FormKey] = headPart;
        }
        return result;
    }

    private static void ApplyFaceFields(Npc target, INpcGetter face)
    {
        target.DeepCopyIn(face, new Npc.TranslationMask(defaultOn: false)
        {
            FaceMorph = true,
            FaceParts = true,
            TextureLighting = true,
            TintLayers = true,
            Height = true,
            Weight = true,
        });
        target.HeadParts.Clear();
        foreach (var headPart in face.HeadParts)
            target.HeadParts.Add(headPart);
        target.HairColor.SetTo(face.HairColor);
        target.HeadTexture.SetTo(face.HeadTexture);
        target.WornArmor.SetTo(face.WornArmor);
        if (face.Configuration.Flags.HasFlag(NpcConfiguration.Flag.OppositeGenderAnims))
            target.Configuration.Flags |= NpcConfiguration.Flag.OppositeGenderAnims;
        else
            target.Configuration.Flags &= ~NpcConfiguration.Flag.OppositeGenderAnims;
    }

    private static void ApplyHeadPartReplacements(
        Npc target,
        IReadOnlyDictionary<string, string>? replacements)
    {
        if (replacements is null || replacements.Count == 0)
            return;

        var parsed = new Dictionary<FormKey, FormKey>();
        foreach (var replacement in replacements)
        {
            if (!FormKey.TryFactory(replacement.Key, out var oldFormKey))
                throw new InvalidDataException($"Invalid source HeadPart FormKey: {replacement.Key}");
            if (!FormKey.TryFactory(replacement.Value, out var newFormKey))
                throw new InvalidDataException($"Invalid replacement HeadPart FormKey: {replacement.Value}");
            parsed[oldFormKey] = newFormKey;
        }

        var replaced = new HashSet<FormKey>();
        for (var i = 0; i < target.HeadParts.Count; i++)
        {
            var oldFormKey = target.HeadParts[i].FormKey;
            if (!parsed.TryGetValue(oldFormKey, out var newFormKey))
                continue;
            target.HeadParts[i] = new FormLink<IHeadPartGetter>(newFormKey);
            replaced.Add(oldFormKey);
        }

        var missing = parsed.Keys.Where(x => !replaced.Contains(x)).ToArray();
        if (missing.Length > 0)
            throw new InvalidOperationException($"Selected appearance record does not contain HeadPart(s): {string.Join(", ", missing)}");
    }
    private static void ApplyHighPolyHeadPartReplacements(
        Npc target,
        IReadOnlyDictionary<string, string>? replacements,
        SkyrimMod patchMod,
        IReadOnlyDictionary<FormKey, IHeadPartGetter> headPartRecords,
        IDictionary<FormKey, FormKey> compatibilityCache)
    {
        if (replacements is null || replacements.Count == 0)
            return;

        if (!FormKey.TryFactory("000A30:High Poly Head.esm", out var templateKey) ||
            !headPartRecords.TryGetValue(templateKey, out var highPolyTemplate))
            throw new InvalidOperationException("High Poly Head female eyebrow template 000A30:High Poly Head.esm is unavailable.");

        var parsed = new Dictionary<FormKey, FormKey>();
        foreach (var replacement in replacements)
        {
            if (!FormKey.TryFactory(replacement.Key, out var oldFormKey))
                throw new InvalidDataException($"Invalid source HeadPart FormKey: {replacement.Key}");
            if (!FormKey.TryFactory(replacement.Value, out var sgFormKey))
                throw new InvalidDataException($"Invalid SG Brows HeadPart FormKey: {replacement.Value}");
            parsed[oldFormKey] = sgFormKey;
        }

        var replaced = new HashSet<FormKey>();
        for (var i = 0; i < target.HeadParts.Count; i++)
        {
            var oldFormKey = target.HeadParts[i].FormKey;
            if (!parsed.TryGetValue(oldFormKey, out var sgFormKey))
                continue;
            if (!headPartRecords.TryGetValue(sgFormKey, out var sgHeadPart))
                throw new InvalidOperationException($"SG Brows HeadPart is unavailable: {sgFormKey}");

            if (!compatibilityCache.TryGetValue(sgFormKey, out var compatibleFormKey))
            {
                var compatible = patchMod.HeadParts.AddNew();
                compatible.DeepCopyIn(highPolyTemplate, new HeadPart.TranslationMask(defaultOn: true));
                compatible.EditorID = sgHeadPart.EditorID ?? $"Agent_HPH_{sgFormKey.ID:X6}";
                compatible.Flags = sgHeadPart.Flags;
                compatible.Type = sgHeadPart.Type;
                compatible.TextureSet.SetTo(sgHeadPart.TextureSet);
                compatible.Color.SetTo(sgHeadPart.Color);
                compatible.ValidRaces.SetTo(sgHeadPart.ValidRaces);
                compatibleFormKey = compatible.FormKey;
                compatibilityCache[sgFormKey] = compatibleFormKey;
            }

            target.HeadParts[i] = new FormLink<IHeadPartGetter>(compatibleFormKey);
            replaced.Add(oldFormKey);
        }

        var missing = parsed.Keys.Where(x => !replaced.Contains(x)).ToArray();
        if (missing.Length > 0)
            throw new InvalidOperationException($"Selected appearance record does not contain High Poly HeadPart(s): {string.Join(", ", missing)}");
    }
    private static void ApplyNameField(Npc target, INpcGetter nameSource)
    {
        target.DeepCopyIn(nameSource, new Npc.TranslationMask(defaultOn: false)
        {
            Name = true,
        });
    }

    private static bool ShouldPatchVanillaFaceFallback(WinningNpcRecord record) =>
        IsBaseGameFormKey(record.FormKey) &&
        record.FaceGenCandidates.Count == 0 &&
        !record.WinningPlugin.Equals(record.BasePlugin, StringComparison.OrdinalIgnoreCase) &&
        IsKnownRecordOnlyNpcPatch(record.WinningPlugin);

    private static bool IsKnownRecordOnlyNpcPatch(string pluginName) =>
        pluginName.Equals("Tullius Supplement.esp", StringComparison.OrdinalIgnoreCase);

    private static bool ShouldPatchReadableName(
        WinningNpcRecord record,
        IReadOnlyDictionary<NpcRecordKey, INpcGetter> npcRecords)
    {
        if (string.IsNullOrWhiteSpace(record.Name))
            return false;
        var forceReadableName = IsFaceRimPlugin(record.WinningPlugin);
        if (!forceReadableName && !LooksKoreanOrMojibake(record.Name))
            return false;
        if (GetKnownReadableName(record.EditorId) is not null)
            return true;
        if (FindReadableNameSource(record.FormKey, record.WinningPlugin, npcRecords) is not null)
            return true;
        return GetReadableNameFallback(record) is not null;
    }

    private static void ApplyReadableNameIfNeeded(
        Npc target,
        WinningNpcRecord record,
        IReadOnlyDictionary<NpcRecordKey, INpcGetter> npcRecords)
    {
        if (string.IsNullOrWhiteSpace(target.Name?.String))
            return;
        var forceReadableName = IsFaceRimPlugin(record.WinningPlugin);
        if (!forceReadableName && !LooksKoreanOrMojibake(target.Name?.String))
            return;
        var knownName = GetKnownReadableName(record.EditorId);
        if (knownName is not null)
        {
            target.Name = knownName;
            return;
        }
        var readableSource = FindReadableNameSource(record.FormKey, record.WinningPlugin, npcRecords);
        if (readableSource is not null)
        {
            ApplyNameField(target, readableSource);
            return;
        }
        var fallbackName = GetReadableNameFallback(record);
        if (fallbackName is not null)
        {
            target.Name = fallbackName;
            return;
        }
    }

    private static string? GetReadableNameFallback(WinningNpcRecord record)
    {
        if (string.IsNullOrWhiteSpace(record.EditorId))
            return null;
        var name = record.EditorId;
        name = name.Trim('_');
        while (name.Length > 0 && char.IsDigit(name[0]))
            name = name[1..].TrimStart('_');
        if (name.StartsWith("aaa", StringComparison.OrdinalIgnoreCase) && name.Length > 3)
            name = name[3..].TrimStart('_');
        foreach (var prefix in new[] { "dun", "DLC1", "DLC2", "BYOH", "MS", "DA", "DB", "CW", "WE", "HH", "Enc" })
        {
            if (name.StartsWith(prefix, StringComparison.Ordinal) && name.Length > prefix.Length)
            {
                name = name[prefix.Length..];
                break;
            }
        }
        name = StripTrailingDigits(name);
        name = SplitEditorIdWords(name);
        return string.IsNullOrWhiteSpace(name) ? null : name;
    }

    private static string StripTrailingDigits(string text)
    {
        var end = text.Length;
        while (end > 0 && char.IsDigit(text[end - 1]))
            end--;
        return text[..end];
    }

    private static string SplitEditorIdWords(string text)
    {
        var words = new List<string>();
        var start = 0;
        for (var i = 1; i < text.Length; i++)
        {
            var current = text[i];
            var previous = text[i - 1];
            var next = i + 1 < text.Length ? text[i + 1] : '\0';
            var boundary =
                current == '_' ||
                (char.IsUpper(current) && (char.IsLower(previous) || (char.IsUpper(previous) && char.IsLower(next)))) ||
                (char.IsDigit(current) && !char.IsDigit(previous));
            if (!boundary)
                continue;
            AddEditorIdWord(words, text[start..i]);
            start = current == '_' ? i + 1 : i;
        }
        AddEditorIdWord(words, text[start..]);
        return string.Join(' ', words);
    }

    private static void AddEditorIdWord(List<string> words, string word)
    {
        word = word.Trim('_');
        if (string.IsNullOrWhiteSpace(word))
            return;
        words.Add(word);
    }

    private static INpcGetter? FindReadableNameSource(
        string formKey,
        string winningPlugin,
        IReadOnlyDictionary<NpcRecordKey, INpcGetter> npcRecords)
    {
        var candidates = npcRecords
            .Where(x => x.Key.FormKey.Equals(formKey, StringComparison.OrdinalIgnoreCase) &&
                !x.Key.PluginName.Equals(winningPlugin, StringComparison.OrdinalIgnoreCase) &&
                !string.IsNullOrWhiteSpace(x.Value.Name?.String) &&
                !LooksKoreanOrMojibake(x.Value.Name?.String))
            .Select(x => x.Value)
            .ToList();
        return candidates.LastOrDefault();
    }

    private static bool IsBaseGameFormKey(string formKey) =>
        formKey.EndsWith(":Skyrim.esm", StringComparison.OrdinalIgnoreCase) ||
        formKey.EndsWith(":Dawnguard.esm", StringComparison.OrdinalIgnoreCase) ||
        formKey.EndsWith(":HearthFires.esm", StringComparison.OrdinalIgnoreCase) ||
        formKey.EndsWith(":Dragonborn.esm", StringComparison.OrdinalIgnoreCase);

    private static bool IsFaceRimPlugin(string pluginName) =>
        pluginName.Equals("FaceRimNPCReplacer.esp", StringComparison.OrdinalIgnoreCase);

    private static bool LooksKoreanOrMojibake(string? text)
    {
        if (string.IsNullOrWhiteSpace(text))
            return false;
        foreach (var c in text)
        {
            if (c is >= '\uAC00' and <= '\uD7AF')
                return true;
            if (c == '\uFFFD')
                return true;
            if ("ÃÂìëêíåæéðÐ¢çäèœµ°»žŸƒ¼½¾¿¤¥¦§¨©ª«¬®¯²³´¶·¸¹º".Contains(c, StringComparison.Ordinal))
                return true;
        }
        return false;
    }

    private static string? GetKnownReadableName(string? editorId)
    {
        if (string.IsNullOrWhiteSpace(editorId))
            return null;
        return editorId switch
        {
            "ElisifTheFair" => "Elisif the Fair",
            "Ysolda" => "Ysolda",
            "Uthgerd" => "Uthgerd the Unbroken",
            "BrelynaMaryon" => "Brelyna Maryon",
            "dunDarklightIllia" => "Illia",
            "DLC1Serana" => "Serana",
            "DLC1Valerica" => "Valerica",
            "HousecarlWhiterun" => "Lydia",
            "Rikke" => "Legate Rikke",
            "CWBattleRikke" => "Legate Rikke",
            "HousecarlSolitude" => "Jordis the Sword-Maiden",
            "Sapphire" => "Sapphire",
            _ => null,
        };
    }

    private static int CopyFaceGenFile(
        string? relativePath,
        string sourceModName,
        Mo2Profile profile,
        string outputModPath)
    {
        if (string.IsNullOrWhiteSpace(relativePath))
            return 0;
        var sourceMod = profile.EnabledMods.FirstOrDefault(x =>
            x.Name.Equals(sourceModName, StringComparison.OrdinalIgnoreCase));
        if (sourceMod is null)
            return 0;
        var sourcePath = Path.Combine(sourceMod.Path, relativePath);
        if (!File.Exists(sourcePath))
            return 0;
        var destinationPath = Path.Combine(outputModPath, relativePath);
        Directory.CreateDirectory(Path.GetDirectoryName(destinationPath)!);
        BackupExistingFile(destinationPath);
        File.Copy(sourcePath, destinationPath);
        return 1;
    }

    private static void BackupExistingFile(string path)
    {
        if (!File.Exists(path))
            return;
        var backupPath = $"{path}.{DateTime.Now:yyyyMMdd_HHmmss}.bak";
        File.Move(path, backupPath);
    }

    private static void BackupExistingDirectory(string path)
    {
        if (!Directory.Exists(path))
            return;
        var backupPath = $"{path}.{DateTime.Now:yyyyMMdd_HHmmss}.bak";
        Directory.Move(path, backupPath);
    }

    private static void SetTes4EslFlag(string pluginPath)
    {
        using var stream = File.Open(pluginPath, FileMode.Open, FileAccess.ReadWrite, FileShare.None);
        Span<byte> header = stackalloc byte[12];
        if (stream.Read(header) != header.Length ||
            !header[..4].SequenceEqual("TES4"u8))
            throw new InvalidDataException($"Unexpected plugin header in {pluginPath}");
        var flags = BinaryPrimitives.ReadUInt32LittleEndian(header[8..12]);
        flags |= 0x00000200;
        BinaryPrimitives.WriteUInt32LittleEndian(header[8..12], flags);
        stream.Position = 0;
        stream.Write(header);
    }
}

sealed record PatchBuildResult(
    string PluginPath,
    int PatchedNpcs,
    int CopiedFaceGenFiles,
    int CreatedHighPolyHeadParts);

sealed record NpcRecordKey(
    string PluginName,
    string FormKey);

static class MutagenNpcAuditor
{
    public static IReadOnlyList<WinningNpcRecord> ReadWinningNpcRecords(Mo2Profile profile, int limit)
    {
        var pluginFiles = FaceGenAuditor.ScanPluginFiles(profile);
        var faceGenAssets = FaceGenAuditor.ScanFaceGenAssets(profile.EnabledMods);
        var faceGenIndex = FaceGenIndex.Build(faceGenAssets);
        var stagedDataPath = StagePluginFiles(profile, pluginFiles);
        var loadOrderKeys = BuildLoadOrder(profile, pluginFiles)
            .Select(x => ModKey.FromNameAndExtension(x))
            .ToList();
        var loadOrder = LoadOrder.Import<ISkyrimModGetter>(stagedDataPath, loadOrderKeys, GameRelease.SkyrimSE);
        var overrideIndex = BuildNpcOverrideIndex(loadOrder, pluginFiles);
        var availableHeadParts = loadOrder.PriorityOrder
            .Where(x => x.Mod is not null)
            .SelectMany(x => x.Mod!.HeadParts)
            .Select(x => x.FormKey)
            .ToHashSet();
        return loadOrder.PriorityOrder.Npc().WinningContextOverrides()
            .Take(limit)
            .Select(ctx =>
            {
                var npc = ctx.Record;
                var basePluginName = npc.FormKey.ModKey.FileName.String;
                var faceGenFormId = npc.FormKey.ID.ToString("x8");
                var faceGenStatus = faceGenIndex.GetStatus(basePluginName, faceGenFormId);
                var formKey = npc.FormKey.ToString();
                overrideIndex.TryGetValue(formKey, out var npcOverrides);
                faceGenStatus = faceGenStatus with { Candidates = faceGenStatus.Candidates.Select(candidate => candidate with
                {
                    SourcePlugin = npcOverrides?.LastOrDefault(x => x.SourceMod.Equals(candidate.SourceMod, StringComparison.OrdinalIgnoreCase))?.PluginName
                }).ToList() };
                var plan = BuildPatchPlan(
                    formKey,
                    ctx.ModKey.FileName.String,
                    faceGenStatus,
                    overrideIndex);
                return new WinningNpcRecord(
                    npc.FormKey.ToString(),
                    ctx.ModKey.FileName.String,
                    basePluginName,
                    faceGenFormId,
                    npc.EditorID,
                    npc.Name?.String,
                    npc.Configuration.Flags.ToString(),
                    faceGenStatus.WinningMesh,
                    faceGenStatus.WinningTint,
                    faceGenStatus.Candidates,
                    faceGenStatus.Issues,
                    plan,
                    npc.HeadParts.Select(x => x.FormKey.ToString()).ToList(),
                    npc.HeadParts.Where(x => !availableHeadParts.Contains(x.FormKey)).Select(x => x.FormKey.ToString()).ToList());
            })
            .ToList();
    }

    private static IReadOnlyDictionary<string, List<NpcOverrideSource>> BuildNpcOverrideIndex(
        ILoadOrder<IModListing<ISkyrimModGetter>> loadOrder,
        IReadOnlyDictionary<string, PluginFileInfo> pluginFiles)
    {
        var result = new Dictionary<string, List<NpcOverrideSource>>(StringComparer.OrdinalIgnoreCase);
        foreach (var listing in loadOrder.PriorityOrder)
        {
            var pluginName = listing.ModKey.FileName.String;
            pluginFiles.TryGetValue(pluginName, out var pluginFile);
            if (listing.Mod is null)
                continue;
            foreach (var npc in listing.Mod.Npcs)
            {
                var key = npc.FormKey.ToString();
                if (!result.TryGetValue(key, out var list))
                {
                    list = [];
                    result[key] = list;
                }
                list.Add(new(pluginName, pluginFile?.SourceMod ?? "Game Data"));
            }
        }
        return result;
    }

    private static NpcPatchPlan? BuildPatchPlan(
        string formKey,
        string winningPlugin,
        FaceGenStatus faceGenStatus,
        IReadOnlyDictionary<string, List<NpcOverrideSource>> overrideIndex)
    {
        var candidate = faceGenStatus.Candidates.FirstOrDefault(x => x.HasMesh && x.HasTint);
        if (candidate is null)
            return null;
        if (winningPlugin.Equals("Agent_NPC_ConflictResolution.esp", StringComparison.OrdinalIgnoreCase))
            return new("already-winning-face-source", winningPlugin, "Agent NPC Conflict Resolution", null);
        if (!overrideIndex.TryGetValue(formKey, out var overrides))
            return new("blocked-no-override-chain", null, candidate.SourceMod, null);
        var faceOverride = !string.IsNullOrWhiteSpace(candidate.SourcePlugin)
            ? overrides.LastOrDefault(x => x.PluginName.Equals(candidate.SourcePlugin, StringComparison.OrdinalIgnoreCase))
            : overrides.LastOrDefault(x => x.SourceMod.Equals(candidate.SourceMod, StringComparison.OrdinalIgnoreCase));
        if (faceOverride is null)
        {
            var translatedFaceOverride = FindTranslatedFaceRecordOverride(candidate, overrides);
            if (translatedFaceOverride is not null &&
                !translatedFaceOverride.PluginName.Equals(winningPlugin, StringComparison.OrdinalIgnoreCase))
                return new(
                    "patch-default-from-winning-face-from-candidate",
                    translatedFaceOverride.PluginName,
                    candidate.SourceMod,
                    translatedFaceOverride.PluginName);
            return new("blocked-facegen-has-no-matching-record-source", null, candidate.SourceMod, null);
        }
        if (faceOverride.PluginName.Equals(winningPlugin, StringComparison.OrdinalIgnoreCase))
            return new("already-winning-face-source", faceOverride.PluginName, candidate.SourceMod, null);
        return new("patch-default-from-winning-face-from-candidate", faceOverride.PluginName, candidate.SourceMod, faceOverride.PluginName);
    }

    private static NpcOverrideSource? FindTranslatedFaceRecordOverride(
        FaceGenCandidate candidate,
        IReadOnlyList<NpcOverrideSource> overrides)
    {
        if (!candidate.SourceMod.Contains("Pussy NPC Original", StringComparison.OrdinalIgnoreCase))
            return null;
        return overrides.LastOrDefault(x =>
            x.PluginName.Equals("pussy.esp", StringComparison.OrdinalIgnoreCase));
    }

    public static IReadOnlyList<string> BuildLoadOrder(
        Mo2Profile profile,
        IReadOnlyDictionary<string, PluginFileInfo> pluginFiles)
    {
        var result = new List<string>();
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var pluginName in profile.LoadOrder)
        {
            if (!profile.EnabledPlugins.Contains(pluginName))
                continue;
            if (!pluginFiles.ContainsKey(pluginName))
                continue;
            if (seen.Add(pluginName))
                result.Add(pluginName);
        }
        foreach (var pluginName in profile.EnabledPlugins.OrderBy(x => x, StringComparer.OrdinalIgnoreCase))
        {
            if (!pluginFiles.ContainsKey(pluginName))
                continue;
            if (seen.Add(pluginName))
                result.Add(pluginName);
        }
        return result;
    }

    public static string StagePluginFiles(
        Mo2Profile profile,
        IReadOnlyDictionary<string, PluginFileInfo> pluginFiles)
    {
        var stageRoot = Path.Combine(
            Environment.CurrentDirectory,
            "staging",
            $"{profile.ProfileName}-{DateTime.Now:yyyyMMdd-HHmmss}");
        Directory.CreateDirectory(stageRoot);
        foreach (var pluginName in BuildLoadOrder(profile, pluginFiles))
        {
            var source = pluginFiles[pluginName].FullPath;
            var destination = Path.Combine(stageRoot, pluginName);
            File.Copy(source, destination, overwrite: true);
        }
        return stageRoot;
    }
}

sealed record WinningNpcRecord(
    string FormKey,
    string WinningPlugin,
    string BasePlugin,
    string FaceGenFormId,
    string? EditorId,
    string? Name,
    string Flags,
    FaceGenAssetReport? WinningFaceGenMesh,
    FaceGenAssetReport? WinningFaceGenTint,
    IReadOnlyList<FaceGenCandidate> FaceGenCandidates,
    IReadOnlyList<string> FaceGenIssues,
    NpcPatchPlan? PatchPlan,
    IReadOnlyList<string> HeadParts,
    IReadOnlyList<string> UnresolvedHeadParts);

sealed record NpcPatchPlan(
    string Action,
    string? FacePlugin,
    string? FaceSourceMod,
    string? NamePlugin);

sealed record NpcOverrideSource(
    string PluginName,
    string SourceMod);

sealed record FaceGenCandidate(
    string SourceMod,
    int FilePriority,
    bool HasMesh,
    bool HasTint,
    string? MeshRelativePath,
    string? TintRelativePath,
    string? SourcePlugin = null);

sealed record FaceGenStatus(
    FaceGenAssetReport? WinningMesh,
    FaceGenAssetReport? WinningTint,
    IReadOnlyList<FaceGenCandidate> Candidates,
    IReadOnlyList<string> Issues);

static class FaceGenIndex
{
    public static FaceGenIndexData Build(IReadOnlyList<FaceGenAsset> assets)
    {
        var map = assets
            .GroupBy(x => new FaceGenKey(x.PluginDirectory, x.FormId), FaceGenKey.Comparer)
            .ToDictionary(g => g.Key, g => g.ToList(), FaceGenKey.Comparer);
        return new(map);
    }
}

sealed class FaceGenIndexData
{
    private readonly IReadOnlyDictionary<FaceGenKey, List<FaceGenAsset>> assets;

    public FaceGenIndexData(IReadOnlyDictionary<FaceGenKey, List<FaceGenAsset>> assets)
    {
        this.assets = assets;
    }

    public FaceGenStatus GetStatus(string pluginDirectory, string formId)
    {
        var key = new FaceGenKey(pluginDirectory, formId);
        if (!assets.TryGetValue(key, out var matches))
        {
            return new(null, null, [], []);
        }
        var meshes = matches.Where(x => x.Kind == FaceGenKind.Mesh).OrderBy(x => x.FilePriority).ToList();
        var tints = matches.Where(x => x.Kind == FaceGenKind.Tint).OrderBy(x => x.FilePriority).ToList();
        var winningMesh = meshes.FirstOrDefault();
        var winningTint = tints.FirstOrDefault();
        var issues = new List<string>();
        if (winningMesh is null)
            issues.Add("missing-mesh");
        if (winningTint is null)
            issues.Add("missing-tint");
        if (winningMesh is not null && winningTint is not null &&
            !winningMesh.SourceMod.Equals(winningTint.SourceMod, StringComparison.OrdinalIgnoreCase))
            issues.Add("mesh-tint-winning-mod-mismatch");
        var candidates = matches
            .GroupBy(x => x.SourceMod, StringComparer.OrdinalIgnoreCase)
            .Select(g =>
            {
                var mesh = g.Where(x => x.Kind == FaceGenKind.Mesh).OrderBy(x => x.FilePriority).FirstOrDefault();
                var tint = g.Where(x => x.Kind == FaceGenKind.Tint).OrderBy(x => x.FilePriority).FirstOrDefault();
                return new FaceGenCandidate(
                    g.Key,
                    Math.Min(mesh?.FilePriority ?? int.MaxValue, tint?.FilePriority ?? int.MaxValue),
                    mesh is not null,
                    tint is not null,
                    mesh?.RelativePath,
                    tint?.RelativePath);
            })
            .OrderBy(x => AppearanceSourceRank(x.SourceMod))
            .ThenBy(x => x.FilePriority)
            .ThenBy(x => x.SourceMod, StringComparer.OrdinalIgnoreCase)
            .ToList();
        return new(winningMesh?.ToReport(), winningTint?.ToReport(), candidates, issues);
    }

    private static int AppearanceSourceRank(string sourceMod)
    {
        if (sourceMod.Contains("Agent NPC Conflict Resolution", StringComparison.OrdinalIgnoreCase))
            return 0;
        if (IsBotoxBase(sourceMod))
            return 300;
        if (IsFaceRimBase(sourceMod))
            return 200;
        if (sourceMod.Equals("Game Data", StringComparison.OrdinalIgnoreCase))
            return 400;
        return 100;
    }

    private static bool IsFaceRimBase(string sourceMod) =>
        sourceMod.Contains("FaceRim NPC Replacer", StringComparison.OrdinalIgnoreCase);

    private static bool IsBotoxBase(string sourceMod) =>
        sourceMod.Contains("Botox For Skyrim", StringComparison.OrdinalIgnoreCase) ||
        sourceMod.Contains("Botox of Skyrim", StringComparison.OrdinalIgnoreCase);
}

sealed record NpcDecision(
    string NpcKey,
    string AppearanceSourceMod,
    string? AppearancePlugin,
    string? NamePlugin,
    string? FaceGenSourceMod = null,
    string? FaceGenMeshSourceMod = null,
    string? FaceGenTintSourceMod = null,
    IReadOnlyDictionary<string, string>? HeadPartReplacements = null,
    IReadOnlyDictionary<string, string>? HighPolyHeadPartReplacements = null);
sealed class DecisionSet
{
    private readonly Dictionary<string, NpcDecision> items;
    private DecisionSet(IEnumerable<NpcDecision> values) => items = values.ToDictionary(x => x.NpcKey, StringComparer.OrdinalIgnoreCase);
    public static DecisionSet Load(string? path)
    {
        if (string.IsNullOrWhiteSpace(path)) return new([]);
        var root = JsonSerializer.Deserialize<DecisionDocument>(File.ReadAllText(path), Json.Options) ?? throw new InvalidDataException("Invalid decision document");
        if (root.SchemaVersion != 1) throw new InvalidDataException("Unsupported decision schema");
        return new(root.Decisions ?? []);
    }
    public NpcDecision? For(string basePlugin, string formId) => items.GetValueOrDefault($"{basePlugin}:{formId.ToUpperInvariant().PadLeft(8, '0')}");
}
sealed record DecisionDocument(int SchemaVersion, IReadOnlyList<NpcDecision>? Decisions);

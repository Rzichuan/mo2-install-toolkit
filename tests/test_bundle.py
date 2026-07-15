import json
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "mo2-mod-installer"


class BundleContractTests(unittest.TestCase):
    def test_one_authoritative_skill_source(self):
        skill = SKILL / "SKILL.md"
        contract = SKILL / "references" / "agent-contract.md"
        usage = SKILL / "references" / "tool-usage.md"
        self.assertTrue(skill.is_file())
        self.assertTrue(contract.is_file())
        self.assertTrue(usage.is_file())
        root_adapter = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("skills/mo2-mod-installer/SKILL.md", root_adapter)
        self.assertIn("authoritative workflow", root_adapter)

    def test_skill_bootstraps_a_pinned_absolute_executable(self):
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        bootstrap = (SKILL / "scripts" / "ensure-runtime.ps1").read_text(encoding="utf-8")
        manifest = json.loads((SKILL / "runtime-manifest.json").read_text(encoding="utf-8"))
        self.assertIn("scripts\\ensure-runtime.ps1 -Json", text)
        self.assertIn("absolute `tool_path`", text)
        self.assertIn("runtime-manifest.json", text)
        self.assertIn("Get-FileSha256", bootstrap)
        self.assertIn("Security.Cryptography.SHA256", bootstrap)
        self.assertIn("Threading.Mutex", bootstrap)
        self.assertIn("Invoke-WebRequest", bootstrap)
        self.assertEqual(f"v{manifest['tool_version']}", manifest["release_tag"])
        self.assertNotIn("/latest/", manifest["asset_url"])

    def test_skill_uses_layered_tool_documentation(self):
        skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        contract = (SKILL / "references" / "agent-contract.md").read_text(encoding="utf-8")
        usage = (SKILL / "references" / "tool-usage.md").read_text(encoding="utf-8")
        self.assertIn("references/tool-usage.md", skill)
        self.assertIn("references/agent-contract.md", skill)
        self.assertIn("tool-usage.md", contract)
        self.assertNotIn("--after-plugin", skill)
        self.assertNotIn("--after-plugin", usage)
        for command in (
            "config set --archive-directory",
            "nexus batch prepare",
            "install inspect",
            "install plan",
            "install apply",
            "install resume",
            "archive retry",
            "root deploy",
            "profile audit",
            "backup restore",
        ):
            self.assertIn(command, usage)
        self.assertIn("## Exit handling", usage)

    def test_versions_share_project_version(self):
        version = tomllib.loads((ROOT / "pyproject.toml").read_bytes().decode("utf-8"))["project"]["version"]
        namespace = {}
        exec((ROOT / "src" / "mo2_agent_toolkit" / "__init__.py").read_text(encoding="utf-8"), namespace)
        plugin = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        manifest = json.loads((SKILL / "runtime-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(version, namespace["__version__"])
        self.assertEqual(version, plugin["version"])
        self.assertEqual(version, manifest["tool_version"])
        self.assertEqual(version, manifest["toolkit_version"])

    def test_release_is_tag_driven_and_packages_runtime_only(self):
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        package = (ROOT / "scripts" / "package-release.ps1").read_text(encoding="utf-8")
        self.assertIn("actions/setup-dotnet@v4", workflow)
        self.assertIn("scripts/package-release.ps1", workflow)
        self.assertIn("github.ref_type == 'tag'", workflow)
        self.assertNotIn("release:\n    types: [published]", workflow)
        manifest = json.loads((SKILL / "runtime-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual("mo2-runtime", manifest["archive_root"])
        self.assertEqual(f"mo2-runtime-v{manifest['tool_version']}-win-x64.zip", manifest["asset_name"])
        self.assertIn("checksum_asset_name", package)
        self.assertIn("Compress-Archive", package)
        self.assertIn("$ToolDirectory", package)
        self.assertIn("runtime.json", package)
        self.assertIn("third_party", package)
        self.assertNotIn("mo2-mod-installer-bundle", package)
        self.assertNotIn("SKILL.md", package)

    def test_bundle_includes_project_docs_and_vendored_licenses(self):
        build = (ROOT / "scripts" / "build-bundle.ps1").read_text(encoding="utf-8")
        notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        project_license = (ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("(Join-Path $Root 'LICENSE')", build)
        self.assertIn("(Join-Path $Stage 'LICENSE')", build)
        self.assertIn("(Join-Path $Stage 'runtime.json')", build)
        self.assertIn("schema_version = 1", build)
        self.assertIn("(Join-Path $Stage 'references\\tool-usage.md')", build)
        self.assertIn("THIRD_PARTY_NOTICES.md", build)
        self.assertIn("third_party\\pyfomod\\LICENSE", build)
        self.assertIn("third_party\\mutagen\\LICENSE", build)
        self.assertIn("third_party\\newtonsoft-json\\LICENSE.md", build)
        self.assertIn("GNU GENERAL PUBLIC LICENSE", project_license)
        self.assertIn("pyfomod 1.2.1", notices)
        self.assertIn("Mutagen.Bethesda", notices)
        self.assertIn("Newtonsoft.Json", notices)
        self.assertTrue((ROOT / "third_party" / "pyfomod" / "LICENSE").is_file())


    def test_codex_marketplace_points_to_repository_plugin(self):
        marketplace = json.loads((ROOT / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8"))
        self.assertEqual("mo2-install-toolkit", marketplace["name"])
        self.assertEqual("MO2 Agent Toolkit", marketplace["interface"]["displayName"])
        self.assertEqual(1, len(marketplace["plugins"]))
        entry = marketplace["plugins"][0]
        self.assertEqual("mo2-agent-toolkit", entry["name"])
        self.assertEqual("./", entry["source"]["path"])
        self.assertEqual("AVAILABLE", entry["policy"]["installation"])
        self.assertEqual("ON_INSTALL", entry["policy"]["authentication"])

    def test_clean_checkout_build_uses_in_repository_sidecar(self):
        build = (ROOT / "scripts" / "build.ps1").read_text(encoding="utf-8")
        self.assertIn("sidecars\\npc-agent-patcher\\NpcAgentPatcher.csproj", build)
        self.assertNotIn("..\\npc-agent-patcher", build)
        self.assertTrue((ROOT / "sidecars" / "npc-agent-patcher" / "Program.cs").is_file())

    def test_project_uses_gpl_3_or_later_metadata(self):
        project = tomllib.loads((ROOT / "pyproject.toml").read_bytes().decode("utf-8"))["project"]
        plugin = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual("GPL-3.0-or-later", project["license"])
        self.assertEqual("GPL-3.0-or-later", plugin["license"])

    def test_adapter_uses_stable_shared_bundle(self):
        install = (ROOT / "scripts" / "install-adapters.ps1").read_text(encoding="utf-8")
        uninstall = (ROOT / "scripts" / "uninstall-adapters.ps1").read_text(encoding="utf-8")
        self.assertIn("MO2AgentToolkit", install)
        self.assertIn("skill-bundles", install)
        self.assertIn("New-Item -ItemType Junction", install)
        self.assertIn("bin\\_internal", install)
        self.assertIn("adapter-install.json", uninstall)
        self.assertIn("Refusing to remove unmanaged or changed adapter", uninstall)


if __name__ == "__main__":
    unittest.main()

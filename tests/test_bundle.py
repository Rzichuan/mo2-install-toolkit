import json
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class BundleContractTests(unittest.TestCase):
    def test_one_authoritative_skill_source(self):
        skill = ROOT / "skills" / "mo2-mod-installer" / "SKILL.md"
        contract = ROOT / "skills" / "mo2-mod-installer" / "references" / "agent-contract.md"
        self.assertTrue(skill.is_file())
        self.assertTrue(contract.is_file())
        self.assertFalse((ROOT / "claude" / "skills" / "mo2-mod-installer").exists())

    def test_skill_requires_absolute_bundled_executable(self):
        text = (ROOT / "skills" / "mo2-mod-installer" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("$HOME/.claude/skills/mo2-mod-installer/bin/mo2-tool.exe", text)
        self.assertIn("$HOME/.codex/skills/mo2-mod-installer/bin/mo2-tool.exe", text)
        self.assertIn("bin/_internal", text)
        self.assertIn("never to the shell's current working directory", text)
        self.assertIn("fall back to another `mo2-tool` on `PATH`", text)

    def test_versions_share_project_version(self):
        version = tomllib.loads((ROOT / "pyproject.toml").read_bytes().decode("utf-8"))["project"]["version"]
        namespace = {}
        exec((ROOT / "src" / "mo2_agent_toolkit" / "__init__.py").read_text(encoding="utf-8"), namespace)
        plugin = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(version, namespace["__version__"])
        self.assertEqual(version, plugin["version"])

    def test_release_contains_bundle_not_legacy_root_bin(self):
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertIn("dist/mo2-mod-installer-bundle", workflow)
        self.assertIn("skill-bundle/mo2-mod-installer", workflow)
        self.assertNotIn("release/mo2-agent-toolkit/bin", workflow)
        self.assertNotIn("Copy-Item dist/mo2-tool/*", workflow)

    def test_bundle_includes_project_and_vendored_licenses(self):
        build = (ROOT / "scripts" / "build-bundle.ps1").read_text(encoding="utf-8")
        notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        project_license = (ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("(Join-Path $Root 'LICENSE')", build)
        self.assertIn("(Join-Path $Stage 'LICENSE')", build)
        self.assertIn("THIRD_PARTY_NOTICES.md", build)
        self.assertIn("third_party\\pyfomod\\LICENSE", build)
        self.assertIn("GNU GENERAL PUBLIC LICENSE", project_license)
        self.assertIn("pyfomod 1.2.1", notices)
        self.assertTrue((ROOT / "third_party" / "pyfomod" / "LICENSE").is_file())

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

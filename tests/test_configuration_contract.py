from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ConfigurationContractTests(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_skill_says_unique_candidate_is_not_authorization(self):
        skill = self.read("skills/mo2-mod-installer/SKILL.md")
        self.assertIn("A sole candidate", skill)
        self.assertIn("never authorization", skill)

    def test_contract_requires_current_flow_confirmation_and_complete_summary(self):
        contract = self.read("skills/mo2-mod-installer/references/agent-contract.md")
        self.assertIn("current conversation flow", contract)
        for value in ("instance root", "derived `mods`", "Profile", "game directory", "download directory", "archive directory", "7-Zip"):
            self.assertIn(value, contract)

    def test_writing_examples_have_explicit_instance_and_profile(self):
        documents = [
            self.read("README.md"),
            self.read("README.zh-CN.md"),
            self.read("skills/mo2-mod-installer/references/tool-usage.md"),
        ]
        for document in documents:
            setup_lines = [line for line in document.splitlines() if line.lstrip().startswith("& $Tool setup ") and "--dry-run" not in line]
            self.assertTrue(setup_lines)
            for line in setup_lines:
                self.assertIn("--instance", line)
                self.assertIn("--profile", line)

    def test_no_document_allows_bare_setup_json(self):
        documents = [ROOT / "AGENTS.md", ROOT / "skills/mo2-mod-installer/SKILL.md", *ROOT.glob("README*.md"), *ROOT.glob("skills/mo2-mod-installer/references/*.md")]
        forbidden = "If auto-discovery returns one unambiguous instance and Profile, `setup --json` may be used without selectors."
        for path in documents:
            self.assertNotIn(forbidden, path.read_text(encoding="utf-8"), str(path))


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path

from mo2_agent_toolkit.metadata import MetadataError, prepare_meta_ini, validate_meta_ini


class MetadataTests(unittest.TestCase):
    def source(self):
        return {"provider":"nexus","mod_id":133568,"file_id":751019,
                "official_filename":"MfgFix NG-133568-1-0-9-1778493989.zip",
                "version":"1.0.9","last_modified":"2026-05-11T10:06:29Z"}

    def test_merge_preserves_unknown_values_and_writes_literal_backslash_key(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); staged=root/"staged"; staged.mkdir(); old=root/"meta.ini"
            old.write_text("[General]\ncategory=42\nversion=1.0.4\n\n[installedFiles]\nsize=1\n1\\modid=133568\n1\\fileid=1\n",encoding="utf-8")
            result=prepare_meta_ini(staged,old,self.source()); text=(staged/"meta.ini").read_text(encoding="utf-8")
            self.assertEqual(result["action"],"merged"); self.assertIn("category=42",text)
            self.assertIn(r"1\fileid=751019",text); self.assertNotIn("\f",text)
            self.assertTrue(validate_meta_ini(staged/"meta.ini",self.source())["valid"])

    def test_control_character_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"meta.ini"; path.write_bytes(b"[installedFiles]\n1\x0cileid=751019\n")
            with self.assertRaises(MetadataError):validate_meta_ini(path)

    def test_new_nexus_install_creates_minimal_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            staged=Path(temp); result=prepare_meta_ini(staged,None,self.source())
            self.assertEqual(result["action"],"created"); self.assertTrue((staged/"meta.ini").is_file())
            self.assertTrue(validate_meta_ini(staged/"meta.ini",self.source())["valid"])


if __name__ == "__main__":
    unittest.main()

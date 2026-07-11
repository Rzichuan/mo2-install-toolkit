import contextlib
import importlib.util
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class NexusDownloadLegacyTests(unittest.TestCase):
    def load_module(self):
        source=Path(__file__).parents[1]/"src"/"mo2_agent_toolkit"/"legacy"/"nexus-download.py"
        spec=importlib.util.spec_from_file_location("test_nexus_download_backend",source)
        module=importlib.util.module_from_spec(spec)
        with patch.dict(os.environ,{"NEXUS_API_KEY":"test-only","MO2_INSTANCE_PATH":str(source.parent)},clear=False):
            spec.loader.exec_module(module)
        return module

    def test_direct_download_uses_official_nexus_filename(self):
        module=self.load_module()
        official="MfgFix NG-133568-1-0-9-1778493989.zip"
        response={"files":[{"file_id":751019,"file_name":official,"version":"1.0.9"}]}
        with tempfile.TemporaryDirectory() as temp:
            destination=[]
            def download(_mod_id,_file_id,path):
                destination.append(Path(path)); Path(path).write_bytes(b"x"*2048); return True,"api_direct"
            with patch.object(module,"fetch",return_value=response), patch.object(module,"try_api_download",side_effect=download):
                out=io.StringIO()
                with contextlib.redirect_stdout(out):module.cmd_download(133568,751019,temp,json_out=True)
            self.assertEqual(destination[0].name,official)
            self.assertTrue((Path(temp)/official).is_file())
            self.assertIn(f'"official_filename": "{official}"',out.getvalue())


if __name__ == "__main__":
    unittest.main()

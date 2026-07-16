import contextlib
import io
import importlib
import json
from pathlib import Path
import tempfile
import unittest
from ctypes import wintypes
from unittest.mock import Mock, patch
import urllib.error

from mo2_agent_toolkit import auth, cli
from mo2_agent_toolkit.auth_gui import GuiResult
import mo2_agent_toolkit.auth_gui as auth_gui


class AuthTests(unittest.TestCase):
    def test_validate_and_save_is_atomic(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "secrets" / "nexus_api_key.dpapi"
            with patch.object(auth, "validate_key"), patch.object(auth, "dpapi_protect", return_value=b"cipher"):
                auth.validate_and_save("a" * 32, target)
            self.assertEqual(target.read_bytes(), b"cipher")
            self.assertFalse(target.with_name(target.name + ".tmp").exists())

    def test_invalid_key_does_not_replace_existing_secret(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "key.dpapi"
            target.write_bytes(b"old")
            error = auth.AuthError("invalid", 2, "invalid_credential")
            with patch.object(auth, "validate_key", side_effect=error), patch.object(auth, "dpapi_protect"):
                with self.assertRaises(auth.AuthError):
                    auth.validate_and_save("a" * 32, target)
            self.assertEqual(target.read_bytes(), b"old")

    def test_unauthorized_response_is_redacted(self):
        secret = "sensitive-key-never-output"
        response = urllib.error.HTTPError(auth.VALIDATE_URL, 401, "Unauthorized", {}, None)
        with patch("urllib.request.urlopen", side_effect=response):
            with self.assertRaises(auth.AuthError) as caught:
                auth.validate_key(secret)
        self.assertEqual(caught.exception.category, "invalid_credential")
        self.assertNotIn(secret, str(caught.exception))

    def test_network_failure_is_not_saved(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "key.dpapi"
            target.write_bytes(b"old")
            with patch.object(auth, "validate_key", side_effect=auth.AuthError("offline", 4, "network_error")):
                with self.assertRaises(auth.AuthError):
                    auth.validate_and_save("a" * 32, target)
            self.assertEqual(target.read_bytes(), b"old")

    def test_status_does_not_claim_current_online_validation(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "key.dpapi"
            target.write_bytes(b"cipher")
            with patch.object(auth, "dpapi_unprotect", return_value=b"value"):
                status = auth.credential_status(target)
            self.assertEqual(status, {"configured": True, "provider": "windows_dpapi", "decryptable": True})
            self.assertNotIn("validated", status)


class AuthCliTests(unittest.TestCase):
    def test_auth_flags_are_mutually_exclusive(self):
        with self.assertRaises(SystemExit):
            cli.parser().parse_args(["auth", "set", "--gui", "--console"])

    def test_gui_cursor_type_falls_back_to_handle_when_alias_is_missing(self):
        original = getattr(wintypes, "HCURSOR", None)
        try:
            if hasattr(wintypes, "HCURSOR"):
                delattr(wintypes, "HCURSOR")
            importlib.reload(auth_gui)
            self.assertIs(auth_gui.HCURSOR, wintypes.HANDLE)
        finally:
            if original is not None:
                wintypes.HCURSOR = original
            importlib.reload(auth_gui)

    def test_gui_success_emits_metadata_only(self):
        secret = "sensitive-key-never-output"
        result = GuiResult("success", True)
        output = io.StringIO()
        with patch("mo2_agent_toolkit.auth_gui.run_auth_gui", return_value=result), contextlib.redirect_stdout(output):
            code = cli.main(["auth", "set", "--gui", "--json"])
        payload = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["data"]["input_mode"], "gui")
        self.assertNotIn(secret, output.getvalue())

    def test_gui_cancel_is_not_an_error(self):
        output = io.StringIO()
        result = GuiResult("cancelled", False)
        with patch("mo2_agent_toolkit.auth_gui.run_auth_gui", return_value=result), contextlib.redirect_stdout(output):
            code = cli.main(["auth", "set", "--gui", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "cancelled")

    def test_console_is_default_and_validates(self):
        output = io.StringIO()
        with patch("getpass.getpass", return_value="a" * 32), patch.object(cli, "validate_and_save") as save, contextlib.redirect_stdout(output):
            code = cli.main(["auth", "set", "--json"])
        self.assertEqual(code, 0)
        save.assert_called_once()
        self.assertEqual(json.loads(output.getvalue())["data"]["input_mode"], "console")


if __name__ == "__main__":
    unittest.main()

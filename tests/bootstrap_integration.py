from __future__ import annotations

import concurrent.futures
import hashlib
import http.server
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SKILL = ROOT / "skills" / "mo2-mod-installer"
BUNDLE = ROOT / "dist" / "mo2-mod-installer-bundle"
RELEASE = ROOT / "release"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


class BootstrapIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if os.name != "nt":
            raise unittest.SkipTest("runtime bootstrap is Windows-only")
        cls.base_manifest = json.loads((SOURCE_SKILL / "runtime-manifest.json").read_text(encoding="utf-8"))
        cls.asset = RELEASE / cls.base_manifest["asset_name"]
        cls.checksum = RELEASE / cls.base_manifest["checksum_asset_name"]
        if not BUNDLE.is_dir() or not cls.asset.is_file() or not cls.checksum.is_file():
            raise RuntimeError("run scripts/build.ps1 and scripts/package-release.ps1 before bootstrap integration tests")

    def setUp(self) -> None:
        self.temp = Path(tempfile.mkdtemp(prefix="mo2-bootstrap-", dir=os.environ.get("TEMP"))) / "含 空格"
        self.temp.mkdir(parents=True)
        self.server_root = self.temp / "server"
        self.release_root = self.server_root / self.base_manifest["release_tag"]
        self.release_root.mkdir(parents=True)
        shutil.copy2(self.asset, self.release_root / self.asset.name)
        shutil.copy2(self.checksum, self.release_root / self.checksum.name)
        self.skill = self.temp / "thin skill" / "mo2-mod-installer"
        shutil.copytree(SOURCE_SKILL, self.skill)
        self.port = free_port()
        handler = lambda *a, **kw: QuietHandler(*a, directory=str(self.server_root), **kw)
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", self.port), handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.write_manifest(self.base_manifest)

    def tearDown(self) -> None:
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
        shutil.rmtree(self.temp.parent, ignore_errors=True)

    def write_manifest(self, data: dict[str, object], *, port: int | None = None) -> Path:
        manifest = dict(data)
        selected_port = self.port if port is None else port
        base = f"http://127.0.0.1:{selected_port}/{manifest['release_tag']}"
        manifest["asset_url"] = f"{base}/{manifest['asset_name']}"
        manifest["checksum_url"] = f"{base}/{manifest['checksum_asset_name']}"
        path = self.skill / "runtime-manifest.json"
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        return path

    def run_bootstrap(
        self,
        cache: Path,
        *,
        manifest: Path | None = None,
        legacy_bundle: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = [
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            str(self.skill / "scripts" / "ensure-runtime.ps1"), "-Json",
            "-ManifestPath", str(manifest or self.skill / "runtime-manifest.json"),
            "-CacheRoot", str(cache),
            "-LegacyBundlePath", str(legacy_bundle or self.temp / "missing legacy"),
            "-AllowInsecureTestUrls",
        ]
        env = dict(os.environ)
        env["LOCALAPPDATA"] = str(self.temp / "local app data")
        return subprocess.run(command, text=True, encoding="utf-8", errors="replace", capture_output=True, env=env, timeout=180)

    def payload(self, result: subprocess.CompletedProcess[str]) -> dict[str, object]:
        self.assertTrue(result.stdout.strip(), result.stderr)
        return json.loads(result.stdout.strip().splitlines()[-1])

    def test_release_archive_contains_runtime_only(self) -> None:
        with zipfile.ZipFile(self.asset) as archive:
            names = {name.replace("\\", "/").rstrip("/") for name in archive.namelist() if name.rstrip("/")}
            metadata = json.loads(archive.read("mo2-runtime/runtime.json").decode("utf-8"))
        self.assertEqual({"mo2-runtime"}, {name.split("/", 1)[0] for name in names})
        self.assertIn("mo2-runtime/runtime.json", names)
        self.assertIn("mo2-runtime/bin/mo2-tool.exe", names)
        self.assertTrue(any(name.startswith("mo2-runtime/bin/_internal/") for name in names))
        self.assertIn("mo2-runtime/LICENSE", names)
        self.assertIn("mo2-runtime/THIRD_PARTY_NOTICES.md", names)
        self.assertTrue(any(name.startswith("mo2-runtime/third_party/") for name in names))
        self.assertNotIn("mo2-runtime/SKILL.md", names)
        self.assertNotIn("mo2-runtime/scripts/ensure-runtime.ps1", names)
        self.assertFalse(any(name.startswith("mo2-runtime/references/") for name in names))
        self.assertEqual(1, metadata["schema_version"])
        self.assertEqual(self.base_manifest["tool_version"], metadata["tool_version"])
        self.assertEqual("win-x64", metadata["platform"])

    def test_complete_bundle_is_ready_without_network(self) -> None:
        script = BUNDLE / "scripts" / "ensure-runtime.ps1"
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Json"],
            text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=60,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        payload = self.payload(result)
        self.assertEqual("bundled", payload["cache_source"])
        self.assertFalse(payload["downloaded"])

    def test_legacy_complete_bundle_without_runtime_metadata_is_accepted(self) -> None:
        legacy = self.temp / "legacy bundle"
        shutil.copytree(BUNDLE, legacy)
        (legacy / "runtime.json").unlink()
        result = self.run_bootstrap(self.temp / "legacy cache", legacy_bundle=legacy)
        self.assertEqual(0, result.returncode, result.stderr)
        payload = self.payload(result)
        self.assertEqual("legacy", payload["cache_source"])
        self.assertFalse(payload["downloaded"])

    def test_hash_mismatch_and_http_failure_are_classified(self) -> None:
        checksum = self.release_root / self.base_manifest["checksum_asset_name"]
        checksum.write_text("0" * 64 + f"  {self.base_manifest['asset_name']}\n", encoding="ascii")
        bad_hash = self.run_bootstrap(self.temp / "hash cache")
        self.assertEqual(3, bad_hash.returncode, bad_hash.stderr)
        self.assertEqual("error", self.payload(bad_hash)["status"])

        shutil.copy2(self.checksum, checksum)
        unused_port = free_port()
        failed_manifest = self.write_manifest(self.base_manifest, port=unused_port)
        http_failure = self.run_bootstrap(self.temp / "http cache", manifest=failed_manifest)
        self.assertEqual(4, http_failure.returncode, http_failure.stderr)

    def test_cold_warm_and_concurrent_cache(self) -> None:
        self.write_manifest(self.base_manifest)
        cache = self.temp / "cold cache"
        cold = self.run_bootstrap(cache)
        self.assertEqual(0, cold.returncode, cold.stderr + cold.stdout)
        cold_payload = self.payload(cold)
        self.assertTrue(cold_payload["downloaded"])
        self.assertEqual("downloaded", cold_payload["cache_source"])
        cold_version_root = cache / self.base_manifest["tool_version"]
        self.assertTrue((cold_version_root / "mo2-runtime" / "runtime.json").is_file())
        self.assertEqual([], list(cold_version_root.glob(".stage-*")))

        concurrent_cache = self.temp / "concurrent cache"
        stale = concurrent_cache / self.base_manifest["tool_version"] / ".stage-interrupted"
        stale.mkdir(parents=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.run_bootstrap(concurrent_cache), range(2)))
        for result in results:
            self.assertEqual(0, result.returncode, result.stderr)
        payloads = [self.payload(result) for result in results]
        self.assertEqual(1, sum(bool(item["downloaded"]) for item in payloads))
        self.assertFalse(stale.exists())
        concurrent_version_root = concurrent_cache / self.base_manifest["tool_version"]
        self.assertTrue((concurrent_version_root / "mo2-runtime" / "runtime.json").is_file())
        self.assertEqual([], list(concurrent_version_root.glob(".stage-*")))

        self.httpd.shutdown()
        self.httpd.server_close()
        self.httpd = None
        unreachable = self.write_manifest(self.base_manifest, port=free_port())
        warm = self.run_bootstrap(cache, manifest=unreachable)
        self.assertEqual(0, warm.returncode, warm.stderr)
        self.assertEqual("versioned", self.payload(warm)["cache_source"])

    def test_exact_runtime_version_is_enforced(self) -> None:
        version = "0.9.1"
        asset_name = f"mo2-runtime-v{version}-win-x64.zip"
        checksum_name = asset_name + ".sha256"
        shutil.copy2(self.asset, self.release_root / asset_name)
        (self.release_root / checksum_name).write_text(
            f"{sha256(self.release_root / asset_name)}  {asset_name}\n", encoding="ascii"
        )
        manifest = dict(self.base_manifest)
        manifest.update({
            "toolkit_version": version,
            "tool_version": version,
            "release_tag": f"v{version}",
            "asset_name": asset_name,
            "checksum_asset_name": checksum_name,
        })
        target_release = self.server_root / manifest["release_tag"]
        target_release.mkdir()
        shutil.copy2(self.release_root / asset_name, target_release / asset_name)
        shutil.copy2(self.release_root / checksum_name, target_release / checksum_name)
        manifest_path = self.write_manifest(manifest)
        result = self.run_bootstrap(self.temp / "version cache", manifest=manifest_path)
        self.assertEqual(3, result.returncode, result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)

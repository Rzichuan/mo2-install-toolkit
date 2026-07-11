#!/usr/bin/env python3
"""
nexus-download.py — Download mod files from Nexus Mods to the MO2 downloads directory.

Usage:
  python nexus-download.py <mod_id> <file_id> [--output-dir <path>] [--name <name>]
  python nexus-download.py <mod_id> <file_id> --json                 # Machine-readable output
  python nexus-download.py check <mod_id> <file_id>                   # Check if already downloaded

Environment:
  Reads MO2_INSTANCE_PATH and NEXUS_API_KEY from <skill_dir>/.env.
  Copy .env.example to .env and fill in your key and paths.

Notes:
  - Nexus API does not provide direct download links for non-premium users.
    This script attempts to fetch the download URL via the V1 API. If that fails,
    it outputs the manual download URL for the user.
  - Downloaded files are placed in <MO2_INSTANCE_PATH>/downloads/ with the
    standard MO2 naming convention: <name>-<modid>-<fileid>.<ext>
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
import urllib.parse

# Fix encoding issues on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
ENV_FILE = os.path.join(SKILL_DIR, ".env")

GAME_DOMAIN = "skyrimspecialedition"
V1_BASE = f"https://api.nexusmods.com/v1/games/{GAME_DOMAIN}"

# ── helpers ──

def load_env():
    env = dict(os.environ)
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env.setdefault(k, v)
    for key in ['NEXUS_API_KEY', 'MO2_INSTANCE_PATH']:
        if not env.get(key):
            die(f"{key} is not configured; run mo2-tool setup/auth first")
    return env

def die(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)

ENV = load_env()
KEY = ENV["NEXUS_API_KEY"]
DOWNLOADS_DIR = os.path.join(ENV["MO2_INSTANCE_PATH"], "downloads")

def fetch(url, *, accept="application/json"):
    req = urllib.request.Request(url, headers={
        "apikey": KEY,
        "Accept": accept,
        "User-Agent": "MO2/2.5.2",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:500]
        die(f"HTTP {e.code} from {url}:\n{body}")

# ── download logic ──

def find_existing_file(mod_id, file_id=None):
    """Check if a file matching mod_id pattern already exists in downloads.
    If file_id is provided, tries exact -modid-fileid match first, then falls back to just modid."""
    if not os.path.isdir(DOWNLOADS_DIR):
        return None

    # Exact match: -modid-fileid. When a file ID is requested, never fall
    # back to another file from the same mod; that would mistake an old version
    # for the requested update.
    if file_id:
        pattern = f"-{mod_id}-{file_id}."
        for fname in os.listdir(DOWNLOADS_DIR):
            if pattern in fname:
                return os.path.join(DOWNLOADS_DIR, fname)
        return None

    # Fallback is only valid when the caller did not request a specific file ID.
    for fname in os.listdir(DOWNLOADS_DIR):
        if f"{mod_id}" in fname and not fname.endswith(".meta"):
            return os.path.join(DOWNLOADS_DIR, fname)

    return None

def build_filename(name, mod_id, file_id, ext):
    """Build MO2-standard download filename: <name>-<modid>-<fileid>.<ext>"""
    safe_name = re.sub(r'[<>:"/\\|?*]', '', name).strip()
    return f"{safe_name}-{mod_id}-{file_id}.{ext}"

def download_via_curl(url, dest_path):
    """Download a signed Nexus CDN URL atomically. Returns (success, reason)."""
    partial_path = dest_path + ".part"
    try:
        # Encode spaces/non-ASCII characters in the CDN path while preserving the
        # signed query string exactly as Nexus returned it.
        parts = urllib.parse.urlsplit(url)
        encoded_url = urllib.parse.urlunsplit((
            parts.scheme,
            parts.netloc,
            urllib.parse.quote(urllib.parse.unquote(parts.path), safe="/%"),
            parts.query,
            parts.fragment,
        ))
        req = urllib.request.Request(encoded_url, headers={"User-Agent": "MO2/2.5.2"})
        with urllib.request.urlopen(req, timeout=600) as resp, open(partial_path, "wb") as out:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
        if not os.path.exists(partial_path) or os.path.getsize(partial_path) < 1024:
            raise RuntimeError("downloaded file is missing or suspiciously small")
        os.replace(partial_path, dest_path)
        return True, "ok"
    except Exception as exc:
        try:
            if os.path.exists(partial_path):
                os.remove(partial_path)
        except OSError:
            pass
        return False, f"CDN download failed: {exc}"

def try_api_download(mod_id, file_id, dest_path):
    """
    Attempt to get a download link via the V1 API.
    For premium users this returns a direct URL; for free users it may return
    a redirect to the manual download page.
    """
    # V1 download endpoint — may require premium
    try:
        info = fetch(f"{V1_BASE}/mods/{mod_id}/files/{file_id}/download_link.json")
        # Nexus returns a list of CDN mirrors for premium accounts.
        # Older responses/tools may expose a single object, so support both shapes.
        if isinstance(info, list):
            info = next((item for item in info if isinstance(item, dict)), {})
        if not isinstance(info, dict):
            return False, f"unexpected download-link response: {type(info).__name__}"
        # Check if we got a usable URL
        url = info.get("url") or info.get("URI") or ""
        if url and not url.startswith("https://www.nexusmods.com/"):
            # Got a CDN URL, try downloading
            downloaded, reason = download_via_curl(url, dest_path)
            if downloaded:
                return True, "api_direct"
            return False, reason
        # No direct CDN URL was returned.
        return False, "premium_required" if not url else "non_cdn_redirect"
    except Exception as e:
        return False, str(e)

def manual_download_url(mod_id, file_id):
    """Generate the manual download page URL."""
    return f"https://www.nexusmods.com/{GAME_DOMAIN}/mods/{mod_id}?tab=files&file_id={file_id}"

def verify_archive(path):
    """Basic check that the file exists, is non-empty, and looks like an archive."""
    if not os.path.exists(path):
        return False, "file not found"
    size = os.path.getsize(path)
    if size == 0:
        return False, "file is empty"
    if size < 1024:
        return False, f"suspicious size: {size} bytes"
    # Check magic bytes for common archive types
    with open(path, "rb") as f:
        magic = f.read(16)
    if magic[:2] == b"PK":
        return True, "zip"
    if magic[:2] == b"7z":
        return True, "7z"
    if magic[:3] == b"Rar":
        return True, "rar"
    if magic[:2] == b"\x1f\x8b":
        return True, "gz"
    # Unknown but large enough — accept
    return True, "unknown"

# ── commands ──

def cmd_download(mod_id, file_id, output_dir, name=None, json_out=False):
    output_dir = output_dir or DOWNLOADS_DIR
    os.makedirs(output_dir, exist_ok=True)

    # Get file info from v1 api
    files_data = fetch(f"{V1_BASE}/mods/{mod_id}/files.json")
    target = None
    all_files = files_data.get("files", [])
    for f in all_files:
        if str(f.get("file_id")) == str(file_id) or str(f.get("id", [None])[0]) == str(file_id):
            target = f
            break

    if not target:
        die(f"File ID {file_id} not found in mod {mod_id}")

    file_name = target.get("file_name", "unknown")
    mod_name = name or file_name.rsplit("-", 2)[0]  # Heuristic: strip trailing -modid-fileid
    ext = file_name.rsplit(".", 1)[-1] if "." in file_name else "7z"

    dest_name = build_filename(mod_name, mod_id, file_id, ext)
    dest_path = os.path.join(output_dir, dest_name)

    # Check if already downloaded
    existing = find_existing_file(mod_id, file_id)
    if existing:
        if json_out:
            print(json.dumps({"status": "already_downloaded", "path": existing, "size": os.path.getsize(existing)}))
        else:
            print(f"Already downloaded: {existing}")
        return

    # Try API download
    if json_out:
        print(json.dumps({"status": "attempting", "method": "api", "dest": dest_path}))
    else:
        print(f"Downloading: {file_name}")
        print(f"  Dest: {dest_path}")

    success, method = try_api_download(mod_id, file_id, dest_path)

    if success:
        size_mb = os.path.getsize(dest_path) / (1024 * 1024)
        if json_out:
            print(json.dumps({"status": "downloaded", "path": dest_path, "size_bytes": os.path.getsize(dest_path), "method": method}))
        else:
            print(f"  Downloaded ({size_mb:.1f} MB)")
    else:
        manual_url = manual_download_url(mod_id, file_id)
        if json_out:
            print(json.dumps({"status": "manual_required", "reason": method, "url": manual_url, "suggested_dest": dest_path, "recommended_command": f"mo2-tool nexus request {mod_id} {file_id} --json"}))
        else:
            print(f"  API download not available ({method}).")
            print(f"  Manual download URL: {manual_url}")
            print(f"  Save as: {dest_name}")
            print(f"  Assisted flow: mo2-tool nexus request {mod_id} {file_id} --json")

def cmd_check(mod_id, file_id):
    existing = find_existing_file(mod_id, file_id)
    if existing:
        size_mb = os.path.getsize(existing) / (1024 * 1024)
        ok, ftype = verify_archive(existing)
        print(f"FOUND: {os.path.basename(existing)} ({size_mb:.1f} MB, {ftype})")
        sys.exit(0)
    else:
        print(f"NOT FOUND: No file matching mod {mod_id} file {file_id}")
        print(f"  Manual: {manual_download_url(mod_id, file_id)}")
        sys.exit(1)

# ── main ──

def main():
    parser = argparse.ArgumentParser(description="Download Nexus Mods files for MO2")
    sub = parser.add_subparsers(dest="cmd")

    dl = sub.add_parser("download", help="Download a mod file")
    dl.add_argument("mod_id")
    dl.add_argument("file_id")
    dl.add_argument("--output-dir", help="Override downloads directory")
    dl.add_argument("--name", help="Override mod name in filename")
    dl.add_argument("--json", action="store_true", help="Machine-readable output")

    ck = sub.add_parser("check", help="Check if already downloaded")
    ck.add_argument("mod_id")
    ck.add_argument("file_id")

    args = parser.parse_args()

    if args.cmd == "download":
        cmd_download(args.mod_id, args.file_id, args.output_dir, getattr(args, "name", None), getattr(args, "json", False))
    elif args.cmd == "check":
        cmd_check(args.mod_id, args.file_id)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
nexus-mod-info.py — Query Nexus Mods API for a mod's metadata, files, dependencies, and archive structure.

Usage:
  python nexus-mod-info.py info    <mod_id>                     # Basic mod metadata
  python nexus-mod-info.py files   <mod_id>                     # List mod files and versions
  python nexus-mod-info.py deps    <mod_id>                     # Structured dependencies
  python nexus-mod-info.py preview <mod_id>                     # Archive directory tree
  python nexus-mod-info.py full    <mod_id>                     # All of the above
  python nexus-mod-info.py full    <mod_id> --json              # All, output as JSON

Environment:
  Reads NEXUS_API_KEY from .env in the script's parent directory.
  Copy .env.example to .env and fill in your key.
"""

import argparse
import json
import os
import re
import sys
import urllib.request
import urllib.error

# Fix encoding issues on Windows: ensure stdout uses utf-8
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
ENV_FILE = os.path.join(SKILL_DIR, ".env")

GAME_DOMAIN = "skyrimspecialedition"
V1_BASE = f"https://api.nexusmods.com/v1/games/{GAME_DOMAIN}"
V3_BASE = "https://api.nexusmods.com/v3"

# ── helpers ──────────────────────────────────────────────────────────────────

def load_api_key():
    if os.environ.get("NEXUS_API_KEY"):
        return os.environ["NEXUS_API_KEY"]
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if line.startswith("NEXUS_API_KEY="):
                    return line.split("=", 1)[1]
    die("ERROR: Nexus API key is not configured; run mo2-tool auth set")

def die(msg):
    print(msg, file=sys.stderr)
    sys.exit(1)

KEY = load_api_key()

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

# ── API wrappers ─────────────────────────────────────────────────────────────

def v1_mod(mod_id):
    """Fetch basic V1 mod metadata."""
    return fetch(f"{V1_BASE}/mods/{mod_id}.json")

def v3_mod(game_scoped_id):
    """Fetch V3 mod (gives us the composite id)."""
    return fetch(f"{V3_BASE}/games/{GAME_DOMAIN}/mods/{game_scoped_id}")

def v3_files(v3_mod_id):
    """Fetch V3 mod files list."""
    return fetch(f"{V3_BASE}/mods/{v3_mod_id}/files")

def v3_versions(mod_file_id):
    """Fetch versions for a mod file."""
    return fetch(f"{V3_BASE}/mod-files/{mod_file_id}/versions")

def v3_deps_materialized(version_id):
    """Fetch materialized dependencies for a mod file version."""
    return fetch(f"{V3_BASE}/mod-file-versions/{version_id}/dependencies/materialized")

def v1_preview(preview_url):
    """Fetch archive directory tree from content_preview_link."""
    return fetch(preview_url)

# ── presentation helpers ─────────────────────────────────────────────────────

def print_mod_basic(v1):
    print(f"Name:        {v1['name']}")
    print(f"Version:     {v1['version']}")
    print(f"Author:      {v1['author']}")
    print(f"Summary:     {v1['summary']}")
    print(f"Nexus ID:    {v1['mod_id']}")
    print(f"Category ID: {v1['category_id']}")
    print(f"Endorsements: {v1['endorsement_count']}")
    print(f"Downloads:   {v1['mod_downloads']}")
    print(f"Adult:       {v1['contains_adult_content']}")
    if v1.get("picture_url"):
        print(f"Thumbnail:   {v1['picture_url']}")

def list_files(v1):
    """V1 files endpoint gives us file list, versions, and content_preview_link directly."""
    fid = v1["mod_id"]
    files_data = fetch(f"{V1_BASE}/mods/{fid}/files.json")
    files = files_data.get("files", [])
    if not files:
        print("  (no files)")
        return

    categories = {"1": "MAIN", "2": "UPDATE", "3": "OPTIONAL", "4": "OLD_VERSION", "5": "MISC"}
    for f in sorted(files, key=lambda x: (x.get("category_id", 99), x.get("file_id", 0))):
        cat = categories.get(str(f.get("category_id", "")), "UNKNOWN")
        primary = " [PRIMARY]" if f.get("is_primary") else ""
        size_kb = f.get("size_kb", 0)
        print(f"  [{cat}{primary}] {f['file_name']}")
        print(f"    file_id={f['file_id']}  version={f.get('version','?')}  size={size_kb}KB")
        if f.get("content_preview_link"):
            print(f"    preview: {f['content_preview_link']}")
        desc = f.get("description", "")
        if desc and desc.strip():
            plain = re.sub(r"<[^>]+>", "", desc).strip()
            if plain:
                print(f"    desc: {plain[:120]}")

def print_deps(mod_id, v1):
    """Fetch structured dependencies via V3 chain, fall back to BBCode parse."""
    print("=== REQUIREMENTS ===")
    try:
        v3m = v3_mod(mod_id)
        v3_id = v3m["data"]["id"]
    except Exception:
        print("  (V3 mod lookup failed, parsing description)")
        print_bbcode_reqs(v1.get("description", ""))
        return

    try:
        fdata = v3_files(v3_id)
    except Exception:
        print("  (V3 files lookup failed)")
        print_bbcode_reqs(v1.get("description", ""))
        return

    for mf in fdata["data"]["mod_files"]:
        if not mf.get("is_active"):
            continue
        try:
            vdata = v3_versions(mf["id"])
        except Exception:
            continue

        for v in vdata["data"]["versions"]:
            if v["category"] not in ("main", "optional"):
                continue
            try:
                deps = v3_deps_materialized(v["id"])
            except Exception:
                continue

            dd = deps.get("dependencies", [])
            if not dd:
                continue

            for dep in dd:
                parts = []
                for cand in dep["candidate_mod_files"]:
                    cvs = [cv["version"] for cv in cand["candidate_versions"]]
                    parts.append(f"{cand['mod']['name']} [Nexus:{cand['mod']['game_scoped_id']}] (v{', v'.join(cvs)})")
                connector = "  OR  " if len(parts) > 1 else ""
                print(f"  {'  OR  '.join(parts)}")

            return  # printed deps from first main version — done

    # Fallback: parse BBCode
    print("  (no structured deps found, parsing description)")
    print_bbcode_reqs(v1.get("description", ""))

def print_bbcode_reqs(desc):
    import re
    if not desc:
        print("  (no description available)")
        return
    # Strip BBCode to plain text
    plain = desc
    plain = re.sub(r"<[^>]+>", "", plain)
    plain = re.sub(r"\[/?center\]", "", plain, flags=re.I)
    plain = re.sub(r"\[/?size[^\]]*\]", "", plain, flags=re.I)
    plain = re.sub(r"\[/?[bius]\]", "", plain, flags=re.I)
    plain = re.sub(r"\[line\]", "---", plain, flags=re.I)
    plain = re.sub(r"\[url=[^\]]*\]", "", plain, flags=re.I)
    plain = re.sub(r"\[/url\]", "", plain, flags=re.I)
    plain = re.sub(r"\[spoiler\].*?\[/spoiler\]", "", plain, flags=re.I | re.DOTALL)
    plain = re.sub(r"\[img[^\]]*\]", "", plain)
    plain = re.sub(r"\s*<br\s*/?>\s*", "\n", plain)
    plain = re.sub(r"\n{3,}", "\n", plain)

    m = re.search(r"REQUIREMENTS?\s*\n(.+?)(?:COMPATIBILITY|INSTALLATION|CREDITS|$)", plain, re.I | re.DOTALL)
    if m:
        for line in m.group(1).strip().split("\n"):
            line = line.strip()
            if line and not re.match(r"^---+$", line):
                print(f"  {line}")
    else:
        print("  (no REQUIREMENTS section found in description)")

def print_preview(v1):
    print("=== ARCHIVE LAYOUT ===")
    fid = v1["mod_id"]
    try:
        files_data = fetch(f"{V1_BASE}/mods/{fid}/files.json")
    except Exception:
        print("  (could not fetch files)")
        return

    # Find first main file with content_preview_link
    for f in files_data.get("files", []):
        preview_url = f.get("content_preview_link")
        if not preview_url:
            continue
        cat = f.get("category_name", "")
        print(f"  [{cat}] {f.get('file_name','?')}")

        try:
            tree = v1_preview(preview_url)
        except Exception:
            print("    (preview not available)")
            continue

        def walk(node, prefix):
            if node.get("type") == "file":
                sz = node.get("size", 0)
                kb = f"{sz/1024:.1f}KB" if sz else ""
                print(f"    {prefix}{node['name']}  {kb}")
            elif node.get("type") == "directory":
                name = node.get("name", "")
                new_prefix = f"{prefix}{name}/" if prefix else f"    {name}/"
                children = node.get("children", []) or []
                for child in children:
                    walk(child, new_prefix)

        children = tree.get("children", []) or []
        for child in children:
            walk(child, "")
        return

# ── main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Query Nexus Mods API for mod metadata", prog="nexus-mod-info")
    parser.add_argument("command", choices=["info", "files", "deps", "preview", "full"])
    parser.add_argument("mod_id", help="Nexus mod ID (e.g. 174642)")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON (full command only)")
    args = parser.parse_args()

    mod_id = args.mod_id
    v1 = v1_mod(mod_id)

    if args.command == "info":
        print_mod_basic(v1)

    elif args.command == "files":
        print(f"=== FILES for {v1['name']} ===")
        list_files(v1)

    elif args.command == "deps":
        print(f"=== DEPENDENCIES for {v1['name']} ===")
        print_deps(mod_id, v1)

    elif args.command == "preview":
        print_preview(v1)

    elif args.command == "full":
        if args.json:
            # Machine-readable: collect all data into one dict
            result = {"mod": v1}
            try:
                files_raw = fetch(f"{V1_BASE}/mods/{mod_id}/files.json")
                result["files"] = files_raw.get("files", [])
            except Exception:
                result["files"] = []

            # Dependencies via V3
            deps_result = []
            try:
                v3m = v3_mod(mod_id)
                v3_id = v3m["data"]["id"]
                fdata = v3_files(v3_id)
                for mf in fdata["data"]["mod_files"]:
                    if not mf.get("is_active"):
                        continue
                    vdata = v3_versions(mf["id"])
                    for v in vdata["data"]["versions"]:
                        if v["category"] not in ("main", "optional"):
                            continue
                        try:
                            raw = v3_deps_materialized(v["id"])
                            deps_result = raw.get("dependencies", [])
                            break
                        except Exception:
                            continue
                    if deps_result:
                        break
                result["dependencies"] = deps_result
            except Exception:
                result["dependencies"] = []

            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            # Human-readable: print everything
            print("=" * 60)
            print_mod_basic(v1)
            print()
            print(f"=== FILES for {v1['name']} ===")
            list_files(v1)
            print()
            print_deps(mod_id, v1)
            print()
            print_preview(v1)

if __name__ == "__main__":
    main()

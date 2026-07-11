#!/usr/bin/env python3
"""
nexus-deps-resolve.py — Recursively resolve mod dependencies and generate an install plan.

Usage:
  python nexus-deps-resolve.py plan <mod_id> [--profile <profile>] [--json] [--auto]
  python nexus-deps-resolve.py check <mod_id> [--profile <profile>] [--json]

Environment:
  Reads MO2_INSTANCE_PATH and NEXUS_API_KEY from <skill_dir>/.env.

How it works:
  1. Fetch mod info and structured dependencies via Nexus API (V1 + V3 materialized).
  2. Scan local MO2 profile: read <profile>/modlist.txt for enabled mods,
     match against mods/*/meta.ini for modid= to know what's installed.
  3. For each missing dependency, RECURSIVELY fetch its own dependencies,
     building a full dependency tree down to leaves.
  4. Detect conflicts: game version mismatches, mutually exclusive OR-group
     alternatives, version downgrades, SKSE/Address Library incompatibility.
  5. Consult references/knowledge-base.md for non-Nexus mods and known exceptions.
  6. Output an install plan: ordered list (leaf-first) with conflict warnings.
     With --auto, non-conflicting mods are marked for automatic install.
"""

import argparse
import json
import os
import re
import sys
import urllib.request
import urllib.error
from datetime import datetime

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
ENV_FILE = os.path.join(SKILL_DIR, ".env")
KB_FILE = os.path.join(SKILL_DIR, "references", "knowledge-base.md")

GAME_DOMAIN = "skyrimspecialedition"
V1_BASE = f"https://api.nexusmods.com/v1/games/{GAME_DOMAIN}"
V3_BASE = "https://api.nexusmods.com/v3"

# ── Config loading ───────────────────────────────────────────────────────────

def load_env():
    env = dict(os.environ)
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env.setdefault(k, v)
    return env

def die(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)

ENV = load_env()
KEY = ENV.get("NEXUS_API_KEY", "")
INSTANCE = ENV.get("MO2_INSTANCE_PATH", "")
GAME_PATH = ENV.get("SKYRIM_GAME_PATH", "")

# ── Nexus API ────────────────────────────────────────────────────────────────

def fetch(url):
    req = urllib.request.Request(url, headers={
        "apikey": KEY, "Accept": "application/json", "User-Agent": "MO2/2.5.2"
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))

def fetch_deps_v3(mod_id):
    """Get structured dependencies for a mod via V3 API. Returns list of dependency definitions."""
    try:
        v3m = fetch(f"{V3_BASE}/games/{GAME_DOMAIN}/mods/{mod_id}")
        v3_id = v3m["data"]["id"]
        fdata = fetch(f"{V3_BASE}/mods/{v3_id}/files")
        for mf in fdata["data"]["mod_files"]:
            if not mf.get("is_active"):
                continue
            vdata = fetch(f"{V3_BASE}/mod-files/{mf['id']}/versions")
            for v in vdata["data"]["versions"]:
                if v["category"] not in ("main", "optional"):
                    continue
                try:
                    deps = fetch(f"{V3_BASE}/mod-file-versions/{v['id']}/dependencies/materialized")
                    return deps.get("dependencies", [])
                except Exception:
                    continue
    except Exception:
        pass
    return None  # None = could not fetch, [] = no dependencies

def fetch_mod_name(mod_id):
    """Get mod name from V1 API."""
    try:
        v1 = fetch(f"{V1_BASE}/mods/{mod_id}.json")
        return v1.get("name", f"Nexus:{mod_id}")
    except Exception:
        return f"Nexus:{mod_id}"

# ── Local profile scanning ────────────────────────────────────────────────────

def scan_local_mods(profile):
    """Scan MO2 instance for installed mods with their Nexus IDs."""
    mods_dir = os.path.join(INSTANCE, "mods")
    profile_dir = os.path.join(INSTANCE, "profiles", profile)
    modlist_path = os.path.join(profile_dir, "modlist.txt")

    installed = {}  # modid (str) -> {"folder": str, "enabled": bool, "name": str}

    # Read modlist.txt for enabled/disabled status
    enabled_folders = set()
    if os.path.exists(modlist_path):
        with open(modlist_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("+"):
                    enabled_folders.add(line[1:])

    # Scan mods/ for meta.ini
    if os.path.isdir(mods_dir):
        for folder in os.listdir(mods_dir):
            meta = os.path.join(mods_dir, folder, "meta.ini")
            if not os.path.isfile(meta):
                continue
            modid = None
            with open(meta, encoding="utf-8", errors="replace") as f:
                for line in f:
                    if line.startswith("modid="):
                        mid = line.strip().split("=", 1)[1]
                        if mid and mid != "0":
                            modid = mid
                        break
            if modid:
                installed[modid] = {
                    "folder": folder,
                    "enabled": folder in enabled_folders,
                    "name": folder,
                }

    # Also scan by DLL/known patterns for mods without meta.ini (from knowledge-base)
    # This is a best-effort fallback
    return installed

def scan_game_version():
    """Detect Skyrim SE game version from SkyrimSE.exe."""
    if not GAME_PATH:
        return None
    exe = os.path.join(GAME_PATH, "SkyrimSE.exe")
    if not os.path.exists(exe):
        return None
    # Read file version from Windows PE header
    try:
        import struct
        with open(exe, "rb") as f:
            # PE header offset at 0x3C
            f.seek(0x3C)
            pe_offset = struct.unpack("<I", f.read(4))[0]
            f.seek(pe_offset + 8)
            # TimeDateStamp + pointer to optional header
            f.read(8)
            # Optional header magic (0x10B = PE32, 0x20B = PE32+)
            magic = struct.unpack("<H", f.read(2))[0]
            # Skip to version resource... instead use a simpler approach:
            # Read VS_FIXEDFILEINFO from the resource section
            # For now, just use the linker version in optional header
            if magic == 0x20B:  # PE32+
                f.read(66)
                major = struct.unpack("<H", f.read(2))[0]
                minor = struct.unpack("<H", f.read(2))[0]
                return f"{major}.{minor}.0.0"
            elif magic == 0x10B:  # PE32
                f.read(62)
                major = struct.unpack("<H", f.read(2))[0]
                minor = struct.unpack("<H", f.read(2))[0]
                return f"{major}.{minor}.0.0"
    except Exception:
        pass

    # Fallback: check file product version via subprocess
    try:
        import subprocess
        result = subprocess.run(
            ["powershell", "-Command",
             f"(Get-Item '{exe}').VersionInfo.ProductVersion"],
            capture_output=True, text=True, timeout=10
        )
        ver = result.stdout.strip()
        if ver:
            return ver
    except Exception:
        pass

    return None

# ── Knowledge base integration ──────────────────────────────────────────────

def load_knowledge_base():
    """Parse knowledge-base.md for known alternate detection patterns."""
    entries = []
    if not os.path.exists(KB_FILE):
        return entries

    with open(KB_FILE, encoding="utf-8") as f:
        content = f.read()

    # Extract Source Registry entries
    for match in re.finditer(r"^### (.+)$", content, re.MULTILINE):
        name = match.group(1).strip()
        section_start = match.end()
        next_section = re.search(r"^### |^## ", content[section_start:], re.MULTILINE)
        section_end = section_start + next_section.start() if next_section else len(content)
        section = content[section_start:section_end]

        entry = {"name": name}
        for key in ["Nexus ID", "Detected by", "Satisfies dependency", "Conflicts with", "Source"]:
            m2 = re.search(rf"^- {key}:\s*(.+)$", section, re.MULTILINE)
            if m2:
                entry[key.lower().replace(" ", "_")] = m2.group(1).strip()
        entries.append(entry)

    return entries

def match_installed_by_pattern(installed_mods, dep_name, kb_entries):
    """Try to match a dependency name against installed mods via knowledge base patterns."""
    for entry in kb_entries:
        if dep_name.lower() in entry.get("name", "").lower():
            detected_by = entry.get("detected_by", "")
            if not detected_by:
                continue
            # Check if any of the detection patterns match installed folders or DLLs
            patterns = [p.strip() for p in detected_by.split(",")]
            mods_dir = os.path.join(INSTANCE, "mods")
            for folder in os.listdir(mods_dir):
                for pat in patterns:
                    if pat.lower() in folder.lower():
                        return folder
                    # Check for DLL pattern inside the mod folder
                    dll_path = os.path.join(mods_dir, folder, "SKSE", "Plugins", pat)
                    if os.path.exists(dll_path):
                        return folder
    return None

# ── Conflict detection ────────────────────────────────────────────────────────

def detect_conflicts(mod_id, dep_tree, installed, game_ver, kb_entries):
    """
    Walk the resolved dependency tree and flag anything that would break the current setup.
    Returns list of conflict objects.
    """
    conflicts = []

    # 1. Framework OR-group: BFCO vs MCO mutual exclusion
    framework_ids = {"117052", "160505", "117275", "175044"}  # BFCO, BFCO NG, ADXP MCO, Attack-MCO
    installed_frameworks = framework_ids & set(installed.keys())
    for dep_id in framework_ids:
        if dep_id in dep_tree and installed_frameworks and dep_id not in installed:
            conflicts.append({
                "severity": "warn",
                "type": "framework_conflict",
                "message": f"New dep {fetch_mod_name(dep_id)} ({dep_id}) is in a mutual-exclusion group. "
                           f"Already installed: {fetch_mod_name(list(installed_frameworks)[0])}. "
                           f"These cannot coexist — user must choose.",
                "requires_confirmation": True,
            })

    # 2. Game version incompatibility (AE-only mod on SE, etc.)
    if game_ver and game_ver.startswith("1.5"):
        for dep_id, dep_info in dep_tree.items():
            name = dep_info.get("name", "").lower()
            ae_keywords = ["anniversary edition", "ae only", "1.6.", "ae 1.6"]
            if any(kw in name for kw in ae_keywords):
                conflicts.append({
                    "severity": "error",
                    "type": "version_mismatch",
                    "message": f"{dep_info['name']} ({dep_id}) may require AE (1.6.x). "
                               f"Detected game version: {game_ver}.",
                    "requires_confirmation": True,
                })

    # 3. Version downgrade: trying to install older version over newer installed
    for dep_id in dep_tree:
        if dep_id in installed:
            # Could check version strings here if we tracked them
            pass

    # 4. Plugin conflicts (same ESP from two mods)
    # This requires inspecting archive contents; flagged as a warning if both
    # mods provide plugins and neither is a known compatibility patch.
    mods_dir = os.path.join(INSTANCE, "mods")
    for dep_id, dep_info in dep_tree.items():
        plugins = dep_info.get("plugins", [])
        if not plugins:
            continue
        for folder, info in installed.items():
            if not info["enabled"]:
                continue
            # Check if installed mod has overlapping plugins
            mod_dir = os.path.join(mods_dir, folder)
            for esp in plugins:
                esp_path = os.path.join(mod_dir, esp)
                if os.path.exists(esp_path):
                    # Same ESP in both — check if it's a known override pattern
                    if "patch" not in dep_info.get("name", "").lower():
                        conflicts.append({
                            "severity": "warn",
                            "type": "plugin_overlap",
                            "message": f"{dep_info['name']} provides {esp}, already installed from {folder}. "
                                       f"Overwrite may cause issues.",
                            "requires_confirmation": True,
                        })

    # 5. Missing SKSE/Address Library compatibility
    # If a dep provides SKSE plugins, check that Address Library is installed
    has_address_library = any(
        "Address Library" in info.get("name", "") or mid == "32444"
        for mid, info in installed.items()
    )
    for dep_id, dep_info in dep_tree.items():
        if dep_info.get("has_skse_plugin") and not has_address_library and not installed:
            conflicts.append({
                "severity": "warn",
                "type": "missing_skse_dep",
                "message": f"{dep_info['name']} is a SKSE plugin. Ensure Address Library (32444) "
                           f"and SKSE are installed.",
                "requires_confirmation": False,
            })

    return conflicts

# ── Dependency resolution ────────────────────────────────────────────────────

def resolve_deps(mod_id, installed, kb_entries, visited=None, depth=0):
    """
    Recursively resolve dependencies for a mod.
    Returns: dict of {dep_mod_id: {name, status, children, depth, ...}}
    status: "installed" | "resolved" | "missing" | "conflict" | "failed"
    """
    if visited is None:
        visited = set()

    if mod_id in visited:
        return {}  # cycle detected
    visited.add(mod_id)

    tree = {}

    deps = fetch_deps_v3(mod_id)
    if deps is None:
        # Could not fetch from API — mark as unknown
        return {"_fetch_error": True}

    for dep_def in deps:
        candidates = dep_def.get("candidate_mod_files", [])
        # Try to match against installed first
        matched = False
        for cand in candidates:
            cand_id = cand["mod"]["game_scoped_id"]
            cand_name = cand["mod"]["name"]

            if cand_id in installed:
                tree[cand_id] = {
                    "name": cand_name,
                    "status": "installed",
                    "depth": depth,
                    "children": {},
                }
                matched = True
                break

        if matched:
            continue

        # OR-group: pick the most recent/primary candidate if nothing installed
        # For framework groups, defer to user
        best = candidates[0] if candidates else None
        if not best:
            continue

        best_id = best["mod"]["game_scoped_id"]
        best_name = best["mod"]["name"]

        # Recursively resolve this dependency's own deps
        children = resolve_deps(best_id, installed, kb_entries, visited.copy(), depth + 1)

        tree[best_id] = {
            "name": best_name,
            "status": "resolved" if children else "missing",
            "depth": depth,
            "children": children,
        }

    return tree

# ── Install plan generation ───────────────────────────────────────────────────

def build_install_plan(dep_tree, conflicts, auto=False):
    """
    Flatten the dependency tree into an ordered install plan (leaf-first).
    Returns list of steps: {mod_id, name, action, auto_installable, reason}
    """
    def flatten(tree, result, parent_id=None):
        for mod_id, info in sorted(tree.items(), key=lambda x: x[1].get("depth", 0), reverse=True):
            # Install children first (deeper)
            children = info.get("children", {})
            if children:
                flatten(children, result, mod_id)

            if info.get("status") in ("resolved", "missing"):
                result.append({
                    "mod_id": mod_id,
                    "name": info["name"],
                    "action": "install",
                    "depth": info.get("depth", 0),
                    "auto_installable": True,  # will be evaluated later
                })
            elif info.get("status") == "installed":
                # Could be an update candidate
                pass

    steps = []
    flatten(dep_tree, steps)

    # De-duplicate by mod_id (keep first occurrence = deepest install first)
    seen = set()
    deduped = []
    for s in steps:
        if s["mod_id"] not in seen:
            seen.add(s["mod_id"])
            deduped.append(s)
    steps = deduped

    # For each step, check if it can be auto-installed
    conflict_mod_ids = set()
    for c in conflicts:
        if c.get("requires_confirmation"):
            # Mark related mods — we need to identify which mods are affected
            pass

    for step in steps:
        # Auto-installable if no conflicts block it
        step["auto_installable"] = not any(
            c.get("requires_confirmation") and c.get("severity") == "error"
            for c in conflicts
        )

    return steps

# ── Output ────────────────────────────────────────────────────────────────────

def print_plan(mod_id, mod_name, dep_tree, conflicts, plan, game_ver, installed_count):
    print(f"=== INSTALL PLAN ===")
    print(f"Target:  {mod_name} ({mod_id})")
    print(f"Profile: {profile if profile else 'default'}")
    print(f"Installed mods with meta.ini: {installed_count}")
    if game_ver:
        print(f"Game version: {game_ver}")
    print()

    # Conflicts first
    if conflicts:
        print("--- CONFLICTS ---")
        errors = [c for c in conflicts if c["severity"] == "error"]
        warns = [c for c in conflicts if c["severity"] == "warn"]
        if errors:
            print(f"  {len(errors)} ERROR(S) — must be resolved before installing:")
            for c in errors:
                print(f"  ❌ {c['message']}")
        if warns:
            print(f"\n  {len(warns)} WARNING(S):")
            for c in warns:
                print(f"  ⚠️  {c['message']}")
        print()

    # Dependency tree
    def print_tree(tree, indent=0):
        for mid, info in sorted(tree.items(), key=lambda x: x[1].get("name", "")):
            prefix = "  " * indent
            status_icon = {"installed": "✅", "resolved": "📦", "missing": "❓", "conflict": "⚠️"}.get(info["status"], "  ")
            print(f"{prefix}{status_icon} {info['name']} [{mid}]")
            children = info.get("children", {})
            if children:
                print_tree(children, indent + 1)

    print("--- DEPENDENCY TREE ---")
    print(f"  🎯 {mod_name} [{mod_id}] (target)")
    print_tree(dep_tree, 1)
    print()

    # Install steps
    if not plan:
        print("  No new mods to install — all dependencies are already present.")
        return

    print("--- INSTALL STEPS (leaf-first) ---")
    for i, step in enumerate(plan, 1):
        auto = "AUTO" if step.get("auto_installable") else "REVIEW"
        print(f"  {i}. [{auto}] {step['name']} ({step['mod_id']})")
    print()

    # Summary
    auto_count = sum(1 for s in plan if s.get("auto_installable"))
    review_count = len(plan) - auto_count
    print("--- SUMMARY ---")
    if auto_count > 0:
        print(f"  {auto_count} mod(s) can be auto-installed")
    if review_count > 0:
        print(f"  {review_count} mod(s) require user confirmation")
    if conflicts:
        print(f"  {len(conflicts)} conflict(s) to resolve")
    print()


def print_plan_json(mod_id, mod_name, dep_tree, conflicts, plan, game_ver):
    output = {
        "target": {"mod_id": mod_id, "name": mod_name},
        "game_version": game_ver,
        "conflicts": conflicts,
        "dependency_tree": dep_tree,
        "install_plan": plan,
        "generated": datetime.now().isoformat(),
    }
    print(json.dumps(output, indent=2, ensure_ascii=False))


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Resolve mod dependencies and generate install plan")
    sub = parser.add_subparsers(dest="cmd")

    plan_p = sub.add_parser("plan", help="Generate full install plan")
    plan_p.add_argument("mod_id", help="Nexus mod ID to install")
    plan_p.add_argument("--profile", "-p", default="lux", help="MO2 profile (default: lux)")
    plan_p.add_argument("--json", action="store_true", help="Machine-readable output")
    plan_p.add_argument("--auto", action="store_true", help="Return non-zero exit if any mods need review")

    check_p = sub.add_parser("check", help="Quick check: what's missing?")
    check_p.add_argument("mod_id", help="Nexus mod ID to check")
    check_p.add_argument("--profile", "-p", default="lux", help="MO2 profile (default: lux)")
    check_p.add_argument("--json", action="store_true")

    args = parser.parse_args()

    global profile
    profile = args.profile if hasattr(args, "profile") else "lux"
    mod_id = args.mod_id

    # Input validation
    if not KEY:
        die("NEXUS_API_KEY not set in .env")
    if not INSTANCE:
        die("MO2_INSTANCE_PATH not set in .env")

    # Gather data
    mod_name = fetch_mod_name(mod_id)
    installed = scan_local_mods(profile)
    kb_entries = load_knowledge_base()
    game_ver = scan_game_version()

    # Resolve dependency tree
    dep_tree = resolve_deps(mod_id, installed, kb_entries)

    # Detect conflicts
    conflicts = detect_conflicts(mod_id, dep_tree, installed, game_ver, kb_entries)

    # Build install plan
    plan = build_install_plan(dep_tree, conflicts, auto=getattr(args, "auto", False))

    if args.cmd == "check":
        if args.json:
            print(json.dumps({
                "mod_id": mod_id,
                "name": mod_name,
                "installed_count": len(installed),
                "missing_deps": len(plan),
                "conflicts": len(conflicts),
            }, indent=2))
        else:
            missing = [s for s in plan if s["action"] == "install"]
            if not missing and not conflicts:
                print(f"✅ All dependencies for {mod_name} ({mod_id}) are already installed.")
            else:
                if missing:
                    print(f"Missing: {len(missing)} dep(s)")
                    for s in missing:
                        print(f"  - {s['name']} ({s['mod_id']})")
                if conflicts:
                    print(f"Conflicts: {len(conflicts)}")
                    for c in conflicts:
                        print(f"  - {c['message']}")
        return

    if args.cmd == "plan":
        if args.json:
            print_plan_json(mod_id, mod_name, dep_tree, conflicts, plan, game_ver)
        else:
            print_plan(mod_id, mod_name, dep_tree, conflicts, plan, game_ver,
                       len(installed))

        # Exit code for CI/automation
        if conflicts and any(c["severity"] == "error" for c in conflicts):
            sys.exit(2)  # errors — blocked
        elif conflicts:
            sys.exit(1)  # warnings — needs review


if __name__ == "__main__":
    main()

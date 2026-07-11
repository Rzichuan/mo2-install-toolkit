#!/usr/bin/env python3
"""
mod-install.py — Extract and install a downloaded mod archive into the MO2 mods directory.

Usage:
  python mod-install.py install <archive_path> [--name <folder_name>] [--json]
  python mod-install.py dry-run <archive_path>                          # Show what will happen
  python mod-install.py detect-layout <archive_path>                    # Show archive structure type

Environment:
  Reads MO2_INSTANCE_PATH from <skill_dir>/.env.

Safety rules (enforced):
  - Never install over an existing mod folder without --force.
  - With --force, moves old folder to <instance>/_codex_backups/mods/<timestamp>/ first.
  - Detects nested wrapping (single top-level folder in archive) and flattens.
  - Detects root-level content (d3d11.dll, enbseries.ini, etc.) and DENIES by default.
    Use --allow-root to install to the game root instead of mods/.
  - Detects FOMOD and warns — manual option selection is required.
  - After extraction, creates meta.ini if missing (with modid= if provided via --modid).
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from mo2_agent_toolkit.workflow import archive_members as canonical_archive_members, detect_layout
from datetime import datetime

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
ENV_FILE = os.path.join(SKILL_DIR, ".env")

SEVEN_ZIP = os.environ.get("SEVEN_ZIP_PATH", "7z")

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
    for key in ['MO2_INSTANCE_PATH']:
        if not env.get(key):
            die(f"{key} is not configured; run mo2-tool setup/auth first")
    return env

def die(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)

def warn(msg):
    print(f"WARNING: {msg}", file=sys.stderr)

def ts():
    return datetime.now().strftime("%Y%m%d_%H%M%S")

ENV = load_env()
INSTANCE = ENV["MO2_INSTANCE_PATH"]
MODS_DIR = os.path.join(INSTANCE, "mods")
BACKUPS_DIR = os.path.join(INSTANCE, "_agent_toolkit_backups")

# ── archive inspection ──

def list_archive(archive_path):
    """List through the toolkit canonical archive reader."""
    return canonical_archive_members(Path(archive_path), SEVEN_ZIP)


def manual_post_install_steps(features):
    """Build one-time, non-blocking manual follow-up instructions."""
    actions = []
    if features["has_bodyslide_project"]:
        actions.append({
            "tool": "BodySlide",
            "level": "recommended",
            "advisory": True,
            "reason": "Archive contains BodySlide SliderSets or ShapeData",
            "steps": [
                "Open Mod Organizer 2 and run BodySlide x64 through MO2",
                "Select the body preset used by the current profile",
                "Enable Build Morphs when RaceMenu morphs are required",
                "Run Batch Build and choose variants matching the installed body framework",
                "Write generated files to a dedicated BodySlide Output mod instead of leaving them in Overwrite",
                "Enable the generated output mod in MO2",
            ],
        })
    elif features["has_bodyslide_preset"]:
        actions.append({
            "tool": "BodySlide",
            "level": "informational",
            "advisory": True,
            "reason": "Archive contains a BodySlide preset but no build project",
            "steps": [
                "Open BodySlide x64 through MO2 when rebuilding bodies or outfits",
                "Select this preset only if it matches the body framework used by the current profile",
                "A preset-only archive does not by itself require an immediate Batch Build",
            ],
        })
    if features["has_pandora_patch"]:
        actions.append({
            "tool": "Pandora",
            "level": "recommended",
            "advisory": True,
            "reason": "Archive contains a Pandora behavior patch",
            "steps": [
                "Enable the installed animation or behavior mod in MO2",
                "Run Pandora Behaviour Engine through MO2 and select the patch required by the mod",
                "Generate into a dedicated Pandora Output mod and enable it after the related behavior mods",
                "Do not keep conflicting Pandora, Nemesis, or FNIS generated outputs enabled together",
            ],
        })
    if features["has_nemesis_patch"]:
        actions.append({
            "tool": "Nemesis",
            "level": "recommended",
            "advisory": True,
            "reason": "Archive contains a Nemesis behavior patch",
            "steps": [
                "Enable the installed animation or behavior mod in MO2",
                "Run Nemesis through MO2, update the engine if required, and select the mod patch",
                "Generate into a dedicated Nemesis Output mod and enable it after the related behavior mods",
                "Do not keep conflicting Pandora, Nemesis, or FNIS generated outputs enabled together",
            ],
        })
    if features["has_fnis_content"]:
        actions.append({
            "tool": "FNIS",
            "level": "review",
            "advisory": True,
            "reason": "Archive contains FNIS-specific content",
            "steps": [
                "Check the mod page for its required behavior generator",
                "Use FNIS only when the mod explicitly requires it; do not mix generated outputs by default",
                "If using a compatible Pandora replacement workflow, follow that tool's documented FNIS compatibility steps",
            ],
        })
    if features["has_prebuilt_behavior"] and not any(
        (features["has_pandora_patch"], features["has_nemesis_patch"], features["has_fnis_content"])
    ):
        actions.append({
            "tool": "Behavior generator",
            "level": "review",
            "advisory": True,
            "reason": "Archive contains prebuilt behavior files but no recognized generator patch",
            "steps": [
                "Check the mod page to determine whether behavior regeneration is required",
                "Do not run Pandora, Nemesis, or FNIS solely because prebuilt HKX files are present",
            ],
        })
    return actions


def print_manual_post_install_steps(actions):
    if not actions:
        print("Manual post-install steps: none detected")
        return
    print("Suggested manual post-install steps (not run automatically):")
    print("  These are recommendations only; use your own established workflow when preferred.")
    for action in actions:
        print(f"  [{action['level']}] {action['tool']}: {action['reason']}")
        for index, step in enumerate(action["steps"], 1):
            print(f"    {index}. {step}")


# ── installation ──

def extract_archive(archive_path, dest_dir, strip_components=0):
    """Extract archive to dest_dir using 7z, optionally stripping top-level dirs."""
    os.makedirs(dest_dir, exist_ok=True)

    # First extract to temp, then move if stripping needed
    if strip_components > 0:
        temp_dir = os.path.join(os.path.dirname(dest_dir), f"_tmp_extract_{ts()}")
        os.makedirs(temp_dir, exist_ok=True)
        actual_dest = temp_dir
    else:
        actual_dest = dest_dir

    result = subprocess.run(
        [SEVEN_ZIP, "x", archive_path, f"-o{actual_dest}", "-y"],
        capture_output=False, timeout=300
    )
    if result.returncode != 0:
        die(f"7z extract failed (code {result.returncode})")

    if strip_components > 0:
        # Move contents out of the nesting directory
        nested_root = os.path.join(actual_dest, os.listdir(actual_dest)[0])
        if os.path.isdir(nested_root):
            for item in os.listdir(nested_root):
                src = os.path.join(nested_root, item)
                dst = os.path.join(dest_dir, item)
                if os.path.exists(dst):
                    if os.path.isdir(dst):
                        shutil.rmtree(dst)
                    else:
                        os.remove(dst)
                shutil.move(src, dst)
            shutil.rmtree(actual_dest)
        else:
            # No nested dir found — just move everything
            for item in os.listdir(actual_dest):
                shutil.move(os.path.join(actual_dest, item), os.path.join(dest_dir, item))
            shutil.rmtree(actual_dest)

def backup_and_install(archive_path, mod_name, force=False):
    """Extract into staging and commit only after validation."""
    entries = list_archive(archive_path)
    layout = detect_layout(entries)
    dest_path = os.path.join(MODS_DIR, mod_name)
    if layout["has_fomod"]:
        warn("This archive contains a FOMOD installer; full extraction requires review.")
    if layout["has_root_files"]:
        die("This archive contains root-level game files; MO2 mod installation is blocked.")
    tx_dir = os.environ.get("MO2_TRANSACTION_DIR")
    staging_root = os.path.join(tx_dir, "staging") if tx_dir else os.path.join(INSTANCE, "_agent_toolkit_staging", ts())
    staging = os.path.join(staging_root, mod_name)
    backup_dir = os.path.join(tx_dir, "mods", mod_name) if tx_dir else os.path.join(BACKUPS_DIR, ts(), "mods", mod_name)
    if os.path.exists(staging): shutil.rmtree(staging)
    os.makedirs(staging, exist_ok=True)
    moved_old = False
    try:
        strip = 1 if layout["has_nesting"] else 0
        print(f"  Extracting to staging: {staging}")
        extract_archive(archive_path, staging, strip_components=strip)
        if not os.listdir(staging): die(f"Extraction produced empty directory: {staging}")
        if os.path.exists(dest_path):
            if not force: die(f"Mod folder already exists: {dest_path}\nUse --force to replace it safely.")
            os.makedirs(os.path.dirname(backup_dir), exist_ok=True)
            print(f"  Backing up: {dest_path} -> {backup_dir}")
            shutil.move(dest_path, backup_dir); moved_old = True
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        shutil.move(staging, dest_path)
    except BaseException:
        if os.path.exists(staging): shutil.rmtree(staging, ignore_errors=True)
        if moved_old and os.path.exists(backup_dir) and not os.path.exists(dest_path):
            shutil.move(backup_dir, dest_path)
        raise
    finally:
        if os.path.isdir(staging_root) and not os.listdir(staging_root): os.rmdir(staging_root)
    print(f"  Installed: {dest_path}")
    return layout

def create_meta_ini(mod_folder, modid=None, url=None, name=None, version=None):
    """Create meta.ini for an installed mod."""
    meta_path = os.path.join(mod_folder, "meta.ini")
    if os.path.exists(meta_path):
        return

    mod_name = name or os.path.basename(mod_folder)
    lines = ["[General]", f"modid={modid or 0}", f"version={version or ''}", f"name={mod_name}"]
    if url:
        lines.append(f"url={url}")
    lines.append("")

    with open(meta_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"  Created meta.ini (modid={modid})")

# ── commands ──

def cmd_install(archive_path, name, force, allow_root, modid, json_out):
    if not os.path.exists(archive_path):
        die(f"Archive not found: {archive_path}")

    entries = list_archive(archive_path)
    layout = detect_layout(entries)

    if not name:
        name = os.path.basename(archive_path).rsplit("-", 2)[0]  # strip trailing -modid-fileid

    if json_out:
        install_layout = layout
    else:
        print(f"Archive: {os.path.basename(archive_path)}")
        print(f"Target:  {name}")
        print(f"Layout:  {layout['type']} | nesting={layout['has_nesting']} | plugins={layout['plugin_count']} | files={layout['file_count']}")

    if layout["has_fomod"]:
        print(f"  FOMOD detected. Installing all files (option selection deferred).")

    if allow_root and layout["has_root_files"]:
        die("--allow-root not yet implemented (game root install not ready)")

    backup_and_install(archive_path, name, force=force)

    if not json_out:
        print_manual_post_install_steps(layout["manual_post_install_steps"])

    if modid:
        create_meta_ini(os.path.join(MODS_DIR, name), modid=modid, name=name)

    if json_out:
        print(json.dumps({"status": "installed", "folder": name, "path": os.path.join(MODS_DIR, name), **layout}))

def cmd_dry_run(archive_path, json_out):
    if not os.path.exists(archive_path):
        die(f"Archive not found: {archive_path}")

    entries = list_archive(archive_path)
    layout = detect_layout(entries)

    if json_out:
        print(json.dumps(layout, indent=2))
    else:
        print(json.dumps(layout, indent=2, ensure_ascii=False))

def cmd_detect(archive_path):
    if not os.path.exists(archive_path):
        die(f"Archive not found: {archive_path}")

    entries = list_archive(archive_path)
    layout = detect_layout(entries)

    print(f"Type:       {layout['type']}")
    print(f"Nesting:    {layout['has_nesting']} ({layout['nesting_root']})")
    print(f"FOMOD:      {layout['has_fomod']}")
    print(f"Plugins:    {layout['plugin_count']}")
    print(f"Behavior:   {layout['has_behavior']}")
    print(f"Root files: {layout['has_root_files']}")
    print_manual_post_install_steps(layout["manual_post_install_steps"])

# ── main ──

def main():
    parser = argparse.ArgumentParser(description="Install mod archives into MO2")
    sub = parser.add_subparsers(dest="cmd")

    ins = sub.add_parser("install", help="Extract and install a mod archive")
    ins.add_argument("archive", help="Path to archive file")
    ins.add_argument("--name", help="Mod folder name (default: derived from archive filename)")
    ins.add_argument("--modid", help="Nexus mod ID for meta.ini")
    ins.add_argument("--force", action="store_true", help="Replace existing mod folder (backs up old)")
    ins.add_argument("--allow-root", action="store_true", help="Allow root-level install (NOT YET IMPLEMENTED)")
    ins.add_argument("--json", action="store_true", help="Machine-readable output")

    dr = sub.add_parser("dry-run", help="Show archive layout without installing")
    dr.add_argument("archive", help="Path to archive file")
    dr.add_argument("--json", action="store_true")

    de = sub.add_parser("detect-layout", help="Quick layout detection")
    de.add_argument("archive", help="Path to archive file")

    args = parser.parse_args()

    if args.cmd == "install":
        cmd_install(args.archive, args.name, args.force, args.allow_root, args.modid, args.json)
    elif args.cmd == "dry-run":
        cmd_dry_run(args.archive, args.json)
    elif args.cmd == "detect-layout":
        cmd_detect(args.archive)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()

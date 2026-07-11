#!/usr/bin/env python3
"""Selectively install archive paths into an MO2 mod with prefix stripping and required-path validation."""
import argparse, os, shutil, subprocess, sys, tempfile
from datetime import datetime
from pathlib import Path
if sys.platform=='win32': sys.stdout.reconfigure(encoding='utf-8', errors='replace')
SKILL=Path(__file__).resolve().parent.parent

def env_value(key):
    if os.environ.get(key): return os.environ[key]
    for raw in (SKILL/'.env').read_text(encoding='utf-8-sig').splitlines():
        if raw.strip() and not raw.lstrip().startswith('#') and '=' in raw:
            k,v=raw.split('=',1)
            if k.strip()==key:return v.strip().strip('"')
    raise SystemExit(f'ERROR: {key} is not configured')

def seven_zip():
    found=shutil.which('7z') or shutil.which('7z.exe')
    candidates=[found, r'C:\Program Files\7-Zip\7z.exe', r'C:\Program Files (x86)\7-Zip\7z.exe']
    for c in candidates:
        if c and Path(c).is_file(): return c
    raise SystemExit('ERROR: 7z executable not found')

def safe_target(root,name):
    target=(root/name).resolve(); base=root.resolve()
    if target.parent != base: raise SystemExit('ERROR: mod name must be one folder name')
    return target

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('archive'); ap.add_argument('--name',required=True)
    ap.add_argument('--include',action='append',default=[],help='7z archive path or wildcard; repeatable')
    ap.add_argument('--strip-prefix',default='',help='Remove this archive directory prefix after extraction')
    ap.add_argument('--require',action='append',default=[],help='Required relative output path; repeatable')
    ap.add_argument('--force',action='store_true'); ap.add_argument('--dry-run',action='store_true')
    a=ap.parse_args(); archive=Path(a.archive).resolve()
    if not archive.is_file(): raise SystemExit(f'ERROR: archive missing: {archive}')
    mods=Path(env_value('MO2_INSTANCE_PATH'))/'mods'; target=safe_target(mods,a.name)
    cmd=[seven_zip(),'x','-y']+[str(archive)]+a.include
    if a.dry_run:
        print({'target':str(target),'includes':a.include,'strip_prefix':a.strip_prefix,'required':a.require}); return
    if target.exists() and not a.force: raise SystemExit(f'ERROR: target exists: {target}')
    with tempfile.TemporaryDirectory(prefix='mo2-select-',dir=str(Path(env_value('MO2_INSTANCE_PATH')))) as td:
        stage=Path(td); run=cmd[:2]+[f'-o{stage}']+cmd[2:]
        cp=subprocess.run(run)
        if cp.returncode: raise SystemExit(f'ERROR: 7z extraction failed: {cp.returncode}')
        source=stage/Path(a.strip_prefix.replace('\\','/')) if a.strip_prefix else stage
        if not source.is_dir(): raise SystemExit(f'ERROR: strip prefix not found: {a.strip_prefix}')
        missing=[r for r in a.require if not (source/Path(r.replace('\\','/'))).exists()]
        if missing: raise SystemExit('ERROR: required paths missing after mapping: '+', '.join(missing))
        if not any(source.iterdir()): raise SystemExit('ERROR: extraction produced no installable files')
        if target.exists():
            backup=Path(env_value('MO2_INSTANCE_PATH'))/'_codex_backups'/'mods'/datetime.now().strftime('%Y%m%d-%H%M%S')/a.name
            backup.parent.mkdir(parents=True,exist_ok=True); shutil.move(str(target),str(backup))
        shutil.move(str(source),str(target))
    print(f'Installed {target}')
    for r in a.require: print(f'  verified: {r}')
if __name__=='__main__': main()

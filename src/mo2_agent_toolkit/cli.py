from __future__ import annotations

import argparse
import contextlib
import io
import ctypes
import hashlib
import re
import subprocess
import tempfile
import time
from webbrowser import open_new_tab as open_browser_tab
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import runpy
import shutil
import sys
import tomllib
from typing import Any

from . import __version__
from .auth import AuthError, credential_status, dpapi_unprotect, remove_key, validate_and_save
from .workflow import WorkflowError

SCHEMA_VERSION = 1
CONFIG_SCHEMA_VERSION = 2
CONFIG_HOME = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "MO2AgentToolkit"
CONFIG_PATH = CONFIG_HOME / "config.toml"
SECRET_PATH = CONFIG_HOME / "secrets" / "nexus_api_key.dpapi"
SESSIONS_DIR = CONFIG_HOME / "sessions"
PLANS_DIR = CONFIG_HOME / "plans"
REQUIRED_DIRS = ("mods", "downloads", "profiles", "overwrite")
LEGACY_DIR = Path(__file__).resolve().parent / "legacy"

class CaptureStringIO(io.StringIO):
    def reconfigure(self, **kwargs: Any) -> None:
        return None

class ToolError(Exception):
    def __init__(self, message: str, code: int = 2, details: Any = None):
        super().__init__(message); self.code = code; self.details = details

def envelope(status: str, data: Any = None, warnings: list[str] | None = None, errors: list[str] | None = None) -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "tool_version": __version__, "status": status,
            "warnings": warnings or [], "errors": errors or [], "data": data}

def emit(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"MO2 Agent Toolkit {__version__}: {payload['status']}")
        for item in payload.get("warnings", []): print(f"WARNING: {item}")
        for item in payload.get("errors", []): print(f"ERROR: {item}")
        data = payload.get("data")
        if data is not None: print(json.dumps(data, ensure_ascii=False, indent=2) if isinstance(data, (dict,list)) else data)

def q(value: str) -> str:
    return '"' + value.replace('\\','/').replace('"','\\"') + '"'

def load_config(path: Path | None = None) -> dict[str, Any]:
    path = path or CONFIG_PATH
    if not path.exists(): return {}
    return tomllib.loads(path.read_text(encoding="utf-8-sig"))

def save_config(config: dict[str, Any], path: Path | None = None) -> None:
    path = path or CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"schema_version = {CONFIG_SCHEMA_VERSION}"]
    for key in ("mo2_instance_path", "profile", "skyrim_game_path", "seven_zip_path", "download_directory", "archive_directory"):
        lines.append(f"{key} = {q(str(config.get(key, '')))}")
    lines.append(f"archive_after_install = {str(bool(config.get('archive_after_install', False))).lower()}")
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(lines)+"\n", encoding="utf-8", newline="\n")
    os.replace(tmp, path)

def valid_instance(path: Path) -> bool:
    return path.is_dir() and all((path / name).is_dir() for name in REQUIRED_DIRS)

def discover_instances() -> list[Path]:
    found: set[Path] = set()
    hints = [os.environ.get("MO2_INSTANCE_PATH", ""), Path.home()/"AppData/Local/ModOrganizer",
             Path.home()/"AppData/Local/ModOrganizer/Skyrim Special Edition", Path("C:/Modding/MO2")]
    for raw in hints:
        if not raw: continue
        path = Path(raw).expanduser()
        candidates = [path]
        if path.is_dir():
            try: candidates.extend(x for x in path.iterdir() if x.is_dir())
            except OSError: pass
        for item in candidates:
            if valid_instance(item):
                try: found.add(item.resolve())
                except OSError: found.add(item)
    return sorted(found, key=lambda x: str(x).lower())

def profiles(instance: Path) -> list[str]:
    root = instance / "profiles"
    return sorted([p.name for p in root.iterdir() if p.is_dir() and (p/"modlist.txt").exists()]) if root.exists() else []

def find_7zip(config: dict[str, Any]) -> str | None:
    candidates = [config.get("seven_zip_path", ""), Path(sys.executable).parent/"7za.exe",
                  Path("C:/Program Files/7-Zip/7z.exe"), shutil.which("7z"), shutil.which("7za")]
    for value in candidates:
        if value and Path(value).is_file(): return str(Path(value).resolve())
    return None

def apply_environment(config: dict[str, Any]) -> None:
    mapping = {"mo2_instance_path":"MO2_INSTANCE_PATH", "skyrim_game_path":"SKYRIM_GAME_PATH"}
    for key, env in mapping.items():
        if config.get(key): os.environ[env] = str(config[key])
    seven_zip = find_7zip(config)
    if seven_zip: os.environ["SEVEN_ZIP_PATH"] = seven_zip
    if SECRET_PATH.exists(): os.environ["NEXUS_API_KEY"] = dpapi_unprotect(SECRET_PATH.read_bytes()).decode("utf-8")

def run_legacy(script: str, argv: list[str], config: dict[str, Any]) -> int:
    target = LEGACY_DIR / script
    if not target.exists(): raise ToolError(f"Bundled backend missing: {script}", 10)
    apply_environment(config)
    previous = sys.argv[:]; json_mode = "--json" in argv
    stdout = CaptureStringIO() if json_mode else None; stderr = CaptureStringIO() if json_mode else None
    code = 0
    try:
        sys.argv = [str(target), *argv]
        with contextlib.redirect_stdout(stdout) if stdout else contextlib.nullcontext(), contextlib.redirect_stderr(stderr) if stderr else contextlib.nullcontext():
            runpy.run_path(str(target), run_name="__main__")
    except SystemExit as exc:
        code = int(exc.code or 0)
    finally:
        sys.argv = previous
    if json_mode:
        raw = stdout.getvalue().strip(); err = stderr.getvalue().strip(); data: Any = None
        if raw:
            try: data = json.loads(raw)
            except json.JSONDecodeError:
                lines = raw.splitlines()
                for index in range(len(lines)):
                    try: data = json.loads("\n".join(lines[index:])); break
                    except json.JSONDecodeError: continue
                if data is None: data = {"output": raw}
        warnings = [line.removeprefix("WARNING:").strip() for line in err.splitlines() if line.strip().startswith("WARNING:")]
        errors = [line.removeprefix("ERROR:").strip() for line in err.splitlines() if line.strip() and not line.strip().startswith("WARNING:")]
        status = "success" if code == 0 and not warnings else ("warning" if code in (0,1) and not errors else "error")
        emit(envelope(status, data, warnings, errors), True)
    return code

def handle_setup(args: argparse.Namespace) -> tuple[dict[str,Any],int]:
    found = discover_instances()
    if args.instance:
        chosen = Path(args.instance).expanduser().resolve()
        if not valid_instance(chosen): raise ToolError("Selected path is not a valid MO2 instance", 2)
    elif len(found) == 1: chosen = found[0]
    else:
        return envelope("review", {"config_path":str(CONFIG_PATH), "instances":[str(p) for p in found]},
                        ["Select an instance with --instance" if found else "No MO2 instance was discovered"]), 1
    choices = profiles(chosen)
    profile = args.profile or (choices[0] if len(choices)==1 else "")
    if profile and profile not in choices: raise ToolError("Selected profile does not exist", 2)
    if not profile:
        return envelope("review", {"instance":str(chosen),"profiles":choices}, ["Select a profile with --profile"]),1
    cfg=load_config()
    cfg.update({"mo2_instance_path":str(chosen),"profile":profile})
    if args.game is not None: cfg["skyrim_game_path"]=args.game
    if args.seven_zip is not None: cfg["seven_zip_path"]=args.seven_zip
    cfg.setdefault("skyrim_game_path",""); cfg.setdefault("seven_zip_path","")
    cfg.setdefault("download_directory",str(default_browser_downloads_dir()))
    cfg.setdefault("archive_after_install",False); cfg.setdefault("archive_directory",str(chosen/"downloads"))
    if not args.dry_run: save_config(cfg)
    return envelope("success", {"config_path":str(CONFIG_PATH),"dry_run":args.dry_run,**cfg}),0

def handle_doctor(args: argparse.Namespace) -> tuple[dict[str,Any],int]:
    cfg=load_config(Path(args.config) if args.config else CONFIG_PATH); warnings=[]; checks={}
    instance=Path(cfg.get("mo2_instance_path", "")) if cfg.get("mo2_instance_path") else None
    checks["config_exists"] = bool(cfg)
    checks["mo2_instance_valid"] = bool(instance and valid_instance(instance))
    checks["profile_valid"] = bool(instance and cfg.get("profile") and (instance/"profiles"/cfg["profile"]).is_dir())
    game=Path(cfg.get("skyrim_game_path", "")) if cfg.get("skyrim_game_path") else None
    checks["game_root_valid"] = bool(game and (game/"SkyrimSE.exe").is_file())
    checks["seven_zip"] = find_7zip(cfg)
    checks["nexus_credential"] = credential_status(SECRET_PATH)
    if not checks["config_exists"]: warnings.append("Run setup before write operations")
    if not checks["mo2_instance_valid"]: warnings.append("MO2 instance is missing or invalid")
    if not checks["profile_valid"]: warnings.append("Active profile is missing or invalid")
    if not checks["game_root_valid"]: warnings.append("Skyrim game root is missing or invalid; game-root deployment is unavailable")
    if not checks["seven_zip"]: warnings.append("7-Zip was not found; 7z/rar extraction may fail")
    return envelope("success" if not warnings else "warning", {"config_path":str(CONFIG_PATH),"checks":checks}, warnings), 0 if not warnings else 1

def write_manifest(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    os.replace(temp, path)

def start_transaction(cfg: dict[str, Any], operation: str, entries: list[dict[str, Any]]) -> tuple[Path, dict[str, Any]]:
    root = backups_root(cfg)
    transaction_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    tx = root / transaction_id
    manifest = {"schema_version": 1, "id": transaction_id, "operation": operation,
                "status": "in_progress", "created_at": datetime.now().astimezone().isoformat(),
                "files": entries}
    write_manifest(tx / "manifest.json", manifest)
    return tx, manifest

def snapshot_profile(cfg: dict[str, Any], profile: str) -> tuple[Path, dict[str, Any]]:
    base = Path(cfg["mo2_instance_path"]) / "profiles" / profile
    paths = [base / name for name in ("modlist.txt", "plugins.txt", "loadorder.txt")]
    if not all(path.is_file() for path in paths): raise ToolError(f"Profile is incomplete: {profile}", 2)
    tx, manifest = start_transaction(cfg, "profile_apply", [])
    for path in paths:
        rel = Path("profile") / path.name
        target = tx / rel; target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(path, target)
        manifest["files"].append({"kind":"file", "backup":str(rel).replace("\\","/"), "destination":str(path)})
    write_manifest(tx / "manifest.json", manifest)
    return tx, manifest

def transaction_mod_name(archive: str, extra: list[str]) -> str:
    for index, value in enumerate(extra):
        if value == "--name" and index + 1 < len(extra): return extra[index + 1]
        if value.startswith("--name="): return value.split("=", 1)[1]
    return Path(archive).name.rsplit("-", 2)[0]

def prepare_mod_transaction(cfg: dict[str, Any], operation: str, archive: str, extra: list[str]) -> tuple[Path, dict[str, Any]]:
    name = transaction_mod_name(archive, extra)
    destination = Path(cfg["mo2_instance_path"]) / "mods" / name
    entry = {"kind":"directory" if destination.exists() else "absent", "destination":str(destination)}
    if destination.exists(): entry["backup"] = str(Path("mods") / name).replace("\\","/")
    return start_transaction(cfg, operation, [entry])

def finish_transaction(tx: Path, manifest: dict[str, Any], status: str, exit_code: int) -> None:
    manifest["status"] = status; manifest["exit_code"] = exit_code
    manifest["finished_at"] = datetime.now().astimezone().isoformat()
    write_manifest(tx / "manifest.json", manifest)

def backups_root(cfg: dict[str,Any]) -> Path:
    if not cfg.get("mo2_instance_path"): raise ToolError("MO2 instance is not configured",2)
    return Path(cfg["mo2_instance_path"])/"_agent_toolkit_backups"

def handle_backup(args: argparse.Namespace) -> tuple[dict[str,Any],int]:
    root=backups_root(load_config())
    if args.backup_command=="list":
        items=[{"id":p.name,"path":str(p)} for p in sorted(root.iterdir(),reverse=True) if p.is_dir()] if root.exists() else []
        return envelope("success",items),0
    target=(root/args.backup_id).resolve()
    if root.resolve() not in target.parents or not target.is_dir(): raise ToolError("Backup does not exist",2)
    manifest=target/"manifest.json"
    if not manifest.exists(): raise ToolError("Backup has no restorable manifest",3)
    data=json.loads(manifest.read_text(encoding="utf-8-sig"))
    if args.backup_command=="inspect": return envelope("success",data),0
    if not args.yes: return envelope("review",data,["Restore requires --yes after inspection"]),1
    for entry in data.get("files",[]):
        dest=Path(entry["destination"]); kind=entry.get("kind", "file")
        if kind == "absent":
            if dest.is_dir(): shutil.rmtree(dest)
            elif dest.exists(): dest.unlink()
            continue
        source=target/entry["backup"]
        if kind == "directory":
            if not source.is_dir(): raise ToolError(f"Backup directory missing: {source}",5)
            if dest.exists(): shutil.rmtree(dest) if dest.is_dir() else dest.unlink()
            dest.parent.mkdir(parents=True,exist_ok=True); shutil.copytree(source,dest)
        else:
            if not source.is_file(): raise ToolError(f"Backup file missing: {source}",5)
            dest.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(source,dest)
    data["status"]="restored"; data["restored_at"]=datetime.now().astimezone().isoformat(); write_manifest(manifest,data)
    return envelope("success",{"restored":args.backup_id}),0

def _safe_relative_files(root: Path) -> list[Path]:
    files=[]
    for path in root.rglob("*"):
        if path.is_symlink(): raise ToolError(f"Archive contains a symbolic link: {path.name}",3)
        if path.is_file():
            rel=path.relative_to(root)
            if rel.is_absolute() or ".." in rel.parts: raise ToolError("Archive path escapes the staging directory",3)
            files.append(rel)
    return sorted(files, key=lambda item: item.as_posix().lower())

def _extract_root_archive(archive: Path, staging: Path, cfg: dict[str,Any]) -> Path:
    seven_zip=find_7zip(cfg)
    if not seven_zip: raise ToolError("7-Zip is required for game-root archive inspection",3)
    result=subprocess.run([seven_zip,"x",str(archive),f"-o{staging}","-y"],capture_output=True,encoding="utf-8",errors="replace",timeout=300)
    if result.returncode != 0: raise ToolError(f"7-Zip extraction failed with code {result.returncode}",5)
    children=list(staging.iterdir())
    if len(children)==1 and children[0].is_dir(): return children[0]
    return staging

def _classify_root_package(files: list[Path]) -> str:
    lowered={p.as_posix().lower() for p in files}
    names={p.name.lower() for p in files}
    if "skse64_loader.exe" in names and any(re.fullmatch(r"skse64_\d+_\d+_\d+\.dll",name) for name in names): return "skse"
    if "d3dx9_42.dll" in names and any(name.startswith("tbb") and name.endswith(".dll") for name in names): return "engine_fixes"
    raise ToolError("Unknown game-root package; only recognized SKSE and Engine Fixes root packages are allowed",3)

def _game_processes_running() -> list[str]:
    result=subprocess.run(["tasklist","/FO","CSV","/NH"],capture_output=True,encoding="utf-8",errors="replace",timeout=30)
    text=result.stdout.lower()
    return [name for name in ("skyrimse.exe","skse64_loader.exe","modorganizer.exe") if name in text]

def handle_root(args: argparse.Namespace) -> tuple[dict[str,Any],int]:
    cfg=load_config()
    if args.root_command=="deploy" and not args.dry_run:
        running=__import__("mo2_agent_toolkit.workflow",fromlist=["mo2_running"]).mo2_running()
        if running: raise ToolError("Close Mod Organizer 2 before game-root deployment",3,{"processes":running})
    game=Path(cfg.get("skyrim_game_path", "")) if cfg.get("skyrim_game_path") else None
    if not game or not (game/"SkyrimSE.exe").is_file():
        raise ToolError("A verified Skyrim game root is required; run setup --game <folder containing SkyrimSE.exe>",3)
    archive=Path(args.archive).expanduser().resolve()
    if not archive.is_file(): raise ToolError("Archive does not exist",2)
    with tempfile.TemporaryDirectory(prefix="mo2-root-inspect-") as td:
        content=_extract_root_archive(archive,Path(td),cfg); files=_safe_relative_files(content)
        package_type=_classify_root_package(files)
        conflicts=[p.as_posix() for p in files if (game/p).exists()]
        data={"package_type":package_type,"archive":str(archive),"game_root":str(game.resolve()),
              "file_count":len(files),"files":[p.as_posix() for p in files],"existing_files":conflicts,
              "requires_confirmation":True}
        if args.root_command=="inspect" or args.dry_run:
            return envelope("review",data,["Game-root deployment is separate from MO2 and requires deploy --yes"]),1
        running=_game_processes_running()
        if running: raise ToolError(f"Close processes before game-root deployment: {', '.join(running)}",3)
        if not args.yes: return envelope("review",data,["Deployment requires --yes after inspection"]),1
        entries=[]
        for rel in files:
            dest=game/rel
            entry={"kind":"file" if dest.is_file() else "absent","destination":str(dest)}
            if dest.is_file(): entry["backup"]=(Path("game-root")/rel).as_posix()
            elif dest.exists(): raise ToolError(f"Destination is not a file: {dest}",3)
            entries.append(entry)
        tx,manifest=start_transaction(cfg,"game_root_deploy",entries)
        try:
            for rel,entry in zip(files,entries):
                src=content/rel; dest=game/rel
                if entry["kind"]=="file":
                    backup=tx/entry["backup"]; backup.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(dest,backup)
                dest.parent.mkdir(parents=True,exist_ok=True)
                temp=dest.with_name(dest.name+".mo2-tool.tmp"); shutil.copy2(src,temp); os.replace(temp,dest)
            finish_transaction(tx,manifest,"complete",0)
        except BaseException:
            for entry in reversed(entries):
                dest=Path(entry["destination"])
                if entry["kind"]=="absent":
                    if dest.exists(): dest.unlink()
                else:
                    backup=tx/entry["backup"]
                    if backup.exists(): dest.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(backup,dest)
            finish_transaction(tx,manifest,"rolled_back",5)
            raise
        data["backup_id"]=tx.name; data["deployed"]=True
        return envelope("success",data),0

def default_browser_downloads_dir() -> Path:
    """Resolve the current Windows user's Downloads known folder."""
    if os.name == "nt":
        try:
            import winreg
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
            downloads_id = "{374DE290-123F-4565-9164-39C4925E467B}"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                value, _kind = winreg.QueryValueEx(key, downloads_id)
            return Path(os.path.expandvars(str(value))).expanduser().resolve()
        except (OSError, ValueError):
            pass
    return (Path.home() / "Downloads").resolve()

TEMP_DOWNLOAD_SUFFIXES = (".crdownload", ".part", ".tmp", ".download", ".meta")
ARCHIVE_SUFFIXES = (".zip", ".7z", ".rar", ".gz")

def _nexus_file_metadata(mod_id: int, file_id: int) -> dict[str,Any]:
    if not SECRET_PATH.exists(): raise ToolError("Nexus API key is required; configure a free account key with auth set",2)
    key=dpapi_unprotect(SECRET_PATH.read_bytes()).decode("utf-8")
    url=f"https://api.nexusmods.com/v1/games/skyrimspecialedition/mods/{mod_id}/files.json"
    request=urllib.request.Request(url,headers={"apikey":key,"Accept":"application/json","User-Agent":"MO2AgentToolkit/0.2"})
    try:
        with urllib.request.urlopen(request,timeout=30) as response:
            payload=json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ToolError(f"Nexus metadata request failed with HTTP {exc.code}",4) from exc
    except (urllib.error.URLError,TimeoutError) as exc:
        raise ToolError(f"Nexus metadata request failed: {exc.reason if hasattr(exc,'reason') else exc}",4) from exc
    target=next((item for item in payload.get("files",[]) if str(item.get("file_id"))==str(file_id)),None)
    if not target: raise ToolError(f"File ID {file_id} was not found for Nexus mod {mod_id}",2)
    size=target.get("size_in_bytes")
    if not size and target.get("size_kb") is not None: size=int(target["size_kb"])*1024
    last_modified=target.get("uploaded_time")
    if not last_modified and target.get("uploaded_timestamp") is not None:
        last_modified=datetime.fromtimestamp(int(target["uploaded_timestamp"]),timezone.utc).isoformat().replace("+00:00","Z")
    official=Path(str(target.get("file_name") or f"nexus-{mod_id}-{file_id}")).name
    return {"provider":"nexus","mod_id":mod_id,"file_id":file_id,"file_name":official,"official_filename":official,
            "version":str(target.get("version") or ""),"last_modified":last_modified,
            "category_name":target.get("category_name"),"expected_size_bytes":int(size) if size else None}

def _download_snapshot(folder: Path) -> dict[str,tuple[int,int]]:
    result={}
    if not folder.is_dir(): return result
    for path in folder.iterdir():
        try:
            if path.is_file(): result[path.name]=(path.stat().st_size,path.stat().st_mtime_ns)
        except OSError: continue
    return result

def _candidate_score(path: Path, metadata: dict[str,Any]) -> int:
    name=path.name.lower(); expected=metadata["file_name"].lower()
    if name.endswith(TEMP_DOWNLOAD_SUFFIXES) or path.suffix.lower() not in ARCHIVE_SUFFIXES: return -1
    score=0
    if name==expected: score+=100
    expected_stem=Path(expected).stem.lower()
    if path.stem.lower()==expected_stem: score+=80
    if str(metadata["mod_id"]) in name: score+=10
    if str(metadata["file_id"]) in name: score+=20
    size=metadata.get("expected_size_bytes")
    if size:
        delta=abs(path.stat().st_size-size); tolerance=max(4096,int(size*0.001))
        if delta<=tolerance: score+=40
        else: return -1
    return score if score>=40 else -1

def _test_and_inspect_archive(path: Path, cfg: dict[str,Any]) -> dict[str,Any]:
    seven_zip=find_7zip(cfg)
    if not seven_zip: raise ToolError("7-Zip is required to validate the downloaded archive",3)
    tested=subprocess.run([seven_zip,"t",str(path)],capture_output=True,encoding="utf-8",errors="replace",timeout=300)
    if tested.returncode != 0: raise ToolError("Downloaded file failed the 7-Zip integrity test",3)
    from .workflow import inspect_archive
    return inspect_archive(path,seven_zip)

def _recommended_download_commands(path: Path, layout: dict[str,Any], mod_id: int | None = None, file_id: int | None = None) -> list[str]:
    quoted=f'"{path}"'
    if layout.get("type")=="root":
        return [f"mo2-tool root inspect {quoted} --json",f"mo2-tool root deploy {quoted} --dry-run --json"]
    metadata = f" --modid {mod_id} --file-id {file_id}" if mod_id is not None and file_id is not None else ""
    commands=[f"mo2-tool install inspect {quoted} --json"]
    if layout.get("type")=="fomod":
        commands.append(f"mo2-tool install plan {quoted} --selections <selections.json>{metadata} --json")
    else:commands.append(f"mo2-tool install plan {quoted}{metadata} --json")
    return commands

def handle_nexus_request(args: argparse.Namespace) -> tuple[dict[str,Any],int]:
    cfg=load_config(); instance=Path(cfg.get("mo2_instance_path", ""))
    if not valid_instance(instance): raise ToolError("A valid MO2 instance is required",2)
    folder=Path(args.downloads_dir).expanduser().resolve() if args.downloads_dir else default_browser_downloads_dir()
    folder.mkdir(parents=True,exist_ok=True)
    metadata=_nexus_file_metadata(args.mod_id,args.file_id)
    url=f"https://www.nexusmods.com/skyrimspecialedition/mods/{args.mod_id}?tab=files&file_id={args.file_id}"
    before=_download_snapshot(folder)
    if args.open_browser and not open_browser_tab(url):
        raise ToolError("Unable to open the system browser",5)
    if not args.wait:
        return envelope("review",{**metadata,"manual_url":url,"downloads_dir":str(folder),"waiting":False},
                        ["Rerun with --wait before beginning the official Manual/Slow Download"]),1
    deadline=time.monotonic()+args.timeout; stable: dict[Path,tuple[int,int]]={}
    while time.monotonic()<deadline:
        scored=[]
        for path in folder.iterdir():
            if not path.is_file(): continue
            stat=path.stat(); previous=before.get(path.name)
            if previous==(stat.st_size,stat.st_mtime_ns): continue
            score=_candidate_score(path,metadata)
            if score<0: continue
            old=stable.get(path)
            count=old[1]+1 if old and old[0]==stat.st_size else 1
            stable[path]=(stat.st_size,count)
            if count>=2: scored.append((score,path))
        if scored:
            matches=[path for _score,path in scored]
            if len(matches)>1:
                data={**metadata,"manual_url":url,"downloads_dir":str(folder),"candidates":[str(p) for p in matches]}
                return envelope("review",data,["Multiple downloaded files match; choose one explicitly"]),1
            path=matches[0]; layout=_test_and_inspect_archive(path,cfg)
            data={**metadata,"status":"verified","path":str(path),"actual_size_bytes":path.stat().st_size,
                  "manual_url":url,"archive_test":"passed","layout":layout,
                  "recommended_commands":_recommended_download_commands(path,layout,args.mod_id,args.file_id)}
            return envelope("success",data),0
        time.sleep(args.poll_interval)
    retry=f'mo2-tool nexus request {args.mod_id} {args.file_id} --downloads-dir "<folder containing the downloaded file>" --json'
    return envelope("review",{**metadata,"manual_url":url,"downloads_dir":str(folder),"timeout_seconds":args.timeout,
                              "recommended_command":retry},
                    ["No matching file was found in the browser Downloads folder; provide its folder with --downloads-dir"]),1

def parser() -> argparse.ArgumentParser:
    p=argparse.ArgumentParser(prog="mo2-tool"); p.add_argument("--version",action="version",version=__version__)
    sub=p.add_subparsers(dest="command",required=True)
    s=sub.add_parser("setup"); s.add_argument("--instance"); s.add_argument("--profile"); s.add_argument("--game"); s.add_argument("--seven-zip"); s.add_argument("--dry-run",action="store_true"); s.add_argument("--json",action="store_true")
    d=sub.add_parser("doctor"); d.add_argument("--config"); d.add_argument("--json",action="store_true")
    c=sub.add_parser("config"); cc=c.add_subparsers(dest="config_command",required=True); cs=cc.add_parser("show"); cs.add_argument("--json",action="store_true")
    cset=cc.add_parser("set"); cset.add_argument("--download-directory"); cset.add_argument("--archive-directory"); cset.add_argument("--archive-after-install",choices=("true","false")); cset.add_argument("--json",action="store_true")
    a=sub.add_parser("auth"); aa=a.add_subparsers(dest="auth_command",required=True)
    auth_set=aa.add_parser("set")
    auth_mode=auth_set.add_mutually_exclusive_group()
    auth_mode.add_argument("--gui",action="store_true")
    auth_mode.add_argument("--console",action="store_true")
    auth_set.add_argument("--json",action="store_true")
    for name in ("status","remove","clear"):
        x=aa.add_parser(name); x.add_argument("--json",action="store_true")
    n=sub.add_parser("nexus"); nn=n.add_subparsers(dest="nexus_command",required=True)
    ni=nn.add_parser("info"); ni.add_argument("mod_id"); ni.add_argument("--json",action="store_true")
    ndp=nn.add_parser("deps"); ndp.add_argument("mod_id"); ndp.add_argument("--json",action="store_true")
    ndl=nn.add_parser("download"); ndl.add_argument("values",nargs="+"); ndl.add_argument("--json",action="store_true")
    nr=nn.add_parser("request"); nr.add_argument("mod_id",type=int); nr.add_argument("file_id",type=int)
    nr.add_argument("--downloads-dir"); nr.add_argument("--timeout",type=int,default=900)
    nr.add_argument("--poll-interval",type=float,default=2.0,help=argparse.SUPPRESS)
    nr.add_argument("--open-browser",dest="open_browser",action="store_true",default=True)
    nr.add_argument("--no-open-browser",dest="open_browser",action="store_false")
    nr.add_argument("--wait",dest="wait",action="store_true",default=True)
    nr.add_argument("--no-wait",dest="wait",action="store_false"); nr.add_argument("--json",action="store_true")
    nb=nn.add_parser("batch"); nbb=nb.add_subparsers(dest="batch_command",required=True)
    nbp=nbb.add_parser("prepare"); nbp.add_argument("target"); nbp.add_argument("--file-id",type=int,action="append",default=[]); nbp.add_argument("--include-optional",action="append",default=[]); nbp.add_argument("--downloads-dir"); nbp.add_argument("--no-open-browser",action="store_true"); nbp.add_argument("--json",action="store_true")
    for bn in ("status","collect"):
        bx=nbb.add_parser(bn); bx.add_argument("session_id"); bx.add_argument("--json",action="store_true")
    plan=sub.add_parser("plan"); plan.add_argument("target"); plan.add_argument("--json",action="store_true")
    ar=sub.add_parser("archive"); ara=ar.add_subparsers(dest="archive_command",required=True); ai=ara.add_parser("inspect"); ai.add_argument("archive"); ai.add_argument("--json",action="store_true")
    retry=ara.add_parser("retry"); retry.add_argument("plan_id"); retry.add_argument("--json",action="store_true")
    root=sub.add_parser("root"); rr=root.add_subparsers(dest="root_command",required=True)
    ri=rr.add_parser("inspect"); ri.add_argument("archive"); ri.add_argument("--json",action="store_true"); ri.set_defaults(dry_run=True,yes=False)
    rd=rr.add_parser("deploy"); rd.add_argument("archive"); rd.add_argument("--dry-run",action="store_true"); rd.add_argument("--yes",action="store_true"); rd.add_argument("--json",action="store_true")
    ins=sub.add_parser("install"); ii=ins.add_subparsers(dest="install_command",required=True)
    ix=ii.add_parser("inspect"); ix.add_argument("archive"); ix.add_argument("--json",action="store_true")
    ip=ii.add_parser("plan"); ip.add_argument("archive"); ip.add_argument("--name"); ip.add_argument("--selections"); ip.add_argument("--modid",type=int); ip.add_argument("--file-id",type=int); ip.add_argument("--full-context",action="store_true"); ip.add_argument("--json",action="store_true")
    placement_group=ip.add_mutually_exclusive_group()
    placement_group.add_argument("--before-mod"); placement_group.add_argument("--after-mod")
    placement_group.add_argument("--modlist-top",action="store_true"); placement_group.add_argument("--modlist-bottom",action="store_true")
    for action in ("apply","resume"):
        ia=ii.add_parser(action); ia.add_argument("plan_id"); ia.add_argument("--yes",action="store_true"); ia.add_argument("--json",action="store_true")
        placement_group=ia.add_mutually_exclusive_group()
        placement_group.add_argument("--before-mod"); placement_group.add_argument("--after-mod")
        placement_group.add_argument("--modlist-top",action="store_true"); placement_group.add_argument("--modlist-bottom",action="store_true")
    il=ii.add_parser("legacy",help=argparse.SUPPRESS); il.add_argument("archive"); il.add_argument("args",nargs=argparse.REMAINDER); il.add_argument("--dry-run",action="store_true"); il.add_argument("--json",action="store_true")
    x=sub.add_parser("update"); x.add_argument("archive"); x.add_argument("args",nargs=argparse.REMAINDER); x.add_argument("--dry-run",action="store_true"); x.add_argument("--json",action="store_true")
    pr=sub.add_parser("profile"); pp=pr.add_subparsers(dest="profile_command",required=True)
    pa=pp.add_parser("audit"); pa.add_argument("profile",nargs="?"); pa.add_argument("--json",action="store_true")
    pap=pp.add_parser("apply"); pap.add_argument("profile",nargs="?");
    pap.add_argument("--enable-mod",action="append",default=[]); pap.add_argument("--disable-mod",action="append",default=[])
    pap.add_argument("--enable-plugin",action="append",default=[]); pap.add_argument("--disable-plugin",action="append",default=[]); pap.add_argument("--unregister-plugin",action="append",default=[])
    pg=pap.add_mutually_exclusive_group(); pg.add_argument("--before-mod"); pg.add_argument("--after-mod"); pg.add_argument("--modlist-top",action="store_true"); pg.add_argument("--modlist-bottom",action="store_true")
    pap.add_argument("--dry-run",action="store_true"); pap.add_argument("--json",action="store_true")
    npc=sub.add_parser("npc",help="Scan, plan, decide, apply, and verify NPC FaceGen conflicts")
    np=npc.add_subparsers(dest="npc_command",required=True)
    ns=np.add_parser("scan"); ns.add_argument("--output"); ns.add_argument("--sidecar"); ns.add_argument("--json",action="store_true")
    nplan=np.add_parser("plan"); nplan.add_argument("scan"); nplan.add_argument("--output"); nplan.add_argument("--json",action="store_true")
    nd=np.add_parser("decide"); nd.add_argument("plan"); nd.add_argument("decisions"); nd.add_argument("--output"); nd.add_argument("--json",action="store_true")
    na=np.add_parser("apply"); na.add_argument("plan"); na.add_argument("--yes",action="store_true"); na.add_argument("--json",action="store_true")
    nv=np.add_parser("verify"); nv.add_argument("plan"); nv.add_argument("--json",action="store_true")
    b=sub.add_parser("backup"); bb=b.add_subparsers(dest="backup_command",required=True)
    bl=bb.add_parser("list"); bl.add_argument("--json",action="store_true")
    for name in ("inspect","restore"):
        x=bb.add_parser(name); x.add_argument("backup_id"); x.add_argument("--yes",action="store_true"); x.add_argument("--json",action="store_true")
    internal=sub.add_parser("_legacy"); internal.add_argument("script"); internal.add_argument("args",nargs=argparse.REMAINDER)
    return p

def _configure_stdio() -> None:
    for stream in (sys.stdout,sys.stderr):
        reconfigure=getattr(stream,'reconfigure',None)
        if callable(reconfigure):reconfigure(encoding='utf-8',errors='replace')


def main(argv: list[str] | None=None) -> int:
    _configure_stdio()
    actual=list(argv) if argv is not None else sys.argv[1:]
    if len(actual)>=2 and actual[0]=="install" and actual[1] not in ("inspect","plan","apply","resume","legacy","-h","--help"):
        actual.insert(1,"legacy")
    args=parser().parse_args(actual)
    # argparse.REMAINDER preserves legacy installer options, but also captures
    # toolkit flags placed after the archive. Promote our flags back out.
    if (getattr(args, "command", None)=="update" or (getattr(args,"command",None)=="install" and getattr(args,"install_command",None)=="legacy")):
        trailing = list(args.args)
        if "--dry-run" in trailing:
            args.dry_run = True
            trailing.remove("--dry-run")
        if "--json" in trailing:
            args.json = True
            trailing.remove("--json")
        args.args = trailing
    as_json=getattr(args,"json",False)
    try:
        if args.command=="setup": payload,code=handle_setup(args)
        elif args.command=="doctor": payload,code=handle_doctor(args)
        elif args.command=="config":
            cfg=load_config()
            if args.config_command=="show": payload,code=envelope("success",{"config_path":str(CONFIG_PATH),**cfg,"needs_first_use_preferences":any(k not in cfg for k in ("download_directory","archive_after_install","archive_directory"))}),0
            else:
                if args.download_directory is not None: cfg["download_directory"]=str(Path(args.download_directory).expanduser().resolve())
                if args.archive_directory is not None: cfg["archive_directory"]=str(Path(args.archive_directory).expanduser().resolve())
                if args.archive_after_install is not None: cfg["archive_after_install"]=args.archive_after_install=="true"
                save_config(cfg); payload,code=envelope("success",{"config_path":str(CONFIG_PATH),**cfg}),0
        elif args.command=="auth":
            if args.auth_command=="set":
                if args.gui:
                    from .auth_gui import run_auth_gui
                    result=run_auth_gui(SECRET_PATH)
                    if result.error: raise ToolError(str(result.error),result.error.code,{"category":result.error.category})
                    if result.status=="cancelled":
                        payload,code=envelope("cancelled",{"configured":result.configured,"provider":"windows_dpapi","input_mode":"gui"}),0
                    else:
                        payload,code=envelope("success",{"configured":True,"provider":"windows_dpapi","validation":"valid","input_mode":"gui"}),0
                else:
                    import getpass
                    key=getpass.getpass("Nexus API key: ")
                    validate_and_save(key,SECRET_PATH)
                    key=""
                    payload,code=envelope("success",{"configured":True,"provider":"windows_dpapi","validation":"valid","input_mode":"console"}),0
            elif args.auth_command=="status":
                payload,code=envelope("success",credential_status(SECRET_PATH)),0
            else:
                remove_key(SECRET_PATH)
                payload,code=envelope("success",{"configured":False,"provider":"windows_dpapi"}),0
        elif args.command=="_legacy": return run_legacy(args.script,args.args,load_config())
        elif args.command=="nexus":
            if args.nexus_command=="request": payload,code=handle_nexus_request(args)
            elif args.nexus_command=="batch":
                from .workflow import prepare_batch, collect_batch
                if args.batch_command=="prepare":
                    if not args.target.startswith("nexus:"): raise ToolError("Target must be nexus:<mod-id>",2)
                    cfg=load_config(); folder=Path(args.downloads_dir or cfg.get("download_directory") or default_browser_downloads_dir())
                    mod_id=int(args.target.split(":",1)[1]); metadata=[]; file_ids=list(args.file_id); dependency_plan=None
                    if not file_ids:
                        if not SECRET_PATH.exists(): raise ToolError("Nexus API key is required for dependency resolution",2)
                        from .nexus import resolve_batch, NexusError
                        key=dpapi_unprotect(SECRET_PATH.read_bytes()).decode("utf-8")
                        instance=Path(cfg.get("mo2_instance_path","")); installed=set()
                        for meta_file in (instance/"mods").glob("*/meta.ini") if (instance/"mods").is_dir() else []:
                            match=re.search(r"(?im)^modid\s*=\s*(\d+)",meta_file.read_text(encoding="utf-8-sig",errors="replace"))
                            if match:installed.add(match.group(1))
                        try:
                            dependency_plan=resolve_batch(mod_id,key,installed,set(args.include_optional))
                        finally:
                            key=""
                        if dependency_plan["unresolved_choices"]:
                            payload,code=envelope("review",dependency_plan,["Resolve dependency alternatives before opening download pages"]),1
                            emit(payload,as_json); return code
                        selected=[*dependency_plan["required"],*[x for x in dependency_plan["optional"] if str(x["mod_id"]) in set(args.include_optional)],dependency_plan["target"]]
                        for item in selected:
                            if item.get("file"):
                                meta=dict(item["file"]); meta["mod_id"]=item["mod_id"]; file_ids.append(int(meta["file_id"])); metadata.append(meta)
                    else:
                        for file_id in file_ids:
                            try: metadata.append(_nexus_file_metadata(mod_id,file_id))
                            except Exception: metadata.append({"file_id":file_id})
                    data=prepare_batch(mod_id,file_ids,folder,SESSIONS_DIR,not args.no_open_browser,metadata); data["dependency_plan"]=dependency_plan; atomic_path=SESSIONS_DIR/f"{data['id']}.json"; atomic_path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
                    payload,code=envelope("review" if dependency_plan and dependency_plan["optional"] and not args.include_optional else "success",data,["Optional dependencies require user confirmation"] if dependency_plan and dependency_plan["optional"] and not args.include_optional else []),1 if dependency_plan and dependency_plan["optional"] and not args.include_optional else 0
                else:
                    sp=SESSIONS_DIR/f"{args.session_id}.json"
                    if not sp.is_file(): raise ToolError("Download session was not found",2)
                    data=json.loads(sp.read_text(encoding="utf-8")) if args.batch_command=="status" else collect_batch(sp)
                    payload,code=envelope("success" if data.get("status") in ("collected","awaiting_downloads") else "review",data,[] if data.get("status")!="review" else ["Some downloads are missing or ambiguous"]),0 if data.get("status")!="review" else 1
            else:
                warnings=[]
                if args.nexus_command=="download":
                    values=list(args.values)
                    if values and values[0]=="download": warnings.append("Deprecated syntax: use nexus download <mod-id> <file-id>"); values=values[1:]
                    if len(values)!=2: raise ToolError("nexus download requires <mod-id> <file-id>",2)
                    script="nexus-download.py"; call=["download",*values]
                else:
                    mapping={"info":("nexus-mod-info.py",["full",str(args.mod_id)]),"deps":("nexus-deps-resolve.py",["check",str(args.mod_id)])}
                    script,call=mapping[args.nexus_command]
                if warnings and as_json:
                    captured=io.StringIO()
                    with contextlib.redirect_stdout(captured): code=run_legacy(script,call+["--json"],load_config())
                    try:
                        legacy=json.loads(captured.getvalue()); payload,code=envelope("success" if code==0 else "error",legacy,warnings=warnings),code
                        emit(payload,True); return code
                    except json.JSONDecodeError: raise ToolError("Legacy Nexus command returned invalid JSON",10)
                if warnings: print("WARNING: "+warnings[0],file=sys.stderr)
                return run_legacy(script,call+(["--json"] if as_json else []),load_config())
        elif args.command=="plan":
            if not args.target.startswith("nexus:"): raise ToolError("Only nexus:<mod-id> targets are supported",2)
            return run_legacy("nexus-deps-resolve.py",["plan",args.target.split(":",1)[1]] + (["--json"] if as_json else []),load_config())
        elif args.command=="archive":
            if args.archive_command=="inspect": return run_legacy("mod-install.py",["dry-run",args.archive]+(["--json"] if as_json else []),load_config())
            from .workflow import archive_source
            pp=Path(args.plan_id) if Path(args.plan_id).is_file() else PLANS_DIR/f"{args.plan_id}.json"
            if not pp.is_file():raise ToolError("Installation plan was not found",2)
            data=json.loads(pp.read_text(encoding="utf-8")); source=Path(data["archive"]); destination=Path(data.get("archive_directory", ""))
            if not source.is_file() or not destination:raise ToolError("Plan has no retryable source archive or destination",2)
            data["archive_result"]=archive_source(source,destination); data["status"]="complete"; write_manifest(pp,data); payload,code=envelope("success",data),0
        elif args.command=="root": payload,code=handle_root(args)
        elif args.command=="install":
            from .workflow import create_plan, apply_plan, fomod_options, fomod_preview, inspect_archive
            cfg=load_config()
            if args.install_command=="inspect":
                archive=Path(args.archive); seven_zip=find_7zip(cfg); layout=inspect_archive(archive,seven_zip); fomod=fomod_options(archive,seven_zip)
                preview=fomod_preview(archive,cfg,seven_zip,fomod) if fomod else None
                data={"archive":str(archive.resolve()),"layout":layout,"fomod":fomod,"recommended_resolution":preview,"recommended_selections":preview.get("recommended_selections") if preview else None,"status":"selection_required" if fomod else "ready"}
                payload,code=envelope("review" if fomod else "success",data,["Confirm FOMOD selections before planning"] if fomod else []),1 if fomod else 0
            elif args.install_command=="plan":
                selections=None
                if args.selections:
                    selections=json.loads(Path(args.selections).read_text(encoding="utf-8-sig"))
                if (args.modid is None)!=(args.file_id is None):raise ToolError("--modid and --file-id must be provided together",2)
                source_metadata=_nexus_file_metadata(args.modid,args.file_id) if args.modid is not None else None
                placement={"before_mod":args.before_mod,"after_mod":args.after_mod,"modlist_top":args.modlist_top,"modlist_bottom":args.modlist_bottom}
                data=create_plan(Path(args.archive),cfg,PLANS_DIR,args.name,selections,find_7zip(cfg),placement,source_metadata)
                shown=data if args.full_context else {k:v for k,v in data.items() if k!='modlist_context'}
                if not args.full_context:
                    context=data.get('modlist_context',{}); shown['modlist_summary']={'target_adjacency':data.get('placement'),'conflict_file_providers':context.get('conflict_file_providers',[]),'plugin_transition':(data.get('profile_transition') or {}).get('plugin_changes',{}),'manual_steps':data.get('layout',{}).get('manual_post_install_steps',[])}
                payload,code=envelope("success",shown),0
            elif args.install_command in ("apply","resume"):
                if not args.yes: payload,code=envelope("review",{"plan_id":args.plan_id},["Apply requires --yes after explicit confirmation"]),1
                else:
                    pp=Path(args.plan_id) if Path(args.plan_id).is_file() else PLANS_DIR/f"{args.plan_id}.json"
                    if not pp.is_file(): raise ToolError("Installation plan was not found",2)
                    placement={"before_mod":args.before_mod,"after_mod":args.after_mod,"modlist_top":args.modlist_top,"modlist_bottom":args.modlist_bottom}
                    placement={key:value for key,value in placement.items() if value}
                    data=apply_plan(pp,find_7zip(cfg),placement or None); payload,code=envelope("success" if data.get("status")=="complete" else "warning",data),0 if data.get("status")=="complete" else 1
            else:
                archive=Path(args.archive)
                if archive.is_file() and fomod_options(archive,find_7zip(cfg)) is not None: raise ToolError("Legacy installation is blocked for FOMOD archives; use install inspect/plan/apply",3)
                call=["dry-run" if args.dry_run else "install",args.archive,*args.args]+(["--json"] if as_json else [])
                if args.dry_run: return run_legacy("mod-install.py",call,cfg)
                raise ToolError("Legacy mutating installs are disabled; use install inspect, install plan, and install apply",3,
                                {"migration":["install inspect <archive>","install plan <archive>","install apply <plan-id> --yes --<placement>"]})
        elif args.command=="update":
            cfg=load_config()
            if Path(args.archive).is_file() and fomod_options(Path(args.archive),find_7zip(cfg)) is not None: raise ToolError("Legacy update is blocked for FOMOD archives; use install inspect/plan/apply",3)
            call=["dry-run" if args.dry_run else "install",args.archive,*(["--force"] if not args.dry_run else []),*args.args]+(["--json"] if as_json else [])
            if args.dry_run:return run_legacy("mod-install.py",call,cfg)
            raise ToolError("Legacy mutating updates are disabled; use install inspect, install plan, and install apply",3,
                            {"migration":["install inspect <archive>","install plan <archive> --name <existing-folder>","install apply <plan-id> --yes"]})
        elif args.command=="profile":
            cfg=load_config(); profile_name=args.profile or cfg.get("profile","")
            if not profile_name: raise ToolError("Profile name is required",2)
            if args.profile_command=="audit": return run_legacy("mo2-profile-audit.py",[profile_name]+(["--json"] if as_json else []),cfg)
            from .workflow import transform_profile_apply, mo2_running
            instance=Path(cfg.get("mo2_instance_path","")); profile=instance/"profiles"/profile_name
            paths={n:profile/n for n in ("modlist.txt","plugins.txt","loadorder.txt")}
            if not all(x.is_file() for x in paths.values()): raise ToolError("Profile files are missing",2)
            placement={"before_mod":args.before_mod,"after_mod":args.after_mod,"modlist_top":args.modlist_top,"modlist_bottom":args.modlist_bottom}
            raw={n:paths[n].read_bytes() for n in paths}; lines={n:paths[n].read_text(encoding="utf-8-sig").splitlines() for n in paths}
            result=transform_profile_apply(lines["modlist.txt"],lines["plugins.txt"],lines["loadorder.txt"],enable_mod=args.enable_mod,disable_mod=args.disable_mod,enable_plugin=args.enable_plugin,disable_plugin=args.disable_plugin,unregister_plugin=args.unregister_plugin,placement=placement)
            data={"profile":profile_name,"dry_run":args.dry_run,"changed":result["changed"],"plugin_states":result["plugin_states"]}
            if args.dry_run: payload,code=envelope("success",data),0
            else:
                running=mo2_running()
                if running and os.environ.get("MO2_PROFILE_UPDATE_ALLOW_RUNNING")!="1": raise ToolError("Close Mod Organizer 2 before changing a profile",3,{"processes":running})
                tx,manifest=snapshot_profile(cfg,profile_name)
                try:
                    for name,key in (("modlist.txt","modlist_lines"),("plugins.txt","plugins_lines"),("loadorder.txt","loadorder_lines")):
                        paths[name].write_text("\n".join(result[key])+"\n",encoding="utf-8-sig",newline="\n")
                    check=transform_profile_apply(result["modlist_lines"],result["plugins_lines"],result["loadorder_lines"])
                    finish_transaction(tx,manifest,"complete",0); data["backup_id"]=tx.name; payload,code=envelope("success",data),0
                except Exception:
                    for name,content in raw.items(): paths[name].write_bytes(content)
                    finish_transaction(tx,manifest,"rolled_back",5); raise
        elif args.command=="npc":
            from . import npc as npc_workflow
            cfg=load_config(); instance=Path(cfg.get("mo2_instance_path","")); profile=cfg.get("profile",""); game=Path(cfg.get("skyrim_game_path",""))/"Data"
            if args.npc_command=="scan":
                if not valid_instance(instance) or not profile or not game.is_dir(): raise ToolError("Configure a valid MO2 instance, profile, and Skyrim game path first",2)
                out=Path(args.output) if args.output else PLANS_DIR/f"npc-scan-{datetime.now():%Y%m%d-%H%M%S}.json"
                data=npc_workflow.run_scan(instance,profile,game,out,args.sidecar); out.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8",newline="\n")
                payload,code=envelope("success",{"scan":str(out),"summary":data["report"].get("Summary",{})},warnings=["BSA-only FaceGen is not indexed in this release"]),0
            elif args.npc_command=="plan":
                scan=json.loads(Path(args.scan).read_text(encoding="utf-8-sig")); data=npc_workflow.make_plan(scan)
                out=Path(args.output) if args.output else PLANS_DIR/f"{data['plan_id']}.json"; out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8",newline="\n")
                unresolved=sum(x["status"]=="decision_required" for x in data["items"]); payload,code=envelope("review" if unresolved else "success",{"plan":str(out),"plan_id":data["plan_id"],"decision_required":unresolved,"items":data["items"]},["Resolve candidate IDs, then confirm once before apply"] if unresolved else []),1 if unresolved else 0
            elif args.npc_command=="decide":
                pp=Path(args.plan); data=json.loads(pp.read_text(encoding="utf-8-sig")); decision=json.loads(Path(args.decisions).read_text(encoding="utf-8-sig")); data=npc_workflow.apply_decisions(data,decision)
                out=Path(args.output) if args.output else PLANS_DIR/f"{data['plan_id']}-decided.json"; out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8",newline="\n"); payload,code=envelope("success",{"plan":str(out),"plan_id":data["plan_id"]}),0
            elif args.npc_command=="apply":
                data=json.loads(Path(args.plan).read_text(encoding="utf-8-sig")); result=npc_workflow.apply_plan(data,SESSIONS_DIR,_game_processes_running,args.yes); payload,code=envelope("success",result),0
            else:
                data=json.loads(Path(args.plan).read_text(encoding="utf-8-sig")); result=npc_workflow.verify(data); payload,code=envelope("success" if result["ok"] else "error",result,errors=[] if result["ok"] else ["NPC output verification failed"]),0 if result["ok"] else 2
        elif args.command=="backup": payload,code=handle_backup(args)
        else: raise ToolError("Unsupported command",2)
        emit(payload,as_json); return code
    except AuthError as exc:
        emit(envelope("error",{"category":exc.category},errors=[str(exc)]),as_json); return exc.code
    except (ToolError, WorkflowError) as exc:
        emit(envelope("error",exc.details,errors=[str(exc)]),as_json); return exc.code
    except KeyboardInterrupt:
        emit(envelope("error",errors=["Operation cancelled"]),as_json); return 2
    except Exception as exc:
        emit(envelope("error",errors=[f"{type(exc).__name__}: {exc}"]),as_json); return 10

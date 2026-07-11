from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from typing import Any

NPC_SCHEMA_VERSION = 1
OUTPUT_MOD = "[角色美化] Agent NPC Conflict Resolution"
OUTPUT_PLUGIN = "Agent_NPC_ConflictResolution.esp"
PROFILE_FILES = ("modlist.txt", "plugins.txt", "loadorder.txt")

class NpcError(Exception):
    pass

def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def _snapshot(instance: Path, profile: str) -> dict[str,str]:
    root=instance/"profiles"/profile
    result={}
    for name in PROFILE_FILES:
        path=root/name
        if not path.is_file(): raise NpcError(f"Missing profile file: {path}")
        result[name]=_sha(path)
    return result

def find_sidecar(explicit: str|None=None) -> Path:
    candidates=[explicit, os.environ.get("MO2_NPC_PATCHER"), Path(__file__).resolve().parent/"bin"/"npc-agent-patcher.exe",
                Path(__file__).resolve().parents[3]/"npc-agent-patcher"/"bin"/"Release"/"net8.0"/"win-x64"/"publish"/"npc-agent-patcher.exe"]
    for value in candidates:
        if value and Path(value).is_file(): return Path(value).resolve()
    raise NpcError("NPC sidecar not found; build/package npc-agent-patcher.exe or set MO2_NPC_PATCHER")

def _protocol(exe: Path, request: dict[str,Any], work: Path) -> dict[str,Any]:
    work.mkdir(parents=True,exist_ok=True)
    request_path=work/"sidecar-request.json"; response_path=work/"sidecar-response.json"
    request_path.write_text(json.dumps(request,ensure_ascii=False,indent=2),encoding="utf-8",newline="\n")
    try:
        proc=subprocess.run([str(exe),"protocol","--request",str(request_path),"--response",str(response_path)],capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=120)
    except subprocess.TimeoutExpired as exc:
        raise NpcError("NPC sidecar timed out after 120 seconds") from exc
    response=json.loads(response_path.read_text(encoding="utf-8-sig")) if response_path.is_file() else None
    if proc.returncode or response is None:
        detail=(response or {}).get("errors") or proc.stderr or proc.stdout or "no structured response"
        raise NpcError(f"NPC protocol failed ({proc.returncode}): {detail}")
    if response.get("protocol_version")!=1 or response.get("status")!="success":
        raise NpcError(f"NPC sidecar returned an incompatible or failed response: {response.get('errors') or []}")
    return response

def run_scan(instance: Path, profile: str, game_data: Path, report: Path, sidecar: str|None=None) -> dict[str,Any]:
    exe=find_sidecar(sidecar); report.parent.mkdir(parents=True,exist_ok=True)
    request={"schema_version":1,"operation":"scan","request_id":f"scan-{datetime.now():%Y%m%d%H%M%S}","instance":str(instance),"profile":profile,"game_data":str(game_data),"report_path":str(report)}
    response=_protocol(exe,request,report.parent/"protocol")
    data=response["data"]["report"]
    report.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8",newline="\n")
    return {"schema_version":NPC_SCHEMA_VERSION,"kind":"npc_scan","created_at":datetime.now(timezone.utc).isoformat(),
            "instance":str(instance.resolve()),"profile":profile,"game_data":str(game_data.resolve()),
            "profile_snapshot":_snapshot(instance,profile),"sidecar":str(exe),"sidecar_exit_code":0,"protocol_version":response["protocol_version"],"report":data}

def _candidate_id(npc_key: str, candidate: dict[str,Any]) -> str:
    raw="\0".join([npc_key,str(candidate.get("SourceMod","")),str(candidate.get("SourcePlugin","")),str(candidate.get("MeshRelativePath","")),str(candidate.get("TintRelativePath",""))])
    return "npcface:"+hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

def make_plan(scan: dict[str,Any]) -> dict[str,Any]:
    records=scan.get("report",{}).get("WinningNpcRecords") or []
    items=[]
    for record in records:
        npc_key=f"{record['BasePlugin']}:{record['FaceGenFormId'].upper().zfill(8)}"
        candidates=[]
        for source in record.get("FaceGenCandidates") or []:
            if source.get("HasMesh") and source.get("HasTint"):
                candidate={**source,"candidate_id":_candidate_id(npc_key,source)}
                mod_root=Path(scan["instance"])/"mods"/source["SourceMod"]
                mesh=mod_root/source["MeshRelativePath"] if source.get("MeshRelativePath") else None
                tint=mod_root/source["TintRelativePath"] if source.get("TintRelativePath") else None
                candidate["mesh_sha256"]=_sha(mesh) if mesh and mesh.is_file() else None
                candidate["tint_sha256"]=_sha(tint) if tint and tint.is_file() else None
                candidate["eligible"]=bool(candidate["mesh_sha256"] and candidate["tint_sha256"] and candidate.get("SourcePlugin"))
                candidates.append(candidate)
        action=(record.get("PatchPlan") or {}).get("Action")
        requires_patch=action=="patch-default-from-winning-face-from-candidate"
        eligible=[x for x in candidates if x.get("eligible")]
        selected=eligible[0]["candidate_id"] if len(eligible)==1 else None
        status="ready" if selected else ("decision_required" if eligible and requires_patch else "not_actionable")
        items.append({"npc_key":npc_key,"form_key":record.get("FormKey"),"editor_id":record.get("EditorId"),"name":record.get("Name"),
                      "status":status,"requires_patch":requires_patch,"appearance_candidate_id":selected,
                      "name_source_id":"current-readable-winner","candidates":candidates,"legacy_patch_plan":record.get("PatchPlan")})
    body={"schema_version":NPC_SCHEMA_VERSION,"kind":"npc_plan","created_at":datetime.now(timezone.utc).isoformat(),
          "instance":scan["instance"],"profile":scan["profile"],"game_data":scan["game_data"],"profile_snapshot":scan["profile_snapshot"],
          "sidecar":scan["sidecar"],"items":items}
    canonical=json.dumps(body,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")
    body["plan_id"]="npc-plan-"+hashlib.sha256(canonical).hexdigest()[:20]
    return body

def apply_decisions(plan: dict[str,Any], decision: dict[str,Any]) -> dict[str,Any]:
    if decision.get("schema_version")!=NPC_SCHEMA_VERSION or decision.get("plan_id")!=plan.get("plan_id"):
        raise NpcError("Decision schema or plan_id does not match")
    by_key={x["npc_key"]:x for x in plan["items"]}
    for selected in decision.get("decisions",[]):
        item=by_key.get(selected.get("npc_key"))
        if not item: raise NpcError(f"Unknown NPC key: {selected.get('npc_key')}")
        ids={x["candidate_id"] for x in item["candidates"]}
        if selected.get("appearance_candidate_id") not in ids: raise NpcError(f"Candidate is not in plan: {selected.get('appearance_candidate_id')}")
        item["appearance_candidate_id"]=selected["appearance_candidate_id"]; item["name_source_id"]=selected.get("name_source_id","current-readable-winner"); item["status"]="ready"
    return plan

def _write_profile(path: Path, entry: str, enabled_prefix: str="") -> None:
    raw=path.read_text(encoding="utf-8-sig"); lines=raw.splitlines(); key=entry.lower().lstrip("+*-")
    lines=[x for x in lines if x.strip().lower().lstrip("+*-")!=key]
    insert=len(lines)
    if path.name=="modlist.txt":
        for i,line in enumerate(lines):
            if line.startswith("*DLC:") or line.startswith("*Creation Club:"): insert=i; break
    lines.insert(insert,enabled_prefix+entry)
    path.write_text("\n".join(lines)+"\n",encoding="utf-8-sig",newline="\n")

def apply_plan(plan: dict[str,Any], sessions: Path, process_check, yes: bool) -> dict[str,Any]:
    if not yes: raise NpcError("NPC apply requires explicit confirmation (--yes)")
    unresolved=[x["npc_key"] for x in plan["items"] if x["requires_patch"] and x["status"]=="decision_required"]
    if unresolved: raise NpcError("NPC plan still has unresolved decisions: "+", ".join(unresolved[:10]))
    instance=Path(plan["instance"]); profile=plan["profile"]
    running=process_check()
    if running: raise NpcError("Close MO2/game/modding tools before applying: "+", ".join(running))
    if _snapshot(instance,profile)!=plan["profile_snapshot"]: raise NpcError("Profile changed after planning; run npc scan and npc plan again")
    tx=sessions/(datetime.now().strftime("%Y%m%d-%H%M%S")+"-npc"); tx.mkdir(parents=True)
    pdir=instance/"profiles"/profile; output=instance/"mods"/OUTPUT_MOD; backup=tx/"output-mod"
    for name in PROFILE_FILES: shutil.copy2(pdir/name,tx/name)
    if output.exists(): shutil.copytree(output,backup)
    stage=Path(tempfile.mkdtemp(prefix="mo2-npc-stage-")); staged=stage/OUTPUT_MOD
    try:
        decisions=[]
        for item in plan["items"]:
            selected=item.get("appearance_candidate_id")
            if not selected: continue
            candidate=next((x for x in item["candidates"] if x["candidate_id"]==selected),None)
            if candidate is None or not candidate.get("eligible"): raise NpcError(f"Selected candidate is missing or ineligible: {selected}")
            source_root=instance/"mods"/candidate["SourceMod"]
            mesh=source_root/candidate["MeshRelativePath"]; tint=source_root/candidate["TintRelativePath"]
            if not mesh.is_file() or not tint.is_file() or _sha(mesh)!=candidate.get("mesh_sha256") or _sha(tint)!=candidate.get("tint_sha256"):
                raise NpcError(f"Selected FaceGen source changed after planning: {item['npc_key']}")
            decisions.append({"NpcKey":item["npc_key"],"AppearanceSourceMod":candidate["SourceMod"],"AppearancePlugin":candidate["SourcePlugin"],"NamePlugin":None})
        decision_path=tx/"decisions.json"
        decision_path.write_text(json.dumps({"SchemaVersion":1,"Decisions":decisions},ensure_ascii=False,indent=2),encoding="utf-8",newline="\n")
        call=[plan["sidecar"],"--instance",str(instance),"--profile",profile,"--game-data",plan["game_data"],"--report",str(tx/"apply-report.json"),
              "--winning-npcs","999999","--ignore-mod",OUTPUT_MOD,"--ignore-plugin",OUTPUT_PLUGIN,"--generate-mod",str(staged),"--decisions",str(decision_path)]
        request={"schema_version":1,"operation":"generate","request_id":plan["plan_id"],"instance":str(instance),"profile":profile,"game_data":plan["game_data"],"report_path":str(tx/"apply-report.json"),"staging_output":str(staged),"decisions_path":str(decision_path)}
        protocol_response=_protocol(Path(plan["sidecar"]),request,tx/"protocol-generate")
        if not (staged/OUTPUT_PLUGIN).is_file(): raise NpcError("Sidecar protocol did not generate the output plugin")
        if output.exists(): shutil.rmtree(output)
        shutil.move(str(staged),str(output))
        _write_profile(pdir/"modlist.txt",OUTPUT_MOD,"+"); _write_profile(pdir/"plugins.txt",OUTPUT_PLUGIN,"*"); _write_profile(pdir/"loadorder.txt",OUTPUT_PLUGIN)
        manifest={"schema_version":1,"id":tx.name,"operation":"npc_apply","status":"complete","plan_id":plan["plan_id"],
                  "files":[{"kind":"file","destination":str(pdir/name),"backup":name} for name in PROFILE_FILES] +
                          ([{"kind":"directory","destination":str(output),"backup":"output-mod"}] if backup.exists() else [{"kind":"absent","destination":str(output)}]),
                  "output_mod":str(output)}
        (tx/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8",newline="\n")
        return {"status":"complete","backup_id":tx.name,"output_mod":str(output),"plugin":str(output/OUTPUT_PLUGIN),"verification":verify(plan)}
    except Exception:
        for name in PROFILE_FILES: shutil.copy2(tx/name,pdir/name)
        if output.exists(): shutil.rmtree(output)
        if backup.exists(): shutil.copytree(backup,output)
        raise
    finally: shutil.rmtree(stage,ignore_errors=True)

def verify(plan: dict[str,Any]) -> dict[str,Any]:
    instance=Path(plan["instance"]); profile=plan["profile"]; output=instance/"mods"/OUTPUT_MOD
    pdir=instance/"profiles"/profile
    checks={"output_plugin_exists":(output/OUTPUT_PLUGIN).is_file(),
            "mod_enabled":any(x.strip()=="+"+OUTPUT_MOD for x in (pdir/"modlist.txt").read_text(encoding="utf-8-sig").splitlines()),
            "plugin_enabled":any(x.strip()=="*"+OUTPUT_PLUGIN for x in (pdir/"plugins.txt").read_text(encoding="utf-8-sig").splitlines()),
            "plugin_in_loadorder":any(x.strip()==OUTPUT_PLUGIN for x in (pdir/"loadorder.txt").read_text(encoding="utf-8-sig").splitlines())}
    npc_results=[]
    for item in plan.get("items",[]):
        selected=item.get("appearance_candidate_id")
        candidate=next((x for x in item.get("candidates",[]) if x.get("candidate_id")==selected),None)
        if not candidate: continue
        files={}
        for key in ("MeshRelativePath","TintRelativePath"):
            output_file=output/candidate[key] if candidate.get(key) else None
            files[key]={"exists":bool(output_file and output_file.is_file()),"matches_source":bool(output_file and output_file.is_file() and _sha(output_file)==candidate.get("mesh_sha256" if key=="MeshRelativePath" else "tint_sha256"))}
        ok=all(v["exists"] and v["matches_source"] for v in files.values())
        npc_results.append({"npc_key":item["npc_key"],"candidate_id":selected,"ok":ok,"files":files})
    checks["selected_facegen_hashes_match"]=all(x["ok"] for x in npc_results)
    return {"ok":all(checks.values()),"checks":checks,"npcs":npc_results,"recommendations":["建议操作：进入游戏抽查目标 NPC；如有自己的检查流程，无需完全参照此步骤。"]}

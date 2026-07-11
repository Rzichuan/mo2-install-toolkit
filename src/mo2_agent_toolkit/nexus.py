from __future__ import annotations
import json, urllib.error, urllib.request
from typing import Any

class NexusError(Exception): pass
V1='https://api.nexusmods.com/v1/games/skyrimspecialedition'
V3='https://api.nexusmods.com/v3'

def _get(url:str,key:str)->dict[str,Any]:
    req=urllib.request.Request(url,headers={'apikey':key,'Accept':'application/json','User-Agent':'MO2AgentToolkit/0.3'})
    try:
        with urllib.request.urlopen(req,timeout=30) as response:return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:raise NexusError(f'Nexus request failed with HTTP {exc.code}') from exc
    except (urllib.error.URLError,TimeoutError) as exc:raise NexusError(f'Nexus request failed: {getattr(exc,"reason",exc)}') from exc

def files(mod_id:int,key:str)->list[dict[str,Any]]:
    return _get(f'{V1}/mods/{mod_id}/files.json',key).get('files',[])

def preferred_file(mod_id:int,key:str)->dict[str,Any]|None:
    all_files=files(mod_id,key)
    available=[x for x in all_files if not x.get('is_deleted') and int(x.get('category_id') or 0) == 1]
    if not available:available=[x for x in all_files if not x.get('is_deleted')]
    if not available:return None
    return max(available,key=lambda x:(int(x.get('uploaded_timestamp') or 0),int(x.get('file_id') or 0)))

def materialized_dependencies(mod_id:int,key:str)->list[dict[str,Any]]|None:
    try:
        mod=_get(f'{V3}/games/skyrimspecialedition/mods/{mod_id}',key); internal=mod['data']['id']
        mod_files=_get(f'{V3}/mods/{internal}/files',key)['data']['mod_files']
        active=[x for x in mod_files if x.get('is_active')]
        for mf in active:
            versions=_get(f"{V3}/mod-files/{mf['id']}/versions",key)['data']['versions']
            for version in versions:
                if version.get('category') not in ('main','optional'):continue
                result=_get(f"{V3}/mod-file-versions/{version['id']}/dependencies/materialized",key)
                return result.get('dependencies',[])
        return []
    except (KeyError,IndexError,NexusError):return None

def resolve_batch(mod_id:int,key:str,installed_ids:set[str],include_optional:set[str]|None=None)->dict[str,Any]:
    include_optional=include_optional or set(); required=[]; optional=[]; satisfied=[]; choices=[]; visited=set()
    def walk(current:int,depth:int=0)->None:
        sid=str(current)
        if sid in visited:return
        visited.add(sid); deps=materialized_dependencies(current,key)
        if deps is None:
            choices.append({'mod_id':current,'reason':'dependency metadata unavailable'}); return
        for index,definition in enumerate(deps):
            candidates=definition.get('candidate_mod_files') or []
            ids=[str(c.get('mod',{}).get('game_scoped_id','')) for c in candidates if c.get('mod',{}).get('game_scoped_id')]
            installed=next((x for x in ids if x in installed_ids),None)
            if installed:satisfied.append({'mod_id':int(installed),'source_mod_id':current}); continue
            is_optional=bool(definition.get('is_optional') or str(definition.get('type','')).casefold()=='optional')
            if len(ids)!=1:
                choices.append({'source_mod_id':current,'group':index,'optional':is_optional,'candidates':[{'mod_id':int(c['mod']['game_scoped_id']),'name':c['mod'].get('name','')} for c in candidates]}); continue
            dep_id=int(ids[0]); item={'mod_id':dep_id,'name':candidates[0]['mod'].get('name',''),'source_mod_id':current,'depth':depth}
            bucket=optional if is_optional else required
            if not any(x['mod_id']==dep_id for x in bucket):bucket.append(item)
            if not is_optional or str(dep_id) in include_optional:walk(dep_id,depth+1)
    walk(mod_id)
    ordered=sorted(required,key=lambda x:x['depth'],reverse=True)
    target={'mod_id':mod_id,'name':'target','depth':-1}
    if not choices:
        for item in [*ordered,*[x for x in optional if str(x['mod_id']) in include_optional],target]:
            meta=preferred_file(item['mod_id'],key)
            if meta:item['file']=meta
            else:choices.append({'mod_id':item['mod_id'],'reason':'no downloadable file found'})
    return {'target_mod_id':mod_id,'target':target,'required':ordered,'optional':optional,'already_satisfied':satisfied,'unresolved_choices':choices}

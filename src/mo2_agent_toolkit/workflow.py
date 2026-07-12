from __future__ import annotations

import hashlib, json, os, re, shutil, subprocess, tempfile, uuid, zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from .metadata import MetadataError, prepare_meta_ini, validate_meta_ini

PARTIAL_SUFFIXES={'.part','.crdownload','.partial','.tmp'}
ARCHIVE_SUFFIXES={'.zip','.7z','.rar'}
PLUGIN_SUFFIXES={'.esp','.esm','.esl'}
GAME_FILE_SUFFIXES=PLUGIN_SUFFIXES|{'.bsa'}
DATA_DIRECTORIES={
    'meshes','textures','scripts','sound','interface','skse','calientetools',
    'nemesis_engine','pandora_engine','music','video','seq','dialogueviews',
    'mcm','platform','strings','grass','lodsettings','materials','shadersfx',
    'source','tools'
}
IGNORED_ARCHIVE_DIRECTORIES={'__macosx'}
_METADATA_NAMES={'meta.ini','desktop.ini','thumbs.db','manifest.json','install.json','info.json'}
_METADATA_PREFIXES=('readme','read me','changelog','change log','license','credits','description','checksum')
_METADATA_SUFFIXES={'.txt','.md','.rtf','.pdf','.jpg','.jpeg','.png','.gif','.webp','.bmp','.crc','.sfv','.sha1','.sha256','.sha512'}
ROOT_GAME_FILES={'d3d11.dll','d3dcompiler_46e.dll','d3dcompiler_47.dll','dxgi.dll','enbseries.ini','enblocal.ini','skse64_loader.exe','skse64_steam_loader.dll'}

class WorkflowError(Exception):
    def __init__(self,message:str,code:int=2,details:Any=None): super().__init__(message); self.code=code; self.details=details

def atomic_json(path:Path,data:dict[str,Any])->None:
    path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); os.replace(tmp,path)

def sha256(path:Path)->str:
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()

def mo2_running()->list[str]:
    if os.name!='nt': return []
    try: out=subprocess.run(['tasklist','/FO','CSV','/NH'],capture_output=True,text=True,timeout=10).stdout
    except Exception: return []
    return sorted({name for name in ('ModOrganizer.exe','ModOrganizer2.exe') if name.casefold() in out.casefold()})

def _safe_member(name:str)->Path:
    normalized=name.replace('\\','/').strip('/')
    p=Path(normalized)
    if not normalized or p.is_absolute() or re.match(r'^[A-Za-z]:',normalized) or normalized.startswith('//') or '..' in p.parts:
        raise WorkflowError(f'Unsafe archive path: {name}',3)
    return p

def _list_7z(archive:Path,seven_zip:str)->list[dict[str,str]]:
    r=subprocess.run([seven_zip,'l',str(archive),'-slt'],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=120)
    if r.returncode: raise WorkflowError('Archive listing failed',5,{'stderr':r.stderr[-2000:]})
    entries=[]; current={}
    for raw in r.stdout.splitlines():
        line=raw.strip()
        if not line:
            if current.get('Path'): entries.append(current)
            current={}; continue
        if ' = ' in line:
            key,value=line.split(' = ',1); current[key]=value
    if current.get('Path'):entries.append(current)
    # 7z -slt includes the archive itself as the first record.
    return [e for e in entries if not (Path(e.get('Path','')).name == archive.name and e.get('Type'))]

def archive_members(archive:Path,seven_zip:str|None)->list[dict[str,Any]]:
    if archive.suffix.casefold()=='.zip':
        with zipfile.ZipFile(archive) as z:
            result=[]
            for info in z.infolist():
                path=_safe_member(info.filename)
                mode=(info.external_attr >> 16) & 0xFFFF
                if mode & 0o170000 == 0o120000: raise WorkflowError(f'Archive link is not allowed: {info.filename}',3)
                result.append({'path':path.as_posix(),'size':info.file_size,'packed_size':info.compress_size,'directory':info.is_dir()})
            return result
    if not seven_zip: raise WorkflowError('7-Zip is required for this archive format',5)
    result=[]
    for entry in _list_7z(archive,seven_zip):
        path=_safe_member(entry['Path']); attrs=entry.get('Attributes','')
        if 'L' in attrs or entry.get('Symbolic Link'): raise WorkflowError(f"Archive link is not allowed: {entry['Path']}",3)
        result.append({'path':path.as_posix(),'size':int(entry.get('Size','0') or 0),'packed_size':int(entry.get('Packed Size','0') or 0),'directory':'D' in attrs})
    return result

def _member_values(entry:dict[str,Any])->tuple[str,bool]:
    raw=str(entry.get('path') or entry.get('Path') or '').replace('\\','/').strip('/')
    attrs=str(entry.get('Attributes','')).upper()
    directory=bool(entry.get('directory',False) or entry.get('Folder')=='+' or raw.endswith('/') or attrs.startswith('D'))
    return raw,directory

def _is_metadata_file(name:str)->bool:
    lowered=Path(name).name.casefold()
    return (lowered in _METADATA_NAMES or lowered.startswith(_METADATA_PREFIXES)
            or Path(lowered).suffix in _METADATA_SUFFIXES)

def _valid_effective_path(path:str)->bool:
    parts=[part for part in path.replace('\\','/').strip('/').split('/') if part]
    if not parts:return False
    return (Path(parts[-1]).suffix.casefold() in GAME_FILE_SUFFIXES
            or parts[0].casefold() in DATA_DIRECTORIES)

def _manual_steps(paths:list[str])->list[dict[str,Any]]:
    normalized=[p.replace('\\','/').casefold().strip('/') for p in paths]
    features={
        'bodyslide':any('/calientetools/bodyslide/slidersets/' in f'/{p}/' or '/calientetools/bodyslide/shapedata/' in f'/{p}/' for p in normalized),
        'preset':any('/calientetools/bodyslide/sliderpresets/' in f'/{p}/' for p in normalized),
        'pandora':any('pandora_engine' in p for p in normalized),
        'nemesis':any('nemesis_engine' in p for p in normalized),
        'fnis':any('generatefnis_for_users' in p or 'fnis_' in Path(p).name for p in normalized),
        'behavior':any('/behaviors/' in f'/{p}/' or p.endswith('.hkx') for p in normalized),
    }
    result=[]
    if features['bodyslide']:
        result.append({'tool':'BodySlide','level':'recommended','advisory':True,'reason':'Archive contains BodySlide SliderSets or ShapeData','steps':[]})
    elif features['preset']:
        result.append({'tool':'BodySlide','level':'informational','advisory':True,'reason':'Archive contains a BodySlide preset only','steps':[]})
    if features['pandora']:
        result.append({'tool':'Pandora','level':'recommended','advisory':True,'reason':'Archive contains a Pandora_Engine patch','steps':[]})
    if features['nemesis']:
        result.append({'tool':'Nemesis','level':'recommended','advisory':True,'reason':'Archive contains a Nemesis_Engine patch','steps':[]})
    if features['fnis']:
        result.append({'tool':'FNIS','level':'review','advisory':True,'reason':'Archive contains FNIS-specific content','steps':[]})
    if features['behavior'] and not any(features[x] for x in ('pandora','nemesis','fnis')):
        result.append({'tool':'Behavior generator','level':'review','advisory':True,'reason':'Archive contains prebuilt behavior files but no recognized generator patch','steps':[]})
    return result

def detect_layout(entries:list[dict[str,Any]])->dict[str,Any]:
    """Return the canonical archive/directory layout used by inspect, plan, and apply."""
    normalized=[_member_values(entry) for entry in entries]
    normalized=[item for item in normalized if item[0]]
    file_paths=[path for path,is_dir in normalized if not is_dir]
    top_dirs={path.split('/',1)[0] for path,is_dir in normalized if '/' in path or (is_dir and path)}
    top_dirs={name for name in top_dirs if name.casefold() not in IGNORED_ARCHIVE_DIRECTORIES}
    root_files=[path for path,is_dir in normalized if not is_dir and '/' not in path]
    candidates=[name for name in top_dirs if name.casefold() not in DATA_DIRECTORIES]

    def child_paths(candidate:str)->list[str]:
        prefix=candidate.casefold()+'/'
        return [path[len(candidate)+1:] for path in file_paths if path.casefold().startswith(prefix)]

    qualified=sorted((name for name in candidates if any(_valid_effective_path(p) for p in child_paths(name))),key=str.casefold)
    suspected=sorted(candidates,key=str.casefold)
    root_blockers=[name for name in root_files if not _is_metadata_file(name)]
    root_data_dirs=[name for name in top_dirs if name.casefold() in DATA_DIRECTORIES]
    nesting_root=qualified[0] if len(candidates)==1 and len(qualified)==1 and not root_blockers and not root_data_dirs else None
    flatten=nesting_root is not None
    effective_files=child_paths(nesting_root) if nesting_root else list(file_paths)
    if flatten:
        effective_files.extend(name for name in root_files if _is_metadata_file(name))
    effective_entries=sorted({path.split('/',1)[0] for path in effective_files},key=str.casefold)
    lowered=[path.casefold() for path in effective_files]
    has_fomod=any(path.endswith('fomod/moduleconfig.xml') or '/fomod/moduleconfig.xml' in '/'+path for path in (p.casefold() for p in file_paths))
    has_root_files=any(Path(path).name.casefold() in ROOT_GAME_FILES or re.match(r'^skse64_1_[0-9_]+\.dll$',Path(path).name.casefold()) or path.startswith(('enbcache/','enbseries/')) for path in lowered)
    plugin_count=sum(Path(path).suffix.casefold() in PLUGIN_SUFFIXES for path in effective_files)
    has_data=any(_valid_effective_path(path) for path in effective_files)
    steps=_manual_steps(effective_files)
    features={
        'has_bodyslide_project':any(x['tool']=='BodySlide' and x['level']=='recommended' for x in steps),
        'has_bodyslide_preset':any(x['tool']=='BodySlide' and x['level']=='informational' for x in steps),
        'has_pandora_patch':any(x['tool']=='Pandora' for x in steps),
        'has_nemesis_patch':any(x['tool']=='Nemesis' for x in steps),
        'has_fnis_content':any(x['tool']=='FNIS' for x in steps),
        'has_prebuilt_behavior':any('/behaviors/' in f'/{p.casefold()}/' or p.casefold().endswith('.hkx') for p in effective_files),
    }
    return {
        'type':'fomod' if has_fomod else 'root' if has_root_files else 'mo2' if has_data else 'asset',
        'nesting_root':nesting_root,'flatten':flatten,'has_nesting':flatten,
        'effective_root_entries':effective_entries,'suspected_wrapper_directories':suspected,
        'root_entries':sorted({path.split('/',1)[0] for path,_ in normalized},key=str.casefold),
        'has_fomod':has_fomod,'has_root_files':has_root_files,'has_data_files':has_data,
        'plugin_count':plugin_count,'file_count':len(file_paths),
        'has_behavior':features['has_prebuilt_behavior'],'has_nemesis':features['has_nemesis_patch'] or features['has_pandora_patch'],
        **features,'manual_post_install_steps':steps,
        '_effective_files':effective_files,
    }

def inspect_archive(archive:Path,seven_zip:str|None=None)->dict[str,Any]:
    archive=archive.expanduser().resolve()
    if not archive.is_file():raise WorkflowError('Archive does not exist',2)
    layout=detect_layout(archive_members(archive,seven_zip))
    return {key:value for key,value in layout.items() if not key.startswith('_')}

def _directory_members(root:Path)->list[dict[str,Any]]:
    return [{'path':item.relative_to(root).as_posix(),'directory':item.is_dir()} for item in root.rglob('*')]

def _copy_entry(source:Path,destination:Path)->None:
    if source.is_dir():shutil.copytree(source,destination,dirs_exist_ok=True)
    else:destination.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(source,destination)

def _stage_effective_root(extracted:Path,staged:Path,layout:dict[str,Any])->None:
    staged.mkdir(parents=True,exist_ok=True)
    source=extracted/Path(layout['nesting_root']) if layout.get('flatten') else extracted
    # Extraction and staging are on the same volume. Rename top-level entries instead
    # of recursively copying them: this avoids creating a second set of deep paths,
    # which can exceed MAX_PATH on otherwise valid Windows MO2 archives.
    for item in list(source.iterdir()):
        if item.name.casefold() not in IGNORED_ARCHIVE_DIRECTORIES:shutil.move(item,staged/item.name)
    if layout.get('flatten'):
        for item in list(extracted.iterdir()):
            if item.is_file() and _is_metadata_file(item.name) and not (staged/item.name).exists():shutil.move(item,staged/item.name)

def validate_staged_mod(staged:Path)->dict[str,Any]:
    layout=detect_layout(_directory_members(staged))
    root_entries=sorted((item.name for item in staged.iterdir()),key=str.casefold)
    if not layout['has_data_files']:
        suspected=layout.get('suspected_wrapper_directories',[])
        suggestions=[str(staged/name) for name in suspected] or [str(staged)]
        raise WorkflowError('Staged mod root contains no valid game data; installation was stopped before commit',2,{
            'current_root_entries':root_entries,
            'suspected_wrapper_directories':suspected,
            'suggested_paths_to_check':suggestions,
        })
    plugins=sorted({item.name for item in staged.rglob('*') if item.is_file() and item.suffix.casefold() in PLUGIN_SUFFIXES},key=str.casefold)
    return {'layout':{key:value for key,value in layout.items() if not key.startswith('_')},'root_entries':root_entries,'plugins':plugins}

def _validate_extracted(dest:Path)->None:
    base=dest.resolve()
    for item in dest.rglob('*'):
        if item.is_symlink(): raise WorkflowError(f'Extracted link is not allowed: {item}',3)
        resolved=item.resolve()
        if base != resolved and base not in resolved.parents: raise WorkflowError(f'Extracted path escaped staging: {item}',3)
        if os.name=='nt' and item.exists() and item.stat().st_file_attributes & 0x400: raise WorkflowError(f'Extracted reparse point is not allowed: {item}',3)

def _extract(archive:Path,dest:Path,seven_zip:str|None)->None:
    members=archive_members(archive,seven_zip)
    total=sum(x['size'] for x in members); packed=max(1,archive.stat().st_size)
    if len(members)>250000 or total>100*1024**3 or total/packed>1000:
        raise WorkflowError('Archive exceeds safe extraction limits',3,{'entries':len(members),'unpacked_bytes':total})
    if archive.suffix.casefold()=='.zip':
        with zipfile.ZipFile(archive) as z:z.extractall(dest)
    else:
        r=subprocess.run([seven_zip,'x',str(archive),f'-o{dest}','-y'],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=300)
        if r.returncode: raise WorkflowError('Archive extraction failed',5,{'stderr':r.stderr[-2000:]})
    _validate_extracted(dest)

def _read_fomod_root(archive:Path,seven_zip:str|None)->tuple[ET.Element|None,str|None]:
    members=archive_members(archive,seven_zip)
    match=next((m['path'] for m in members if m['path'].casefold().endswith('fomod/moduleconfig.xml')),None)
    if not match:return None,None
    with tempfile.TemporaryDirectory(prefix='mo2-fomod-') as td:
        root=Path(td); _extract(archive,root,seven_zip); source=root/Path(match)
        try:return ET.fromstring(source.read_bytes()),match
        except ET.ParseError as exc:raise WorkflowError(f'Invalid FOMOD XML: {exc}',2)

def _dependency(node:ET.Element|None)->dict[str,Any]|None:
    if node is None:return None
    tag=node.tag.rsplit('}',1)[-1]
    if tag in ('dependencies','moduleDependencies'):
        return {'kind':'group','operator':node.get('operator','And'),'children':[x for child in node if (x:=_dependency(child))]}
    if tag=='fileDependency':return {'kind':'file','file':node.get('file',''),'state':node.get('state','Active')}
    if tag=='flagDependency':return {'kind':'flag','flag':node.get('flag',''),'value':node.get('value','')}
    if tag=='gameDependency':return {'kind':'game','version':node.get('version','')}
    if tag=='fommDependency':return {'kind':'unsupported','tag':tag}
    return {'kind':'unsupported','tag':tag}

def fomod_options(archive:Path,seven_zip:str|None=None)->dict[str,Any]|None:
    root,source=_read_fomod_root(archive,seven_zip)
    if root is None:return None
    groups=[]; unsupported=[]
    supported={'config','moduleName','moduleImage','moduleDependencies','requiredInstallFiles','installSteps','installStep','optionalFileGroups','group','plugins','plugin','description','image','files','file','folder','conditionFlags','flag','typeDescriptor','type','dependencyType','patterns','pattern','dependencies','fileDependency','flagDependency','gameDependency','conditionalFileInstalls','patterns','visible','defaultType'}
    for node in root.iter():
        tag=node.tag.rsplit('}',1)[-1]
        if tag not in supported:unsupported.append(tag)
    for step_index,step in enumerate(root.findall('.//installStep')):
      step_dep=_dependency(step.find('./visible/dependencies') or step.find('./visible'))
      for group_index,group in enumerate(step.findall('./optionalFileGroups/group')):
        gtype=group.get('type','SelectAny'); opts=[]
        for plugin_index,plugin in enumerate(group.findall('./plugins/plugin')):
            files=[]
            for tag in ('file','folder'):
                for node in plugin.findall(f'./files/{tag}'):
                    files.append({'kind':tag,'source':node.get('source',''),'destination':node.get('destination',''),'priority':int(node.get('priority','0'))})
            flags={n.get('name',''):n.text or '' for n in plugin.findall('./conditionFlags/flag')}
            direct=plugin.find('./typeDescriptor/type'); dep_type=plugin.find('./typeDescriptor/dependencyType')
            patterns=[]
            if dep_type is not None:
                for pattern in dep_type.findall('./patterns/pattern'):
                    typ=pattern.find('./type'); patterns.append({'dependencies':_dependency(pattern.find('./dependencies')),'type':typ.get('name','Optional') if typ is not None else 'Optional'})
            oid=f'{step_index}:{group_index}:{plugin_index}'
            opts.append({'id':oid,'name':plugin.get('name',''),'type':direct.get('name','Optional') if direct is not None else 'Conditional','patterns':patterns,'description':plugin.findtext('description') or '','files':files,'flags':flags})
        groups.append({'id':f'{step_index}:{group_index}','step':step.get('name',''),'step_dependency':step_dep,'name':group.get('name',''),'type':gtype,'options':opts})
    required=[]
    for tag in ('file','folder'):
        for node in root.findall(f'./requiredInstallFiles/{tag}'):
            required.append({'kind':tag,'source':node.get('source',''),'destination':node.get('destination',''),'priority':int(node.get('priority','0'))})
    conditional=[]
    for pattern in root.findall('./conditionalFileInstalls/patterns/pattern'):
        files=[]
        for tag in ('file','folder'):
            for node in pattern.findall(f'./files/{tag}'):files.append({'kind':tag,'source':node.get('source',''),'destination':node.get('destination',''),'priority':int(node.get('priority','0'))})
        conditional.append({'dependencies':_dependency(pattern.find('./dependencies')),'files':files})

    # pyfomod evaluates conditional files, page visibility and dependency-based
    # option types during planning. Unknown extensions (including the obsolete
    # fommDependency) remain a safe hard stop.
    file_dependencies=sorted({node.get('file','') for node in root.findall('.//fileDependency') if node.get('file')},key=str.casefold)
    game_dependencies=sorted({node.get('version','') for node in root.findall('.//gameDependency') if node.get('version')})
    return {'engine':'pyfomod-1.2.1','source':source,'groups':groups,'required_files':required,'conditional_files':conditional,
            'file_dependencies':file_dependencies,'game_dependencies':game_dependencies,'unsupported':sorted(set(unsupported))}

def _game_version(cfg:dict[str,Any])->str|None:
    explicit=str(cfg.get('game_version') or '').strip()
    if explicit:return explicit
    root=Path(cfg.get('skyrim_game_path','')) if cfg.get('skyrim_game_path') else None
    exe=root/'SkyrimSE.exe' if root else None
    if not exe or not exe.is_file() or os.name!='nt':return None
    escaped=str(exe).replace("'","''")
    try:
        result=subprocess.run(['powershell','-NoProfile','-Command',f"(Get-Item -LiteralPath '{escaped}').VersionInfo.ProductVersion"],capture_output=True,text=True,timeout=10)
        match=re.search(r'\d+(?:\.\d+){1,3}',result.stdout)
        return match.group(0) if match else None
    except Exception:return None


def _fomod_file_type(instance:Path,profile:Path,cfg:dict[str,Any]):
    from ._vendor.pyfomod import FileType
    enabled=[]
    for line in _read_lines(profile/'modlist.txt'):
        if line.startswith('+'):
            path=instance/'mods'/line[1:]
            if path.is_dir():enabled.append(path)
    game_data=Path(cfg.get('skyrim_game_path',''))/'Data' if cfg.get('skyrim_game_path') else None
    active={line[1:].casefold() for line in _read_lines(profile/'plugins.txt') if line.startswith('*')}

    def state(name:str):
        rel=Path(name.replace('\\','/').lstrip('/'))
        if rel.is_absolute() or '..' in rel.parts:return FileType.MISSING
        exists=bool(game_data and (game_data/rel).is_file()) or any((mod/rel).is_file() for mod in enabled)
        if not exists:return FileType.MISSING
        if rel.suffix.casefold() in PLUGIN_SUFFIXES and rel.name.casefold() not in active:return FileType.INACTIVE
        return FileType.ACTIVE
    return state


def _evaluate_fomod(archive:Path,seven_zip:str|None,fomod:dict[str,Any],selections:dict[str,list[str]],cfg:dict[str,Any],instance:Path,profile:Path,auto_select:bool=False)->dict[str,Any]:
    from ._vendor import pyfomod
    valid={group['id']:{option['id'] for option in group['options']} for group in fomod['groups']}
    unknown_groups=sorted(set(selections)-set(valid))
    unknown_options={group:sorted(set(ids)-valid.get(group,set())) for group,ids in selections.items() if set(ids)-valid.get(group,set())}
    if unknown_groups or unknown_options:raise WorkflowError('FOMOD selections contain unknown stable IDs',1,{'unknown_groups':unknown_groups,'unknown_options':unknown_options})
    version=_game_version(cfg)
    if fomod.get('game_dependencies') and not version:raise WorkflowError('FOMOD requires the Skyrim game version, but SkyrimSE.exe could not be versioned',1,{'requirements':fomod['game_dependencies']})
    file_state=_fomod_file_type(instance,profile,cfg)
    try:
        with tempfile.TemporaryDirectory(prefix='mo2-fomod-eval-') as td:
            extracted=Path(td)/'archive'; extracted.mkdir(); _extract(archive,extracted,seven_zip)
            module=extracted/Path(fomod['source'])
            info=next((p for p in module.parent.iterdir() if p.name.casefold()=='info.xml'),None)
            root=pyfomod.parse((str(info) if info else None,str(module)))
            effective=module.parent.parent
            option_ids={id(option):f'{pi}:{gi}:{oi}' for pi,page in enumerate(root.pages) for gi,group in enumerate(page) for oi,option in enumerate(group)}
            installer=pyfomod.Installer(root,path=effective,game_version=version,file_type=file_state)
            visible=[]; selected=[]; page=installer.next()
            while page is not None:
                page_selected=[]; page_groups=[]
                for group in page:
                    choices=[]; group_options=list(group); group_id=option_ids[id(group_options[0]._object)].rsplit(':',1)[0] if group_options else None
                    requested=set(selections.get(group_id,[])) if group_id else set()
                    chosen=[option for option in group_options if option_ids[id(option._object)] in requested]
                    if auto_select:
                        chosen=[option for option in group_options if option.type is pyfomod.OptionType.REQUIRED]+[option for option in group_options if option.type is pyfomod.OptionType.RECOMMENDED]
                        usable=[option for option in group_options if option.type is not pyfomod.OptionType.NOTUSABLE]
                        if group.type is pyfomod.GroupType.ALL:chosen=usable
                        elif group.type in (pyfomod.GroupType.EXACTLYONE,pyfomod.GroupType.ATMOSTONE) and len(chosen)>1:chosen=chosen[:1]
                        elif group.type in (pyfomod.GroupType.EXACTLYONE,pyfomod.GroupType.ATLEASTONE) and not chosen and usable:chosen=usable[:1]
                    for option in group_options:
                        oid=option_ids[id(option._object)]
                        choices.append({'id':oid,'name':option.name,'type':option.type.value})
                        if option in chosen:page_selected.append(option); selected.append(oid)
                    page_groups.append({'id':group_id,'name':group.name,'type':group.type.value,'options':choices})
                visible.append({'name':page.name,'groups':page_groups})
                page=installer.next(page_selected)
            selected_files=[{'kind':'file','source':info.source,'destination':info.destination,'priority':info.priority} for info in installer.file_infos()]
            staged=Path(td)/'staged'; staged.mkdir(); _copy_selected(effective,staged,selected_files)
            plugins=_scan_plugins(staged)
            return {'selected_files':selected_files,'plugins':plugins,'visible_pages':visible,'selected_option_ids':selected,'flags':installer.flags(),'game_version':version,
                    'recommended_selections':{group['id']:[option['id'] for option in group['options'] if option['id'] in selected] for page in visible for group in page['groups'] if group.get('id')},
                    'environment':{'skyrim_game_path':str(cfg.get('skyrim_game_path','')),'configured_game_version':str(cfg.get('game_version') or ''),
                                   'file_states':{name:file_state(name).value for name in fomod.get('file_dependencies',[])}}}
    except pyfomod.FailedCondition as exc:raise WorkflowError(f'FOMOD dependency check failed: {exc}',1) from exc
    except pyfomod.InvalidSelection as exc:raise WorkflowError(f'Invalid FOMOD selection: {exc}',1) from exc
    except (OSError,ValueError,ET.ParseError) as exc:raise WorkflowError(f'FOMOD evaluation failed: {exc}',2) from exc



def fomod_preview(archive:Path,cfg:dict[str,Any],seven_zip:str|None=None,fomod:dict[str,Any]|None=None)->dict[str,Any]|None:
    fomod=fomod if fomod is not None else fomod_options(archive,seven_zip)
    if fomod is None:return None
    if fomod['unsupported']:raise WorkflowError('FOMOD contains unsupported expressions; installation was stopped safely',1,{'unsupported':fomod['unsupported']})
    instance=Path(cfg.get('mo2_instance_path','')); profile=instance/'profiles'/cfg.get('profile','')
    if not profile.is_dir():raise WorkflowError('Configured profile does not exist',2)
    return _evaluate_fomod(archive.expanduser().resolve(),seven_zip,fomod,{},cfg,instance,profile,auto_select=True)


def _profile_modlist_context(profile:Path)->dict[str,Any]:
    lines=_read_lines(profile/'modlist.txt')
    entries=[]
    managed=[(index,line) for index,line in enumerate(lines) if line and not line.startswith('#')]
    total=len(managed)
    for visual_rank,(index,line) in enumerate(reversed(managed)):
        name=line.lstrip('+-*')
        entries.append({'name':name,'marker':line[:1] if line[:1] in '+-*' else '',
                        'enabled':line.startswith(('+','*')),'file_index':index,
                        'mo2_left_pane_index_from_top':visual_rank})
    by_file=sorted(entries,key=lambda item:item['file_index'])
    separators=[item for item in by_file if item['name'].casefold().endswith('_separator') or 'separator' in item['name'].casefold()]
    return {
        'installed_mods_file_order':by_file,
        'separators':separators,
        'dependency_mods':[],
        'conflict_file_providers':[],
        'related_mods':[],
        'evidence_limits':['Plugin master parsing and semantic mod classification are not performed; empty dependency/related lists are not automatic placement advice.'],
        'ordering_explanation':{
            'file_direction':'Earlier modlist.txt lines have higher MO2 priority and appear lower in the left pane.',
            'before_mod':'Insert immediately before the anchor in modlist.txt (higher MO2 priority / lower in the left pane).',
            'after_mod':'Insert immediately after the anchor in modlist.txt (lower MO2 priority / higher in the left pane).',
        },
    }

def _add_conflict_context(context:dict[str,Any],instance:Path,effective_files:list[str])->None:
    expected={path.replace('\\','/').casefold() for path in effective_files if not _is_metadata_file(path)}
    providers=[]
    if not expected:return
    for entry in context['installed_mods_file_order']:
        if entry['marker'] not in ('+','-'):continue
        folder=instance/'mods'/entry['name']
        if not folder.is_dir():continue
        matches=[]
        for path in folder.rglob('*'):
            if path.is_file() and path.relative_to(folder).as_posix().casefold() in expected:
                matches.append(path.relative_to(folder).as_posix())
                if len(matches)>=100:break
        if matches:providers.append({'mod':entry['name'],'enabled':entry['enabled'],'matching_files':matches,'truncated':len(matches)>=100})
    context['conflict_file_providers']=providers

def _empty_placement()->dict[str,Any]:
    return {'required':True,'mode':'explicit','before_mod':None,'after_mod':None,'modlist_top':False,'modlist_bottom':False}


def _normalize_placement(placement:dict[str,Any]|None)->dict[str,Any]:
    result=_empty_placement(); result.update(placement or {})
    chosen=[key for key in ('before_mod','after_mod') if result.get(key)]
    chosen.extend(key for key in ('modlist_top','modlist_bottom') if result.get(key) is True)
    if len(chosen)!=1:
        raise WorkflowError('Exactly one explicit mod placement is required',2,{'placement':result,'accepted':['before_mod','after_mod','modlist_top','modlist_bottom']})
    return result


def _existing_install_state(instance:Path,profile:Path,mod_name:str)->dict[str,Any]:
    lines=_read_lines(profile/'modlist.txt')
    matches=[index for index,line in enumerate(lines) if line.startswith(('+','-')) and _entry_name(line).casefold()==mod_name.casefold()]
    target=instance/'mods'/mod_name
    if len(matches)>1:
        raise WorkflowError('Existing mod entry is duplicated; update identity is ambiguous',2,{'mod_name':mod_name,'matches':[index+1 for index in matches]})
    if target.is_dir() != bool(matches):
        raise WorkflowError('Mod directory and profile entry do not agree; update identity is ambiguous',2,{
            'mod_name':mod_name,'target_exists':target.is_dir(),'profile_matches':[index+1 for index in matches]})
    if not matches:
        return {'operation':'install','target_exists':False}
    index=matches[0]
    previous=_entry_name(lines[index-1]) if index>0 and not lines[index-1].startswith('#') else None
    following=_entry_name(lines[index+1]) if index+1<len(lines) else None
    return {'operation':'update','target_exists':True,'enabled':lines[index].startswith('+'),'marker':lines[index][0],
            'file_line':index+1,'previous_mod':previous,'next_mod':following}


def _validated_source_metadata(source_metadata:dict[str,Any]|None)->dict[str,Any]:
    if not source_metadata:
        return {}
    result=dict(source_metadata)
    if result.get('provider')!='nexus':
        raise WorkflowError('Unsupported source metadata provider',2,{'provider':result.get('provider')})
    missing=[key for key in ('mod_id','file_id','official_filename','version') if result.get(key) in (None,'')]
    if missing:
        raise WorkflowError('Nexus source metadata is incomplete',2,{'missing':missing})
    try:
        result['mod_id']=int(result['mod_id']); result['file_id']=int(result['file_id'])
    except (TypeError,ValueError) as exc:
        raise WorkflowError('Nexus mod_id and file_id must be integers',2) from exc
    if result['mod_id']<=0 or result['file_id']<=0:
        raise WorkflowError('Nexus mod_id and file_id must be positive',2)
    filename=str(result['official_filename'])
    invalid_name=(Path(filename).name!=filename or filename in ('.','..') or any(ord(char)<32 for char in filename)
                  or bool(re.search(r'[<>:\"/\\|?*]',filename)) or filename.rstrip(' .')!=filename)
    if invalid_name:
        raise WorkflowError('Nexus official filename must be a safe Windows basename',2,{'official_filename':filename})
    version=str(result['version'])
    if any(ord(char)<32 for char in version):
        raise WorkflowError('Nexus version contains control characters',2)
    result['official_filename']=filename; result['file_name']=filename; result['version']=version
    return result


def create_plan(archive:Path,cfg:dict[str,Any],plans_dir:Path,name:str|None=None,selections:dict[str,list[str]]|None=None,seven_zip:str|None=None,placement:dict[str,Any]|None=None,source_metadata:dict[str,Any]|None=None)->dict[str,Any]:
    source_metadata=_validated_source_metadata(source_metadata)
    archive=archive.expanduser().resolve()
    if not archive.is_file(): raise WorkflowError('Archive does not exist',2)
    layout=detect_layout(archive_members(archive,seven_zip))
    public_layout={key:value for key,value in layout.items() if not key.startswith('_')}
    if layout['type']=='root':raise WorkflowError('Game-root archive cannot be planned as an ordinary MO2 mod',3,{'layout':public_layout})
    fomod=fomod_options(archive,seven_zip)
    selections_missing=bool(fomod and selections is None and any(group.get('options') for group in fomod['groups']))
    selections=selections or {}
    if fomod and fomod['unsupported']: raise WorkflowError('FOMOD contains unsupported expressions; installation was stopped safely',1,{'unsupported':fomod['unsupported']})
    selected_files=[]; fomod_resolution=None
    instance=Path(cfg.get('mo2_instance_path','')); profile=instance/'profiles'/cfg.get('profile','')
    if not profile.is_dir():raise WorkflowError('Configured profile does not exist',2)
    if selections_missing:
        preview=_evaluate_fomod(archive,seven_zip,fomod,{},cfg,instance,profile,auto_select=True)
        raise WorkflowError('FOMOD selections are required before creating an executable plan',1,{'status':'selection_required','layout':public_layout,'fomod':fomod,'recommended_selections':preview['recommended_selections'],'recommended_resolution':preview})
    if fomod:
        fomod_resolution=_evaluate_fomod(archive,seven_zip,fomod,selections,cfg,instance,profile)
        selected_files=fomod_resolution['selected_files']
    plan_id=datetime.now().strftime('%Y%m%d-%H%M%S-')+uuid.uuid4().hex[:8]
    mod_name=name or re.sub(r'[-_](?:v?\d[\w.-]*)$','',archive.stem).strip() or archive.stem
    existing=_existing_install_state(instance,profile,mod_name)
    if existing['operation']=='update':
        if any((placement or {}).values()):
            raise WorkflowError('Explicit placement is not accepted for an in-place update',2,{'mod_name':mod_name})
        chosen_placement={'required':False,'mode':'preserve_existing','enabled':existing['enabled'],'file_line':existing['file_line'],
                          'previous_mod':existing['previous_mod'],'next_mod':existing['next_mod']}
    else:
        chosen_placement=_empty_placement(); chosen_placement.update(placement or {})
    modlist_context=_profile_modlist_context(profile); _add_conflict_context(modlist_context,instance,layout.get('_effective_files',[]))
    profile_transition=None
    if existing['operation']=='update':
        old_plugins=_scan_plugins(instance/'mods'/mod_name)
        if fomod:new_plugins=list(fomod_resolution['plugins'])
        else:
            candidate=[Path(x).name for x in layout.get('_effective_files',[])]
            new_plugins=sorted({x for x in candidate if Path(x).suffix.casefold() in PLUGIN_SUFFIXES},key=str.casefold)
        pl,lo,changes,states=transform_update_profile(bool(existing['enabled']),_read_lines(profile/'plugins.txt'),_read_lines(profile/'loadorder.txt'),new_plugins,old_plugins)
        profile_transition={'plugins':new_plugins,'old_plugins':old_plugins,'plugin_changes':changes,'plugin_states':states,
          'final_files':{'modlist.txt':_read_lines(profile/'modlist.txt'),'plugins.txt':pl,'loadorder.txt':lo}}
    data={'schema_version':2,'id':plan_id,'created_at':datetime.now(timezone.utc).isoformat(),'status':'planned',
          'operation':existing['operation'],'archive':str(archive),'archive_sha256':sha256(archive),'mod_name':mod_name,
          'profile':cfg.get('profile',''),'instance':cfg.get('mo2_instance_path',''),'layout':public_layout,
          'placement':chosen_placement,'existing':existing,'source_metadata':source_metadata,'profile_transition':profile_transition,
          'modlist_context':modlist_context,'fomod':fomod,'fomod_resolution':fomod_resolution,'selections':selections,'selected_files':selected_files,
          'archive_after_install':bool(cfg.get('archive_after_install',False)),'archive_directory':cfg.get('archive_directory',''),
          'profile_binding':{n:sha256(profile/n) for n in ('modlist.txt','plugins.txt','loadorder.txt')}}
    atomic_json(plans_dir/f'{plan_id}.json',data); return data

def _copy_selected(source:Path,dest:Path,items:list[dict[str,Any]])->None:
    for item in sorted(items,key=lambda x:x.get('priority',0)):
        src=source/Path(item['source'].replace('\\','/'))
        raw_destination=str(item.get('destination','')).replace('\\','/')
        target=dest/Path(raw_destination)
        if not src.exists(): raise WorkflowError(f"FOMOD source is missing: {item['source']}",2)
        if src.is_dir():
            target.mkdir(parents=True,exist_ok=True); shutil.copytree(src,target,dirs_exist_ok=True)
        else:
            if not raw_destination or raw_destination.endswith('/') or item.get('kind')=='folder':target=target/src.name
            target.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,target)

def _write_enabled(path:Path,names:list[str])->None:
    raw=path.read_text(encoding='utf-8-sig').splitlines() if path.exists() else []
    existing={x.lstrip('+-*').casefold() for x in raw}
    for name in names:
        if name.casefold() not in existing: raw.append('+'+name if path.name=='modlist.txt' else '*'+name)
        else:
            raw=[(('+' if path.name=='modlist.txt' else '*')+x.lstrip('+-*')) if x.lstrip('+-*').casefold()==name.casefold() else x for x in raw]
    path.write_text('\n'.join(raw)+'\n',encoding='utf-8-sig')

def _read_lines(path:Path)->list[str]:
    return path.read_text(encoding='utf-8-sig').splitlines() if path.exists() else []

def _unique_entries(lines:list[str],prefixes:str)->list[str]:
    result=[]; seen=set()
    for line in lines:
        key=line.lstrip(prefixes).casefold()
        if line.startswith('#') or not key or key not in seen:
            result.append(line)
            if key:seen.add(key)
    return result

def _entry_name(line:str)->str:
    return line.lstrip('+-*')

def _find_unique_anchor(lines:list[str],name:str)->int:
    matches=[index for index,line in enumerate(lines) if line and not line.startswith('#') and _entry_name(line).casefold()==name.casefold()]
    if len(matches)!=1:
        reason='missing' if not matches else 'duplicated'
        raise WorkflowError(f'Mod placement anchor is {reason}: {name}',2,{'anchor':name,'matches':matches})
    return matches[0]

def _place_mods(lines:list[str],mod_names:list[str],placement:dict[str,Any])->tuple[list[str],dict[str,Any]]:
    placement=_normalize_placement(placement)
    header='# This file was automatically generated by Mod Organizer.'
    lines=[line for line in lines if line!=header and _entry_name(line).casefold() not in {name.casefold() for name in mod_names}]
    unmanaged_at=next((i for i,line in enumerate(lines) if line.startswith('*DLC:') or line.startswith('*Creation Club:')),len(lines))
    if placement.get('before_mod'):
        insertion=_find_unique_anchor(lines,str(placement['before_mod']))
    elif placement.get('after_mod'):
        insertion=_find_unique_anchor(lines,str(placement['after_mod']))+1
    elif placement.get('modlist_top'):
        insertion=0
    else:
        insertion=unmanaged_at
    if insertion>unmanaged_at:
        raise WorkflowError('Mod placement would enter the unmanaged DLC/Creation Club block',2,{'insertion_index':insertion,'unmanaged_index':unmanaged_at})
    added=['+'+name for name in mod_names]
    lines[insertion:insertion]=added
    result=[header]+lines
    start=insertion+1
    previous=_entry_name(result[start-1]) if start-1>=1 else None
    next_index=start+len(added)
    following=_entry_name(result[next_index]) if next_index<len(result) else None
    audit={'file_direction':{'previous_mod':previous,'new_mods':mod_names,'next_mod':following},
           'mo2_left_pane':{'above_mod':following,'new_mods_top_to_bottom':list(reversed(mod_names)),'new_mods_high_to_low_priority':mod_names,'below_mod':previous},
           'explanation':'modlist.txt order is the reverse of the MO2 left pane.'}
    return result,audit

def update_profile(profile:Path,mod_names:list[str],plugins:list[str],placement:dict[str,Any])->dict[str,Any]:
    modlist=profile/'modlist.txt'; plugin_file=profile/'plugins.txt'; loadorder=profile/'loadorder.txt'
    ml=_unique_entries(_read_lines(modlist),'+-'); pl=_unique_entries(_read_lines(plugin_file),'*'); lo=_unique_entries(_read_lines(loadorder),'*')
    ml,placement_result=_place_mods(ml,mod_names,placement)
    wanted={name.casefold():name for name in plugins}
    pl=[line for line in pl if line.lstrip('*').casefold() not in wanted]
    lo=[line for line in lo if line.lstrip('*').casefold() not in wanted]
    esms=[name for name in plugins if name.casefold().endswith('.esm')]; others=[name for name in plugins if name not in esms]
    pl_esm=max((index for index,line in enumerate(pl) if line.lstrip('*').casefold().endswith('.esm')),default=-1)+1
    lo_esm=max((index for index,line in enumerate(lo) if line.lstrip('*').casefold().endswith('.esm')),default=-1)+1
    pl[pl_esm:pl_esm]=['*'+name for name in esms]; lo[lo_esm:lo_esm]=esms
    pl.extend('*'+name for name in others); lo.extend(others)
    for path,lines in ((modlist,ml),(plugin_file,pl),(loadorder,lo)):
        path.write_text('\n'.join(lines)+'\n',encoding='utf-8-sig',newline='\n')
    return placement_result


def transform_profile_apply(modlist_lines:list[str],plugin_lines:list[str],loadorder_lines:list[str],*,enable_mod:list[str]=[],disable_mod:list[str]=[],enable_plugin:list[str]=[],disable_plugin:list[str]=[],unregister_plugin:list[str]=[],placement:dict[str,Any]|None=None)->dict[str,Any]:
    """Pure, strict transformation for the native ``profile apply`` command."""
    ml=list(modlist_lines); pl=list(plugin_lines); lo=list(loadorder_lines)
    actions={x.casefold():True for x in enable_mod}; actions.update({x.casefold():False for x in disable_mod})
    if set(x.casefold() for x in enable_mod)&set(x.casefold() for x in disable_mod): raise WorkflowError('A mod cannot be both enabled and disabled',2)
    for key,enabled in actions.items():
        hits=[i for i,x in enumerate(ml) if x.startswith(('+','-')) and _entry_name(x).casefold()==key]
        if len(hits)>1: raise WorkflowError('Mod entry is duplicated',3,{'mod':key,'matches':hits})
        if not hits:
            if not placement or not any(placement.values()): raise WorkflowError('Mod entry is missing and no explicit placement was supplied',3,{'mod':key})
            name=next((x for x in [*enable_mod,*disable_mod] if x.casefold()==key),key)
            ml,_=_place_mods(ml,[name],{**placement,'enabled':enabled})
        else:
            i=hits[0]; name=_entry_name(ml[i]); ml[i]=('+' if enabled else '-')+name
            if placement and any(placement.values()):
                ml.pop(i); ml,_=_place_mods(ml,[name],{**placement,'enabled':enabled})
    requested=[*enable_plugin,*disable_plugin,*unregister_plugin]
    if len({x.casefold() for x in requested})!=len(requested): raise WorkflowError('Conflicting plugin actions were requested',2)
    _profile_plugin_states(pl,lo,requested)
    for name,state in [*((x,'enabled') for x in enable_plugin),*((x,'disabled') for x in disable_plugin),*((x,'unregistered') for x in unregister_plugin)]:
        key=name.casefold(); pl=[x for x in pl if x.lstrip('*').casefold()!=key]; lo=[x for x in lo if x.casefold()!=key]
        if state!='unregistered': pl.append(('*' if state=='enabled' else '')+name); lo.append(name)
    # Validate all touched entries and exact placement after transformation.
    states=_profile_plugin_states(pl,lo,requested)
    return {'modlist_lines':ml,'plugins_lines':pl,'loadorder_lines':lo,'plugin_states':states,
            'changed':{'modlist.txt':ml!=modlist_lines,'plugins.txt':pl!=plugin_lines,'loadorder.txt':lo!=loadorder_lines}}

def _scan_plugins(root:Path)->list[str]:
    return sorted({item.name for item in root.rglob('*') if item.is_file() and item.suffix.casefold() in PLUGIN_SUFFIXES},key=str.casefold)


def _placement_audit(lines:list[str],mod_name:str)->dict[str,Any]:
    matches=[index for index,line in enumerate(lines) if line.startswith(('+','-')) and _entry_name(line).casefold()==mod_name.casefold()]
    if len(matches)!=1:raise WorkflowError('Updated mod is not unique in modlist.txt',2,{'mod_name':mod_name,'matches':matches})
    index=matches[0]; previous=_entry_name(lines[index-1]) if index>0 and not lines[index-1].startswith('#') else None
    following=_entry_name(lines[index+1]) if index+1<len(lines) else None
    return {'file_direction':{'previous_mod':previous,'new_mods':[mod_name],'next_mod':following},
            'mo2_left_pane':{'above_mod':following,'new_mods_top_to_bottom':[mod_name],'new_mods_high_to_low_priority':[mod_name],'below_mod':previous},
            'explanation':'modlist.txt order is the reverse of the MO2 left pane.'}


def _profile_plugin_states(plugin_lines:list[str],loadorder_lines:list[str], relevant:list[str]|None=None)->dict[str,str]:
    """Parse MO2's two plugin files strictly and return enabled/disabled/unregistered."""
    wanted={x.casefold():x for x in (relevant or [])}
    pmap:dict[str,list[str]]={}; lmap:dict[str,list[str]]={}
    for line in plugin_lines:
        if not line or line.startswith('#'): continue
        name=line[1:] if line.startswith('*') else line; pmap.setdefault(name.casefold(),[]).append(line)
    for line in loadorder_lines:
        if not line or line.startswith('#'): continue
        name=line[1:] if line.startswith('*') else line
        if line.startswith('*'): raise WorkflowError('loadorder.txt contains an activation marker',3,{'repair':f'remove * from {line}'})
        lmap.setdefault(name.casefold(),[]).append(line)
    keys=set(wanted) if relevant is not None else set(pmap)|set(lmap)
    states={}
    for key in keys:
        pc=pmap.get(key,[]); lc=lmap.get(key,[]); display=wanted.get(key,key)
        if len(pc)>1 or len(lc)>1:
            raise WorkflowError(f'Duplicate plugin registration: {display}',3,{'plugin':display,'plugins_txt':pc,'loadorder_txt':lc})
        if bool(pc)!=bool(lc):
            raise WorkflowError(f'Plugin is registered in only one profile file: {display}',3,{'plugin':display,'repair':'add it to both files or remove it from both'})
        states[key]='enabled' if pc and pc[0].startswith('*') else ('disabled' if pc else 'unregistered')
    return states


def transform_update_profile(mod_enabled:bool,plugin_lines:list[str],loadorder_lines:list[str],new_plugins:list[str],old_plugins:list[str])->tuple[list[str],list[str],dict[str,Any],dict[str,str]]:
    """Pure profile transition used by planning and apply."""
    old={x.casefold():x for x in old_plugins}; new={x.casefold():x for x in new_plugins}
    states=_profile_plugin_states(plugin_lines,loadorder_lines,list({**old,**new}.values()))
    retained=set(old)&set(new); removed=set(old)-set(new); added=set(new)-set(old)
    pl=[x for x in plugin_lines if x.lstrip('*').casefold() not in removed]
    lo=[x for x in loadorder_lines if x.casefold() not in removed]
    transitions=[]
    for key in sorted(retained): transitions.append({'plugin':new[key],'before':states[key],'after':states[key]})
    for key in sorted(removed): transitions.append({'plugin':old[key],'before':states[key],'after':'unregistered'})
    added_disabled=[]; added_unregistered=[]
    for key in sorted(added):
        name=new[key]; after='disabled' if mod_enabled else 'unregistered'
        transitions.append({'plugin':name,'before':'unregistered','after':after})
        if after=='disabled':
            pi=max((i for i,x in enumerate(pl) if x.lstrip('*').casefold().endswith('.esm')),default=-1)+1 if name.casefold().endswith('.esm') else len(pl)
            li=max((i for i,x in enumerate(lo) if x.casefold().endswith('.esm')),default=-1)+1 if name.casefold().endswith('.esm') else len(lo)
            pl.insert(pi,name); lo.insert(li,name); added_disabled.append(name)
        else: added_unregistered.append(name)
    final={key:states[key] for key in retained}
    final.update({key:('disabled' if mod_enabled else 'unregistered') for key in added})
    changes={'preserved_plugins':sorted((new[k] for k in retained),key=str.casefold),
      'preserved_unregistered_plugins':sorted((new[k] for k in retained if states[k]=='unregistered'),key=str.casefold),
      'new_plugins_disabled':added_disabled,'new_plugins_unregistered':added_unregistered,
      'new_plugins_already_present':[],'removed_plugins':sorted((old[k] for k in removed),key=str.casefold),
      'plugin_transition':transitions}
    return pl,lo,changes,final


def update_profile_for_update(profile:Path,mod_name:str,new_plugins:list[str],old_plugins:list[str],mod_enabled:bool|None=None)->tuple[dict[str,Any],dict[str,Any],dict[str,str]]:
    ml=_read_lines(profile/'modlist.txt')
    if mod_enabled is None:
        matches=[x for x in ml if x.startswith(('+','-')) and _entry_name(x).casefold()==mod_name.casefold()]
        if len(matches)!=1: raise WorkflowError('Updated mod is not unique in modlist.txt',3)
        mod_enabled=matches[0].startswith('+')
    pl,lo,changes,states=transform_update_profile(mod_enabled,_read_lines(profile/'plugins.txt'),_read_lines(profile/'loadorder.txt'),new_plugins,old_plugins)
    (profile/'plugins.txt').write_text('\n'.join(pl)+'\n',encoding='utf-8-sig',newline='\n')
    (profile/'loadorder.txt').write_text('\n'.join(lo)+'\n',encoding='utf-8-sig',newline='\n')
    return _placement_audit(ml,mod_name),changes,states

def audit_profile(instance:Path,profile:Path,mod_name:str,plugin_states:dict[str,str],target:Path,expected_enabled:bool=True,removed_plugins:list[str]|None=None)->dict[str,Any]:
    issues=[]; ml=_read_lines(profile/'modlist.txt'); pl=_read_lines(profile/'plugins.txt'); lo=_read_lines(profile/'loadorder.txt')
    if not target.is_dir():issues.append({'severity':'error','what':'target mod directory is missing'})
    expected_marker=('+' if expected_enabled else '-')+mod_name
    if sum(line.lstrip('+-').casefold()==mod_name.casefold() for line in ml)!=1 or not any(line.casefold()==expected_marker.casefold() for line in ml):
        issues.append({'severity':'error','what':'mod enable state or uniqueness is invalid'})
    for plugin_key,state in plugin_states.items():
        plugin=next((item.name for item in target.rglob('*') if item.is_file() and item.name.casefold()==plugin_key),plugin_key)
        if not any(item.is_file() and item.name.casefold()==plugin_key for item in target.rglob('*')):issues.append({'severity':'error','what':f'plugin output missing: {plugin}'})
        matches=[line for line in pl if line.lstrip('*').casefold()==plugin_key]
        if state=='unregistered':
            if matches or any(line.casefold()==plugin_key for line in lo): issues.append({'severity':'error','what':f'plugin should be unregistered: {plugin}'})
            continue
        enabled=state=='enabled'
        if len(matches)!=1 or matches[0].startswith('*')!=enabled:issues.append({'severity':'error','what':f'plugin state invalid: {plugin}'})
        if sum(line.casefold()==plugin_key for line in lo)!=1:issues.append({'severity':'error','what':f'loadorder entry invalid: {plugin}'})
    for plugin in removed_plugins or []:
        key=plugin.casefold()
        if any(line.lstrip('*').casefold()==key for line in pl) or any(line.casefold()==key for line in lo):
            issues.append({'severity':'error','what':f'removed plugin remains configured: {plugin}'})
    for label,lines,prefix in (('modlist',ml,'+-'),('plugins',pl,'*'),('loadorder',lo,'')):
        keys=[line.lstrip(prefix).casefold() for line in lines if line and not line.startswith('#')]
        if len(keys)!=len(set(keys)):issues.append({'severity':'error','what':f'duplicate {label} entries'})
    return {'status':'passed' if not issues else 'failed','issues':issues}


def _content_manifest(root:Path)->dict[str,str]:
    return {item.relative_to(root).as_posix():sha256(item) for item in root.rglob('*') if item.is_file() and item.name.casefold()!='meta.ini'}


def _compare_manifests(expected:dict[str,str],actual:dict[str,str])->dict[str,Any]:
    missing=sorted(set(expected)-set(actual),key=str.casefold); extra=sorted(set(actual)-set(expected),key=str.casefold)
    different=sorted((name for name in set(expected)&set(actual) if expected[name]!=actual[name]),key=str.casefold)
    return {'status':'passed' if not (missing or extra or different) else 'failed','expected_files':len(expected),
            'installed_files':len(actual),'missing':missing,'extra':extra,'different':different}

def archive_source(source:Path,destination:Path,file_id:str|None=None)->dict[str,Any]:
    source=source.expanduser().resolve(); destination=destination.expanduser().resolve(); target=(destination/source.name).resolve()
    if source==target or (target.exists() and source.exists() and os.path.samefile(source,target)):
        return {'status':'already_in_archive','path':str(source)}
    destination.mkdir(parents=True,exist_ok=True)
    if target.exists():
        if sha256(target)==sha256(source):
            source.unlink(); return {'status':'deduplicated','path':str(target)}
        base_suffix=f'-{file_id}' if file_id else datetime.now().strftime('-%Y%m%d-%H%M%S')
        candidate=destination/f'{source.stem}{base_suffix}{source.suffix}'; counter=2
        while candidate.exists():
            candidate=destination/f'{source.stem}{base_suffix}-{counter}{source.suffix}'; counter+=1
        target=candidate
    shutil.move(str(source),target); return {'status':'moved','path':str(target)}

def _validate_update_state(plan:dict[str,Any],instance:Path,profile:Path)->dict[str,Any]:
    current=_existing_install_state(instance,profile,plan['mod_name']); planned=plan.get('existing') or {}
    fields=('operation','enabled','file_line','previous_mod','next_mod')
    mismatches={field:{'planned':planned.get(field),'current':current.get(field)} for field in fields if planned.get(field)!=current.get(field)}
    if mismatches:raise WorkflowError('Existing mod placement or state changed after planning',2,{'mismatches':mismatches})
    return current


def apply_plan(plan_path:Path,seven_zip:str|None,placement:dict[str,Any]|None=None)->dict[str,Any]:
    plan=json.loads(plan_path.read_text(encoding='utf-8-sig'))
    if plan.get('schema_version') != 2: raise WorkflowError('Plan schema is obsolete; please create a new plan',2,{'planned_schema':plan.get('schema_version'),'required_schema':2})
    running=mo2_running()
    if running: raise WorkflowError('Close Mod Organizer 2 before applying this installation plan',3,{'processes':running,'plan_id':plan['id']})
    if plan.get('status') not in ('planned','rolled_back'):
        raise WorkflowError('Installation plan is not in an applicable state',2,{'status':plan.get('status')})
    archive=Path(plan['archive'])
    if not archive.exists() or sha256(archive)!=plan['archive_sha256']: raise WorkflowError('Archive changed or is missing; create a new plan',2)
    instance=Path(plan['instance']); profile=instance/'profiles'/plan['profile']; target=instance/'mods'/plan['mod_name']
    if not profile.is_dir():raise WorkflowError('Configured profile does not exist',2)
    binding=plan.get('profile_binding',{})
    drift={n:{'planned':binding.get(n),'current':sha256(profile/n) if (profile/n).is_file() else None} for n in ('modlist.txt','plugins.txt','loadorder.txt') if binding.get(n)!=(sha256(profile/n) if (profile/n).is_file() else None)}
    if drift: raise WorkflowError('Profile changed after planning; please create a new plan',3,{'drift':drift})
    resolution=plan.get('fomod_resolution') or {}
    environment=resolution.get('environment') or {}
    if resolution and 'game_version' in resolution:
        current_game_version=_game_version({'skyrim_game_path':environment.get('skyrim_game_path',''),'game_version':environment.get('configured_game_version','')})
        if current_game_version!=resolution.get('game_version'):
            raise WorkflowError('FOMOD game version environment changed after planning; please create a new plan',3,{'planned':resolution.get('game_version'),'current':current_game_version})
    if environment.get('file_states'):
        state=_fomod_file_type(instance,profile,{'skyrim_game_path':environment.get('skyrim_game_path','')})
        dependency_drift={name:{'planned':planned,'current':state(name).value} for name,planned in environment['file_states'].items() if state(name).value!=planned}
        if dependency_drift:raise WorkflowError('FOMOD dependency environment changed after planning; please create a new plan',3,{'drift':dependency_drift})
    operation=plan.get('operation','install')
    if operation=='update':
        if placement and any(placement.values()):raise WorkflowError('Explicit placement is not accepted for an in-place update',2)
        _validate_update_state(plan,instance,profile); selected_placement=dict(plan['placement'])
    else:
        selected_placement=dict(plan.get('placement') or {})
        if placement:selected_placement.update(placement)
        selected_placement=_normalize_placement(selected_placement)
        _place_mods(_read_lines(profile/'modlist.txt'),[plan['mod_name']],selected_placement)
    current_layout=detect_layout(archive_members(archive,seven_zip)); planned_layout=plan.get('layout') or {}
    for key in ('nesting_root','flatten','type'):
        if planned_layout.get(key)!=current_layout.get(key):
            raise WorkflowError('Archive layout no longer matches the installation plan',2,{'field':key,'planned':planned_layout.get(key),'current':current_layout.get(key)})
    tx=instance/'_agent_toolkit_backups'/plan['id']; tx.mkdir(parents=True,exist_ok=False)
    snapshots=[]; committed=False; target_committed=False; old_moved=False
    try:
        plan['status']='applying'; plan['placement']=selected_placement; atomic_json(plan_path,plan)
        for profile_file in (profile/'modlist.txt',profile/'plugins.txt',profile/'loadorder.txt'):
            if not profile_file.is_file():raise WorkflowError(f'Missing profile file: {profile_file}',2)
            backup=tx/profile_file.name; shutil.copy2(profile_file,backup); snapshots.append((profile_file,backup))
        extracted=tx/'x'; extracted.mkdir(); _extract(archive,extracted,seven_zip)
        staged=tx/'s'; staged.mkdir()
        if plan.get('fomod'):
            source=extracted/Path(current_layout['nesting_root']) if current_layout.get('flatten') else extracted
            _copy_selected(source,staged,plan['selected_files'])
        else:_stage_effective_root(extracted,staged,current_layout)
        validation=validate_staged_mod(staged); plugins=validation['plugins']
        old_plugins=_scan_plugins(target) if target.is_dir() else []
        try:
            metadata_result=prepare_meta_ini(staged,target/'meta.ini' if target.is_dir() else None,plan.get('source_metadata'))
        except MetadataError as exc:raise WorkflowError(f'Metadata validation failed: {exc}',2) from exc
        expected_manifest=_content_manifest(staged)
        if target.exists():shutil.move(target,tx/'old_mod'); old_moved=True
        target.parent.mkdir(parents=True,exist_ok=True); shutil.move(staged,target); target_committed=True
        if operation=='update':
            frozen=plan.get('profile_transition') or {}
            if sorted(plugins,key=str.casefold)!=sorted(frozen.get('plugins',[]),key=str.casefold): raise WorkflowError('Staged plugins differ from the planned transition',3,{'planned':frozen.get('plugins',[]),'staged':plugins})
            finals=frozen['final_files']
            for filename in ('modlist.txt','plugins.txt','loadorder.txt'):
                (profile/filename).write_text('\n'.join(finals[filename])+'\n',encoding='utf-8-sig',newline='\n')
            placement_result=_placement_audit(finals['modlist.txt'],plan['mod_name']); plugin_changes=frozen['plugin_changes']; plugin_states=frozen['plugin_states']
            expected_enabled=bool(plan['existing']['enabled'])
        else:
            placement_result=update_profile(profile,[plan['mod_name']],plugins,selected_placement)
            plugin_changes={'preserved_plugins':[],'new_plugins_disabled':[],'new_plugins_already_present':[], 'removed_plugins':[]}
            plugin_states={name.casefold():'enabled' for name in plugins}; expected_enabled=True
        content_audit=_compare_manifests(expected_manifest,_content_manifest(target))
        if content_audit['status']!='passed':raise WorkflowError('Installed files do not match the staged manifest; installation was rolled back',5,content_audit)
        metadata_audit=None
        if (target/'meta.ini').is_file():
            try:metadata_audit=validate_meta_ini(target/'meta.ini',plan.get('source_metadata'))
            except MetadataError as exc:raise WorkflowError(f'Metadata audit failed: {exc}',5) from exc
        audit=audit_profile(instance,profile,plan['mod_name'],plugin_states,target,expected_enabled,plugin_changes['removed_plugins'])
        plan['profile_audit']=audit
        if audit['status']!='passed':raise WorkflowError('Profile audit failed; installation was rolled back',5,audit)
        plan.update(status='complete',plugins=list(plugins),plugins_enabled=sorted((name for name in plugins if plugin_states.get(name.casefold())=='enabled'),key=str.casefold),
                    target=str(target),staged_validation=validation,metadata=metadata_result,metadata_audit=metadata_audit,
                    plugin_changes=plugin_changes,content_audit=content_audit,final_placement=placement_result,
                    manual_advisory='以下操作为建议操作；如你已有自己的处理方案，无需完全参照或执行。')
        if extracted.exists():shutil.rmtree(extracted,ignore_errors=True)
        atomic_json(tx/'manifest.json',{'status':'complete','plan_id':plan['id'],'snapshots':[str(item[0]) for item in snapshots],
                    'old_mod':str(tx/'old_mod') if old_moved else None,'final_placement':placement_result,
                    'metadata':metadata_result,'plugin_changes':plugin_changes,'content_audit':content_audit})
        atomic_json(plan_path,plan); committed=True
    except Exception:
        if not committed:
            if target_committed and target.exists():shutil.move(target,tx/'failed_mod')
            old=tx/'old_mod'
            if old_moved and old.exists():shutil.move(old,target)
            for destination,backup in snapshots:shutil.copy2(backup,destination)
            plan['status']='rolled_back'; atomic_json(plan_path,plan); atomic_json(tx/'manifest.json',{'status':'rolled_back','plan_id':plan.get('id')})
        raise
    if plan.get('archive_after_install') and plan.get('archive_directory'):
        try:plan['archive_result']=archive_source(archive,Path(plan['archive_directory']),str((plan.get('source_metadata') or {}).get('file_id') or '')); atomic_json(plan_path,plan)
        except Exception as exc:
            plan['status']='installed_with_warnings'; plan['archive_result']={'status':'warning','error':str(exc),'source':str(archive)}; atomic_json(plan_path,plan)
    return plan

def prepare_batch(mod_id:int,file_ids:list[int],download_dir:Path,sessions_dir:Path,open_tabs:bool=True,metadata:list[dict[str,Any]]|None=None)->dict[str,Any]:
    session_id=datetime.now().strftime('%Y%m%d-%H%M%S-')+uuid.uuid4().hex[:8]; metadata=metadata or []
    records=[]; seen=set()
    if metadata:
        inputs=metadata
    else:inputs=[{'mod_id':mod_id,'file_id':fid} for fid in file_ids]
    for meta in inputs:
        mid=int(meta.get('mod_id') or mod_id); fid=int(meta.get('file_id')); key=(mid,fid)
        if key in seen:continue
        seen.add(key)
        records.append({'mod_id':mid,'file_id':fid,'file_name':meta.get('file_name',''),'name':meta.get('name',''),'size_in_bytes':meta.get('size_in_bytes') or meta.get('expected_size_bytes') or (int(meta.get('size_kb',0))*1024 if meta.get('size_kb') else None),'version':meta.get('version',''),'category_id':meta.get('category_id'),'url':f'https://www.nexusmods.com/skyrimspecialedition/mods/{mid}?tab=files&file_id={fid}','status':'missing'})
    data={'schema_version':1,'id':session_id,'mod_id':mod_id,'download_directory':str(download_dir.resolve()),'files':records,'status':'awaiting_downloads'}
    atomic_json(sessions_dir/f'{session_id}.json',data)
    if open_tabs:
        import webbrowser
        for item in records:webbrowser.open_new_tab(item['url'])
    return data

def _normalized_name(value:str)->str:
    return re.sub(r'[^a-z0-9]+','',Path(value).name.casefold())

def collect_batch(session_path:Path)->dict[str,Any]:
    data=json.loads(session_path.read_text(encoding='utf-8')); folder=Path(data['download_directory'])
    candidates=[p for p in folder.iterdir() if p.is_file() and p.suffix.casefold() in ARCHIVE_SUFFIXES and not any(p.name.casefold().endswith(s) for s in PARTIAL_SUFFIXES)] if folder.is_dir() else []
    used=set()
    for item in data['files']:
        scored=[]; expected_name=item.get('file_name',''); expected_size=item.get('size_in_bytes'); fid=str(item['file_id'])
        for path in candidates:
            if path in used:continue
            score=0
            if expected_name and path.name.casefold()==Path(expected_name).name.casefold():score+=100
            elif expected_name and _normalized_name(path.name)==_normalized_name(expected_name):score+=80
            if expected_size:
                delta=abs(path.stat().st_size-int(expected_size)); tolerance=max(4096,int(expected_size)*0.01)
                if delta<=tolerance:score+=40
                elif delta>max(1024*1024,int(expected_size)*0.1):continue
            if re.search(rf'(?<!\d){re.escape(fid)}(?!\d)',path.name):score+=10
            if score:scored.append((score,path))
        if scored:
            best=max(x[0] for x in scored); matches=[p for score,p in scored if score==best]
        else:matches=[]
        if len(matches)==1:item.update(status='collected',path=str(matches[0]),sha256=sha256(matches[0]),match_score=best); used.add(matches[0])
        elif len(matches)>1:item.update(status='ambiguous',candidates=[str(p) for p in matches])
        else:item['status']='missing'
    data['status']='collected' if all(x['status']=='collected' for x in data['files']) else 'review'
    atomic_json(session_path,data); return data

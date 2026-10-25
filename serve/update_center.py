"""Bounded official-source checks and verified staging. Never mutates installed runtimes."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

ENVIRONMENT_INVENTORY_VERSION = 3

SOURCES = {'colibri':'JustVugg/colibri','pytorch':'pytorch/pytorch', 'strata': 'Niko1221/Strata', 'transformers':'huggingface/transformers', 'airllm':'lyogavin/airllm', 'voicestudio':'debpalash/VoiceStudio', 'llama.cpp': 'unslothai/llama.cpp',
           'unsloth': 'unslothai/unsloth', 'soup': 'MakazhanAlpamys/Soup',
           'whisper.cpp': 'unslothai/whisper.cpp','audio.cpp':'unslothai/audio.cpp','opencode':'anomalyco/opencode','dsh':'deepseek-ai/deepseek-harness','trueforge':'truefoundry/trueforge','browser':'microsoft/playwright-mcp','memory':'modelcontextprotocol/servers','hermes':'NousResearch/hermes-agent','claude':'anthropics/claude-code'}

def file_sha256(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as source:
        while block:=source.read(1024*1024):digest.update(block)
    return digest.hexdigest()

def source_fingerprint(root):
    digest=hashlib.sha256();root=Path(root)
    for path in sorted([*root.glob('serve/*.py'),*root.glob('tools/*.py')]):
        digest.update(path.relative_to(root).as_posix().encode());digest.update(b'\0');digest.update(path.read_bytes())
    return digest.hexdigest()

def whisper_cpu_dependencies(destination,asset_name):
    """Use the new bundle's declared pairing, never an arbitrary installed DLL set."""
    destination=Path(destination).resolve()
    servers=list(destination.rglob('whisper-server.exe'))
    if len(servers)!=1:raise ValueError('Whisper slim server is ambiguous')
    metadata=list(destination.rglob('UNSLOTH_WHISPER_PREBUILT_INFO.json'))
    if len(metadata)!=1:raise ValueError('Whisper pairing metadata is missing or ambiguous')
    info=json.loads(metadata[0].read_text(encoding='utf-8'))
    if info.get('source_repo')!='unslothai/whisper.cpp' or not asset_name.endswith(info.get('asset_name','!missing')) or info.get('os')!='windows' or info.get('arch')!='x64':
        raise ValueError('Whisper metadata does not match the official host package')
    tag=info.get('requires_llama_tag')
    if not isinstance(tag,str) or not tag or '/' in tag or '\\' in tag:raise ValueError('Whisper requires an explicit llama.cpp pairing')
    source=None;names=[]
    # Prefer an intact isolated official CPU bundle with the exact required tag.
    for record in sorted(destination.parent.glob('*/CANDIDATE-MANIFEST.json')):
        if record.is_symlink():continue
        try:
            manifest=json.loads(record.read_text(encoding='utf-8'))
            url=manifest.get('source','')
            if not url.startswith('https://github.com/unslothai/llama.cpp/releases/download/'+tag+'/') or not url.endswith('windows-x64-cpu.zip'):continue
            base=record.parent.resolve()
            if not base.is_relative_to(destination.parent):continue
            files=manifest.get('files',[])
            if not files:continue
            for row in files:
                path=(base/row['path']).resolve()
                if not path.is_relative_to(base) or path.is_symlink() or not path.is_file() or path.stat().st_size!=row['bytes'] or file_sha256(path)!=row['sha256']:
                    raise ValueError('Paired llama.cpp candidate has changed')
            binaries=list(base.rglob('llama-server.exe'))
            if len(binaries)!=1:raise ValueError('Paired CPU server is ambiguous')
            source=binaries[0].parent
            names=[path.name for path in source.glob('*.dll')]
            break
        except (OSError,KeyError,TypeError):continue
    if source is None:
        installed=Path.home()/'.unsloth/whisper.cpp/UNSLOTH_WHISPER_PREBUILT_INFO.json'
        paired=Path.home()/'.unsloth/llama.cpp'
        old=json.loads(installed.read_text(encoding='utf-8'))
        llama=json.loads((paired/'UNSLOTH_PREBUILT_INFO.json').read_text(encoding='utf-8'))
        if tag!=(llama.get('release_tag') or llama.get('tag')) or old.get('paired_llama_tag')!=tag or old.get('paired_llama_ggml_tree')!=info.get('requires_ggml_tree'):
            raise ValueError('Prepare the official Windows x64 CPU llama.cpp '+tag+' package first; Whisper requires its exact GGML libraries')
        source=paired/'build/bin/Release';names=old.get('linked_libraries',[])
    names=[name for name in names if isinstance(name,str) and (name in ('ggml-base.dll','ggml.dll','libomp140.x86_64.dll') or name.startswith('ggml-cpu-') and name.endswith('.dll'))]
    if any(Path(name).name!=name for name in names):raise ValueError('Invalid dependency filename')
    required=info.get('requires_ggml_sonames',[])
    if 'ggml-base.dll' not in names or not any(name.startswith('ggml-cpu-') for name in names) or any(name not in names for name in required):
        raise ValueError('Exact paired CPU dependencies are unavailable')
    total=sum((source/name).stat().st_size for name in names)
    if total>128*1024**2 or shutil.disk_usage(destination).free<total+1024**3:raise ValueError('Insufficient reserve or oversized Whisper dependencies')
    rows=[]
    for name in names:
        target=servers[0].parent/name;digest=file_sha256(source/name)
        if target.exists() and file_sha256(target)!=digest:raise ValueError('Whisper candidate contains a conflicting GGML library')
        if not target.exists():shutil.copyfile(source/name,target)
        if file_sha256(target)!=digest:raise ValueError('Paired CPU dependency changed during copy')
        rows.append({'path':target.relative_to(destination).as_posix(),'bytes':target.stat().st_size,'sha256':digest})
    return {'files':rows,'paired_llama_tag':tag,'device':'cpu','dependency_source':str(source)}


class UpdateCenter:
    def __init__(self, root, port=None):
        self.root = Path(root)
        self.port = port
        from serve.harness_updates import HarnessUpdates
        self.harness_updates=HarnessUpdates(self.root)
        self.folder = self.root / 'output' / 'updates'
        self.lock = threading.RLock()
        self.cancel_download = threading.Event()
        self.result = {'checked_at': None, 'components': [], 'state': 'idle'}
        self.job = {'state': 'idle'}
        self.cache = self.root / 'data' / 'update-check.json'
        self.job_path=self.root/'data/update-job.json'
        try:
            saved=json.loads(self.job_path.read_text(encoding='utf-8')) if os.environ.get('STRATA_PYTHON_CANDIDATE_PROBE')!='1' else {}
            if not isinstance(saved,dict) or saved.get('state') not in ('idle','downloading','preparing','validating','staged','prepared','validated','activated_cpu','selected_strata','selected_colibri','rolled_back','failed','cancelled','interrupted','resolving','resolved','resolution_failed','installing_candidate','candidate_installed','candidate_failed','validating_python'):
                raise ValueError('Invalid persisted update state')
            self.job=saved
            import psutil
            owner_alive=type(saved.get('owner_pid')) is int and psutil.pid_exists(saved['owner_pid'])
            if saved['state'] in ('downloading','preparing','validating','resolving','installing_candidate','validating_python') and not owner_alive:
                if saved['state']=='downloading' and saved.get('download_path'):
                    import psutil
                    owner=saved.get('owner_pid')
                    target=Path(saved['download_path']).resolve()
                    # Only a dead worker's known temporary file can be removed.
                    if type(owner) is int and owner!=os.getpid() and not psutil.pid_exists(owner) and target.parent==self.folder.resolve():
                        partial=target.with_name(target.name+'.partial')
                        if partial.is_file() and not partial.is_symlink():
                            try:
                                size=partial.stat().st_size;partial.unlink();self.job['removed_partial_bytes']=size
                            except OSError as error:self.job['partial_cleanup_error']=str(error)
                self.job.update(state='prepared' if saved['state']=='validating' else 'staged' if saved['state']=='preparing' else 'interrupted',error='Previous operation was interrupted; no automatic execution or activation',recovered_at=time.time())
                self._persist_job()
        except (OSError,ValueError):pass
        self.installed_provider = lambda: {}
        self.operational_idle = lambda: False
        self.configuration_provider=lambda:None
        from serve.dependency_supervisor import DependencySupervisor
        self.dependency_supervisor=DependencySupervisor(self.root)
        try:
            data = json.loads(self.cache.read_text(encoding='utf-8'))
            if isinstance(data.get('components'), list):
                self.result = data
                for environment in self.result.get('environments',[]):
                    if environment.get('name')=='Strata' and Path(environment.get('python','')).resolve()!=Path(sys.executable).resolve():
                        refresh_running_environment(environment,sys.executable)
                        self.result['shared_libraries']=shared_libraries(self.result['environments'])
        except (OSError, ValueError, AttributeError): pass

    def _sync_shared_job(self):
        if os.environ.get('STRATA_PYTHON_CANDIDATE_PROBE')=='1':return
        active=('downloading','preparing','validating','resolving','installing_candidate','validating_python')
        if self.job.get('state') in active and self.job.get('owner_pid')==os.getpid():return
        try:
            saved=json.loads(self.job_path.read_text(encoding='utf-8'))
            if isinstance(saved,dict) and saved.get('state'):
                with self.lock:self.job=saved
        except (OSError,ValueError):pass

    def _persist_job(self):
        from serve.configuration import atomic_json
        try:
            self.job_path.parent.mkdir(parents=True,exist_ok=True)
            atomic_json(self.job_path,self.job)
            self.job.pop('persistence_error',None)
        except OSError as error:self.job['persistence_error']=str(error)

    def status(self):
        self._sync_shared_job()
        protection=None
        try:
            info=json.loads((self.root/'data/customization-backup-last.json').read_text(encoding='utf-8'))
            archive=Path(info['archive']).resolve()
            if archive.is_relative_to((self.folder/'backups').resolve()) and archive.is_file():protection=info
        except (OSError,ValueError,KeyError,TypeError):pass
        with self.lock:
            result=json.loads(json.dumps({**self.result, 'download': self.job,
                'customization_backup':protection,
                'activation': 'validated_llama_cpu_only', 'installed_runtimes_modified': False}))
        try:result['runtime_selection']=json.loads((self.root/'data/runtime-selection.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):result['runtime_selection']=None
        try:result['dashboard_python_selection']=json.loads((self.root/'data/dashboard-python-selection.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):result['dashboard_python_selection']=None
        try:result['audio_python_selection']=json.loads((self.root/'data/audio-python-selection.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):result['audio_python_selection']=None
        try:result['document_python_selection']=json.loads((self.root/'data/document-python-selection.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):result['document_python_selection']=None
        try:result['visual_python_selection']=json.loads((self.root/'data/visual-python-selection.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):result['visual_python_selection']=None
        try:result['inference_python_selection']=json.loads((self.root/'data/inference-python-selection.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):result['inference_python_selection']=None
        candidate=result.get('download',{}).get('result',{})
        result['python_candidate_validation_current']=bool(not result.get('download',{}).get('error') and candidate.get('dashboard_start_verified') and candidate.get('server_suite',{}).get('passed') and candidate.get('core_source_sha256')==source_fingerprint(self.root))
        try:result['audio_runtime_selection']=json.loads((self.root/'data/audio-runtime-selection.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):result['audio_runtime_selection']=None
        try:result['whisper_runtime_selection']=json.loads((self.root/'data/whisper-runtime-selection.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):result['whisper_runtime_selection']=None
        try:
            from serve.soup_runtime import selected_package
            soup=selected_package(self.root)
            result['soup_package_selection']={'version':soup['version'],'cpu_verified':True,'gpu_verified':soup['validation'].get('gpu_verified')} if soup else None
        except (OSError,ValueError,KeyError):result['soup_package_selection']=None
        try:
            gpu_registry=json.loads((self.root/'data/runtime-gpu-selection.json').read_text(encoding='utf-8'))
            result['llama_gpu_runtime_selection']={key:{field:value.get(field) for field in ('binary','directory','scope','version','activated_at')} if isinstance(value,dict) else None for key,value in gpu_registry.items() if key in ('active','previous')}
        except (OSError,ValueError):result['llama_gpu_runtime_selection']=None
        try:
            from serve.llama_gpu_update import proof
            result['llama_gpu_candidate_validated']=self.job.get('component')=='llama.cpp' and bool(proof(self.root,self.job.get('result') or {}))
        except (OSError,ValueError,KeyError,TypeError):result['llama_gpu_candidate_validated']=False
        result['harness_update']=self.harness_updates.status()
        installed=self.installed_versions()
        known={row.get('id') for row in result.get('components',[])}
        for component,repository in SOURCES.items():
            if component not in known:
                result.setdefault('components',[]).append({'id':component,'repository':repository,
                    'state':'not_checked','version':None,'assets':[],
                    'release_url':'https://github.com/'+repository+'/releases'})
        for row in result.get('components',[]):
            for asset in row.get('assets',[]):asset['platform_compatibility']=platform_compatibility(asset.get('name',''))
            row.update(installed.get(row['id'],{'installed_version':None,'installed_source':'unavailable'}))
            row['package_selection']=recommend_package(row)
            if row.get('repository')!=SOURCES.get(row['id']):
                row.update(state='source_changed',version=None,assets=[],release_url=None,
                           error='Run a check against the installed runtime source')
        try:result['strata_runtime_selection']=json.loads((self.root/'data/strata-runtime-selection.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):result['strata_runtime_selection']=None
        from serve.strata_update import candidate_proof
        result['strata_candidate_validation_current']=bool(not self.job.get('error') and self.job.get('component')=='strata' and candidate_proof(self.root,self.job.get('result') or {}))
        from serve.component_notifications import newer
        for row in result.get('components',[]):
            if row['id']=='colibri':
                supported=row.get('installed_backend') in ('vulkan','cpu','cuda') and bool(row.get('package_selection',{}).get('asset_id'))
                row.update(automatic_update_supported=supported,update_block_reason=None if supported else 'compatible_package_unavailable')
            if row['id'] in ('unsloth','voicestudio'):
                row.update(automatic_update_supported=False,update_block_reason='desktop_installer_not_integrated')
            if row['id']=='soup':
                row.update(automatic_update_supported=str(row.get('version','')).removeprefix('v')=='0.76.0',update_block_reason=None if str(row.get('version','')).removeprefix('v')=='0.76.0' else 'release_requires_training_validation')
            if row['id']=='transformers' and any(e.get('name')=='Unsloth' and any(p.get('name','').lower()=='torch' and 'rocm' in p.get('version','').lower() for p in e.get('packages',[])) for e in result.get('environments',[])):
                from serve.transformers_compatibility import cached
                row.update(cached(self.root,row))
                row.update(automatic_update_supported=bool(row.get('compatible_release')),update_block_reason=None if row.get('compatible_release') else 'vendor_dependencies_require_validation',vendor_preserving_update=True)
            installed_version=row.get('installed_version');available=row.get('version')
            comparable=row.get('version_comparable') is not False and installed_version and available
            row['update_state']=('available' if comparable and newer(installed_version,available) else
                'ahead' if comparable and newer(available,installed_version) else
                'current' if comparable and str(installed_version).removeprefix('v')==str(available).removeprefix('v') else 'unknown')
        job=result.get('download') or {};directory=(job.get('result') or {}).get('candidate_directory')
        active=(result.get('llama_gpu_runtime_selection') or {}).get('active') or {}
        result['update_features']={'single_component_dependencies':True,'dependency_supervisor':True}
        result['dependency_health']=self.dependency_supervisor.status()
        result['operation_state']='selected_gpu' if job.get('component')=='llama.cpp' and directory and active.get('directory')==directory and result['llama_gpu_candidate_validated'] else job.get('state','idle')
        return result

    def check_dependency_health(self):
        self.dependency_supervisor.scan(sys.executable,self.configuration_provider())
        return self.status()

    def repair_hydra_assets(self):
        if not self.operational_idle():raise ValueError('Stop active engines before HYDRA recovery')
        from serve.hydra_execution_v10 import admission_status
        if admission_status().get('state') not in ('IDLE','RELEASED'):raise ValueError('HYDRA execution is active or ownership is unknown')
        from serve.hydra_recovery import restore_missing
        result=restore_missing(self.root)
        from serve.configuration import atomic_json
        atomic_json(self.root/'data/hydra-recovery-last.json',result)
        if result['changed'] or result['missing']:raise ValueError('HYDRA custom or unavailable files preserved; inspect recovery report')
        return result

    def repair_core_dependencies(self):
        from serve.dependency_supervisor import prepare_core_repair
        return prepare_core_repair(self)

    def activate_llama_gpu(self):
        from serve.llama_gpu_update import activate
        if not self.operational_idle():raise ValueError('Stop active engines before GPU selection')
        with self.lock:
            if self.job.get('component')!='llama.cpp' or self.job.get('state') not in ('prepared','validated','rolled_back'):raise ValueError('Prepare the validated GPU candidate first')
            activate(self.root,self.job['result'])
            from serve.native_libraries import inventory
            self.result['native_libraries']=inventory(self.root)
        return self.status()

    def rollback_llama_gpu(self):
        from serve.llama_gpu_update import rollback
        if not self.operational_idle():raise ValueError('Stop active engines before GPU rollback')
        with self.lock:
            rollback(self.root)
            from serve.native_libraries import inventory
            self.result['native_libraries']=inventory(self.root)
        return self.status()

    def activate_soup(self):
        from serve.soup_runtime import activate_package
        if not self.operational_idle():raise ValueError('Stop active engines before activation')
        with self.lock:
            version=self.job.get('version') if self.job.get('component')=='soup' and self.job.get('state') in ('prepared','validated') else '0.75.2'
            activate_package(self.root,version)
            self.job.update(state='validated',component='soup',version=version)
            self._persist_job()
        return self.status()

    def prepare_soup(self,version):
        from serve.soup_update import VERSION
        version=str(version or '').removeprefix('v')
        if version!=VERSION:raise ValueError('Unsupported Soup update version')
        if not self.operational_idle():raise ValueError('Stop active engines before Soup update')
        self._sync_shared_job()
        with self.lock:
            if self.job.get('state') in ('downloading','preparing','validating','resolving','installing_candidate','validating_python'):raise ValueError('Another update is already running')
            self.job={'component':'soup','version':version,'state':'downloading','owner_pid':os.getpid(),'started_at':time.time()}
            self._persist_job()
        threading.Thread(target=self._prepare_soup,args=(version,),daemon=True).start()
        return self.status()

    def _prepare_soup(self,version):
        from serve.soup_update import prepare
        from serve.customization_backup import snapshot
        def progress(**fields):
            with self.lock:self.job.update(fields);self._persist_job()
        try:
            if not self.operational_idle():raise ValueError('Stop active engines before Soup update')
            backup=snapshot(self.root);progress(backup=backup)
            result=prepare(self.root,version,progress)
            progress(state='prepared',result=result,error=None)
        except Exception as error:progress(state='failed',error=str(error))
    def rollback_soup(self):
        from serve.soup_runtime import rollback_package
        if not self.operational_idle():raise ValueError('Stop active engines before rollback')
        with self.lock:rollback_package(self.root)
        return self.status()
    def installed_versions(self):
        from serve.transformers_integration import installed_metadata
        result={'transformers':installed_metadata(self.result.get('environments',[]))}
        try:
            selected=json.loads((self.root/'data/inference-python-selection.json').read_text(encoding='utf-8')).get('active')
            if selected:
                folder=Path(selected['plan_directory']).resolve()
                if folder.is_relative_to((self.folder/'python-plans').resolve()):
                    manifest=json.loads((folder/'environment-manifest.json').read_text(encoding='utf-8'))
                    if manifest.get('inference_validation',{}).get('gpu_verified'):
                        result['transformers'].update(installed_version=manifest['source_packages']['transformers'],installed_source='selected_isolated_gpu_python_distribution',inference_environment='Selected Unsloth runtime',version_comparable=True)
        except (OSError,ValueError,KeyError,TypeError):pass
        from serve.pytorch_integration import installed_metadata as pytorch_metadata
        result['pytorch']=pytorch_metadata(self.result.get('environments',[]))
        from serve.airllm_runtime import status as airllm_status
        airllm=airllm_status(self.root)
        result['airllm']={'installed_version':airllm.get('version') if airllm['installed'] else None,
                          'installed_source':'isolated_cpu_distribution_metadata',
                          'runtime_validated':False}
        try:
            config=json.loads((self.root/'data/colibri/setup.json').read_text(encoding='utf-8'))
            source=str(config.get('engine_source',''))
            version=source.removeprefix('release ').strip() if source.startswith('release ') else None
            result['colibri']={'installed_version':version,'installed_source':'official_isolated_colibri_runtime','runtime_validated':False,'installed_backend':config.get('backend')}
        except (OSError,ValueError,TypeError):result['colibri']={'installed_version':None,'installed_source':'not_installed'}
        from serve.voicestudio import desktop_inventory
        result['voicestudio']=desktop_inventory()
        try:
            info=json.loads((self.root/'engine/BUILD.json').read_text(encoding='utf-8'))
            result['strata']={'installed_version':info.get('version'),'installed_source':'local_build_manifest','installed_backend':info.get('backend'),'installed_asset':info.get('asset')}
        except (OSError,ValueError,AttributeError):pass
        try:
            active=json.loads((self.root/'data/strata-runtime-selection.json').read_text(encoding='utf-8')).get('active') or {}
            configuration=Path(active.get('config',''))
            if active.get('version') and configuration.is_file() and file_sha256(configuration)==active.get('config_sha256'):
                selected=json.loads(configuration.read_text(encoding='utf-8-sig'))
                executable=Path(selected.get('exe','')).resolve()
                if executable==Path(active['directory']).resolve()/'strata.exe' and executable.is_file():
                    result['strata'].update(installed_version=active['version'],installed_source='verified_selected_configuration')
        except (OSError,ValueError,KeyError,TypeError):pass
        for component,folder,marker in [('llama.cpp','llama.cpp','UNSLOTH_PREBUILT_INFO.json'),('whisper.cpp','whisper.cpp','UNSLOTH_WHISPER_PREBUILT_INFO.json')]:
            try:
                info=json.loads((Path.home()/'.unsloth'/folder/marker).read_text(encoding='utf-8'))
                result[component]={'installed_version':info.get('release_tag') or info.get('tag'),
                    'installed_source':'installed_package_manifest','installed_repository':info.get('published_repo'),
                    'installed_backend':info.get('backend'),'installed_asset':info.get('asset'),'installed_gpu_target':info.get('gfx_target'),'paired_llama_tag':info.get('paired_llama_tag'),'linked_libraries':info.get('linked_libraries',[])}
            except (OSError,ValueError,AttributeError):pass
        try:
            info=json.loads((Path.home()/'.unsloth/audio.cpp/UNSLOTH_AUDIO_CPP_PREBUILT_INFO.json').read_text(encoding='utf-8'))
            result['audio.cpp']={'installed_version':info.get('release_tag'),'installed_source':'installed_package_manifest','installed_repository':info.get('published_repo'),'installed_backend':info.get('backend'),'installed_asset':info.get('asset')}
        except (OSError,ValueError,AttributeError):pass
        for environment in self.result.get('environments',[]):
            packages={p['name'].lower():p['version'] for p in environment.get('packages',[])}
            if environment['name']=='Unsloth' and 'unsloth' in packages:
                # Studio release tags and the Python inference library are separate products.
                result['unsloth']={'installed_version':None,'installed_runtime_version':packages['unsloth'],
                    'installed_source':'studio_version_not_detected','version_comparable':False}
            if environment['name']=='Soup':
                version=packages.get('soup-cli') or packages.get('soup_cli') or packages.get('soup')
                if version:result['soup']={'installed_version':version,'installed_source':'python_distribution_metadata'}
        try:
            from serve.soup_runtime import selected_package
            soup=selected_package(self.root)
            if soup:result['soup']={'installed_version':soup['version'],'installed_source':'selected_isolated_python_package'}
        except (OSError,ValueError,KeyError):pass
        from serve.studio_inventory import installed_studio
        studio=installed_studio()
        if studio:result['unsloth']={**result.get('unsloth',{}),**studio}
        for component,registry_name in [('audio.cpp','audio-runtime-selection.json'),('whisper.cpp','whisper-runtime-selection.json'),('llama.cpp','runtime-selection.json'),('llama.cpp','runtime-gpu-selection.json')]:
            try:
                selection=json.loads((self.root/'data'/registry_name).read_text(encoding='utf-8')).get('active')
                if selection:
                    directory=Path(selection['directory']).resolve()
                    if not directory.is_relative_to((self.root/'output/updates/candidates').resolve()):continue
                    marker={'audio.cpp':'UNSLOTH_AUDIO_CPP_PREBUILT_INFO.json','whisper.cpp':'UNSLOTH_WHISPER_PREBUILT_INFO.json','llama.cpp':'UNSLOTH_PREBUILT_INFO.json'}[component]
                    metadata_path=directory/marker
                    metadata=json.loads(metadata_path.read_text(encoding='utf-8')) if metadata_path.is_file() else {}
                    version=selection.get('version') or metadata.get('release_tag') or metadata.get('tag')
                    result[component]={**result.get(component,{}),'installed_version':version,'installed_source':'selected_candidate_manifest','installed_backend':'rocm' if selection.get('scope')=='llama_gpu' else metadata.get('backend')}
            except (OSError,ValueError,KeyError,TypeError):pass
        try:
            for component,metadata in self.installed_provider().items():
                result[component]={**result.get(component,{}),**metadata}
        except Exception:pass
        from serve.harness_updates import installed,selected
        for kind in ('opencode','dsh','trueforge','browser','memory','hermes','claude'):
            active=selected(self.root,kind,verify=False)
            result[kind]={'installed_version':active['version'] if active else installed(self.root,kind),'installed_source':'official_native_binary' if kind=='claude' else 'official_npm_package'}
        return result

    def check(self):
        with self.lock:
            if self.result['state'] == 'checking': return self.status_unlocked()
            if self.result.get('environment_inventory_version')==ENVIRONMENT_INVENTORY_VERSION and self.result.get('checked_at') and 'runtimes' in self.result and 'environments' in self.result and self.result.get('library_updates_checked') and 'native_libraries' in self.result and all('dependency_health' in e for e in self.result['environments']) and set(r.get('id') for r in self.result['components'])==set(SOURCES) and all(r.get('repository')==SOURCES.get(r['id']) for r in self.result['components']) and time.time()-self.result['checked_at'] < 3600:
                return self.status_unlocked()
            self.result['state'] = 'checking'
        threading.Thread(target=self._check, daemon=True).start()
        return self.status()

    def status_unlocked(self):
        return json.loads(json.dumps({**self.result, 'download': self.job}))

    def _check(self):
        rows = []
        for component, repo in SOURCES.items():
            row = {'id': component, 'repository': repo, 'url': 'https://github.com/'+repo}
            try:
                if component=='pytorch':
                    from serve.pytorch_integration import latest
                    rows.append(latest());continue
                if component=='transformers':
                    from serve.transformers_compatibility import latest
                    rows.append(latest(self.root));continue
                if component=='airllm':
                    from serve.airllm_updates import latest
                    rows.append(latest());continue
                if component in ('opencode','dsh','trueforge','browser','memory','hermes','claude'):
                    from serve.harness_updates import latest
                    rows.append(latest(component));continue
                req = urllib.request.Request('https://api.github.com/repos/'+repo+'/releases/latest',
                    headers={'Accept':'application/vnd.github+json', 'User-Agent':'Strata-Update-Center'})
                with urllib.request.urlopen(req, timeout=15) as response:
                    raw = response.read(2*1024*1024+1)
                if len(raw)>2*1024*1024: raise ValueError('Release metadata exceeds limit')
                release = json.loads(raw)
                row.update(version=release['tag_name'], released_at=release.get('published_at'),
                    release_url=release['html_url'], notes=release.get('body','')[:16000],
                    assets=[{'id':a['id'], 'name':a['name'], 'bytes':a['size'],
                        'url':a['browser_download_url'], 'digest':a.get('digest')}
                        for a in release.get('assets',[])[:100]], state='available')
            except Exception as error: row.update(state='unavailable', error=str(error), assets=[])
            rows.append(row)
        from serve.python_inference_update import selected_python
        inference_selection_error=None
        try:inference_python=selected_python(self.root,Path.home()/'.unsloth/studio/unsloth_studio/Scripts/python.exe')
        except (OSError,ValueError,KeyError) as error:
            inference_selection_error=str(error);inference_python=Path.home()/'.unsloth/studio/unsloth_studio/Scripts/python.exe'
        from serve.audio_python_update import selected_python as audio_python
        audio_default=self.root/'tools/local-generative-audio/.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
        audio_error=None
        try:audio_executable=audio_python(self.root,audio_default)
        except (OSError,ValueError,KeyError) as error:audio_executable=audio_default;audio_error=str(error)
        from serve.open_webui_runtime import python_executable as document_python,directory as document_directory
        document_error=None
        try:document_executable=document_python(self.root)
        except (OSError,ValueError,KeyError) as error:document_executable=document_directory(self.root)/'venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python');document_error=str(error)
        from serve.visual_python_update import selected_python as visual_python
        visual_default=self.root/'data/visual-runtime'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
        if not visual_default.is_file():visual_default=inference_python
        visual_error=None
        try:visual_executable=visual_python(self.root,visual_default)
        except (OSError,ValueError,KeyError) as error:visual_executable=visual_default;visual_error=str(error)
        environments=[]
        from serve.airllm_runtime import selected_python as airllm_python
        try:airllm_executable=airllm_python(self.root)
        except ValueError:airllm_executable=self.root/'output/updates/airllm-runtime/not-installed.exe'
        for name, executable in [('Strata',Path(sys.executable)),
                ('Unsloth',inference_python),
                ('AirLLM',airllm_executable),
                ('VoiceStudio',Path.home()/'AppData/Roaming/VoiceStudio/runtime/project/.venv/Scripts/python.exe'),
                ('Soup',self.root/'.venv-soup/Scripts/python.exe'),
                ('Audio generativo',audio_executable),
                ('Open WebUI',document_executable),('Visuale',visual_executable)]:
            if not executable.is_file():continue
            environment={'name':name,'python':str(executable)}
            if name=='Audio generativo' and audio_error:environment['selection_error']=audio_error
            if name=='Open WebUI' and document_error:environment['selection_error']=document_error
            if name=='Visuale' and visual_error:environment['selection_error']=visual_error
            try:
                script="import importlib.metadata as m,json,sys;print(json.dumps({'python_version':sys.version.split()[0],'packages':sorted([{'name':d.metadata['Name'],'version':d.version} for d in m.distributions() if d.metadata['Name']],key=lambda d:d['name'].lower())}))"
                process=subprocess.run([str(executable),'-I','-c',script],capture_output=True,text=True,timeout=20,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                if process.returncode or len(process.stdout)>1024*1024:raise ValueError('Package inventory failed')
                environment.update(json.loads(process.stdout));environment['state']='inventoried'
                environment['dependency_health']=check_dependencies(executable)
            except Exception as error:environment.update(state='unavailable',error=str(error))
            environments.append(environment)
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=3) as pool:
            checks=list(pool.map(lambda environment: library_updates(environment['python']),environments))
        for environment,check in zip(environments,checks):
            environment['update_check']=check
            updates={normalize_package(row['name']):row for row in check.get('outdated',[])}
            for package in environment.get('packages',[]):
                match=updates.get(normalize_package(package['name']))
                package['available_version']=match['latest_version'] if match else package['version'] if check['state']=='checked' else None
                package['update_state']='available' if match else 'current' if check['state']=='checked' else 'unavailable'
        shared=shared_libraries(environments)
        from serve.native_libraries import inventory
        native=inventory(self.root)
        from serve.runtime_updates import inventory as runtime_inventory
        runtimes=runtime_inventory(self.root,environments,native)
        with self.lock:
            self.result={'environment_inventory_version':ENVIRONMENT_INVENTORY_VERSION,'inference_selection_error':inference_selection_error,'library_updates_checked':True,'shared_libraries':shared,'native_libraries':native,'runtimes':runtimes,'checked_at':time.time(),'components':rows,'environments':environments,'state':'complete'}
            self.cache.parent.mkdir(parents=True, exist_ok=True)
            tmp=self.cache.with_suffix('.tmp');tmp.write_text(json.dumps(self.result),encoding='utf-8');tmp.replace(self.cache)

    def stage(self, component, asset_id):
        reused=False
        with self.lock:
            if self.job['state'] in ('downloading','preparing','validating','resolving','installing_candidate','validating_python'): raise ValueError('An update operation is already running')
            row=next((r for r in self.result['components'] if r['id']==component),None)
            asset=next((a for a in (row or {}).get('assets',[]) if a['id']==asset_id),None)
            if not asset: raise ValueError('Check official releases and select a listed asset')
            if row.get('repository') != SOURCES.get(component):
                raise ValueError('Release source does not match the installed runtime family')
            compatible=platform_compatibility(asset.get('name',''))
            if compatible['state']=='incompatible':raise ValueError(compatible['reason'])
            digest=asset.get('digest') or ''
            if not digest.startswith('sha256:') or len(digest)!=71 or any(c not in '0123456789abcdef' for c in digest[7:]):
                raise ValueError('The publisher has not provided a SHA-256 digest; automatic staging is disabled')
            name=asset['name']
            if Path(name).name!=name or '/' in name or '\\' in name or ':' in name:
                raise ValueError('Invalid release filename')
            size=asset['bytes']
            if not 0<size<=2*1024**3: raise ValueError('Asset size exceeds the 2 GiB staging limit')
            if not asset['url'].startswith('https://github.com/'+SOURCES[component]+'/releases/download/'):
                raise ValueError('Asset does not belong to the official release')
            self.folder.mkdir(parents=True,exist_ok=True)
            if shutil.disk_usage(self.folder).free<size+1024**3: raise ValueError('Insufficient disk space plus 1 GiB reserve')
            target=self.folder / (digest[7:19]+'-'+name)
            import os
            if target.exists():
                if target.is_symlink() or target.stat().st_size!=size or file_sha256(target)!=digest[7:]:raise ValueError('Existing staged copy failed integrity verification')
                manifest=json.loads(target.with_name(target.name+'.json').read_text(encoding='utf-8'))
                if manifest.get('sha256')!=digest[7:] or manifest.get('source')!=asset['url']:raise ValueError('Existing staged copy provenance differs')
                manifest['published_version']=row.get('version')
                self.job={'state':'staged','component':component,'version':row.get('version'),'name':name,'bytes':size,'total':size,'result':manifest,'reused_verified_copy':True,'owner_pid':os.getpid()}
                reused=True
            else:self.job={'state':'downloading','component':component,'name':name,'version':row.get('version'),'bytes':0,'total':size,'started_at':time.time(),'download_path':str(target.resolve()),'owner_pid':os.getpid()}
            self._persist_job()
            self.cancel_download.clear()
        if not reused:threading.Thread(target=self._download,args=(asset,target),daemon=True).start()
        return self.status()

    def prepare(self):
        """Extract the verified ZIP into a new isolated directory, never into live code."""
        import os
        import stat
        import uuid
        import zipfile
        with self.lock:
            if self.job.get('state')!='staged':raise ValueError('Stage a verified release first')
            manifest=dict(self.job['result'])
            target=Path(manifest['path']).resolve()
            if not target.is_relative_to(self.folder.resolve()) or not target.is_file():
                raise ValueError('Candidate path is outside the update folder')
            if target.suffix.lower()!='.zip':raise ValueError('Isolated preparation currently supports ZIP releases')
            if file_sha256(target)!=manifest['sha256']:
                raise ValueError('Staged archive has changed; preparation rejected')
            # Reuse only intact isolated copies of this exact official archive.
            candidates=self.folder/'candidates'
            for record in sorted(candidates.glob('*/CANDIDATE-MANIFEST.json')):
                try:
                    if record.is_symlink() or record.stat().st_size>4*1024**2:continue
                    saved=json.loads(record.read_text(encoding='utf-8'))
                    directory=record.parent.resolve()
                    if not directory.is_relative_to(candidates.resolve()):continue
                    if saved.get('sha256')!=manifest['sha256'] or saved.get('source')!=manifest.get('source'):continue
                    files=saved.get('files')
                    if not isinstance(files,list) or not files:continue
                    intact=True
                    for item in files:
                        path=(directory/item['path']).resolve()
                        if not path.is_relative_to(directory) or not path.is_file() or path.stat().st_size!=item['bytes'] or file_sha256(path)!=item['sha256']:
                            intact=False;break
                    if not intact:continue
                    prepared={**saved,'candidate_directory':str(directory),'reused_verified_copy':True,
                              'runtime_validated':False,'activated':False}
                    # Reusing files never reuses an old runtime validation.
                    self.job.update(state='prepared',result=prepared,error=None)
                    self._persist_job()
                    return self.status_unlocked()
                except (OSError,ValueError,KeyError,TypeError):continue
            self.job['state']='preparing'
            self._persist_job()
        destination=self.folder/'candidates'/uuid.uuid4().hex
        try:
            with zipfile.ZipFile(target) as archive:
                entries=archive.infolist()
                total=sum(entry.file_size for entry in entries)
                if len(entries)>20000 or total>8*1024**3:raise ValueError('Archive exceeds extraction limits')
                if shutil.disk_usage(self.folder).free<total+1024**3:raise ValueError('Insufficient disk reserve for extraction')
                for entry in entries:
                    name=entry.filename.replace('\\','/')
                    if name.startswith('/') or ':' in name or '..' in Path(name).parts:
                        raise ValueError('Unsafe archive path')
                    if stat.S_ISLNK(entry.external_attr>>16):raise ValueError('Archive links are not allowed')
                    if entry.flag_bits&1:raise ValueError('Encrypted archives are not supported')
                destination.mkdir(parents=True)
                files=[]
                for entry in entries:
                    output=(destination/entry.filename.replace('\\','/')).resolve()
                    if not output.is_relative_to(destination.resolve()):raise ValueError('Unsafe extraction destination')
                    if entry.is_dir():output.mkdir(parents=True,exist_ok=True);continue
                    output.parent.mkdir(parents=True,exist_ok=True)
                    digest=hashlib.sha256();count=0
                    with archive.open(entry) as source, output.open('xb') as sink:
                        while block:=source.read(1024*1024):
                            count+=len(block)
                            if count>entry.file_size:raise ValueError('Extracted file exceeds declared size')
                            sink.write(block);digest.update(block)
                    if count!=entry.file_size:raise ValueError('Truncated archive member')
                    files.append({'path':output.relative_to(destination).as_posix(),'bytes':count,'sha256':digest.hexdigest()})
            if self.job.get('component')=='whisper.cpp':
                wiring=whisper_cpu_dependencies(destination,target.name)
                files.extend(wiring['files'])
            prepared={**manifest,'candidate_directory':str(destination),'files':files,
                'prepared_at':time.time(),'runtime_validated':False,'activated':False}
            if self.job.get('component')=='whisper.cpp':prepared['dependency_wiring']={key:value for key,value in wiring.items() if key!='files'}
            (destination/'CANDIDATE-MANIFEST.json').write_text(json.dumps(prepared,indent=2),encoding='utf-8')
            with self.lock:self.job.update(state='prepared',result=prepared);self._persist_job()
        except Exception as error:
            if destination.is_relative_to((self.folder/'candidates').resolve()) and destination.exists():shutil.rmtree(destination)
            with self.lock:self.job.update(state='staged',error=str(error));self._persist_job()
            raise
        return self.status()

    def validate(self, model_path):
        """Exercise a candidate llama server using a real local model on CPU only."""
        if self.job.get('component')=='colibri':return self.validate_colibri()
        if self.job.get('component')=='strata':
            return self.validate_strata_startup()
        from serve.optional_backends import OptionalBackends
        with self.lock:
            if self.job.get('state')!='prepared':raise ValueError('Prepare an isolated candidate first')
            component=self.job.get('component')
            if component not in ('llama.cpp','audio.cpp','whisper.cpp'):raise ValueError('Functional validation is currently available for llama.cpp, whisper.cpp and audio.cpp only')
            prepared=dict(self.job['result'])
            directory=Path(prepared['candidate_directory']).resolve()
            if not directory.is_relative_to((self.folder/'candidates').resolve()):raise ValueError('Invalid candidate directory')
            executable={'llama.cpp':'llama-server.exe','audio.cpp':'audiocpp_server.exe','whisper.cpp':'whisper-server.exe'}[component]
            binaries=list(directory.rglob(executable))
            if len(binaries)!=1:raise ValueError('Candidate must contain exactly one '+executable)
            for row in prepared['files']:
                file=(directory/row['path']).resolve()
                if not file.is_relative_to(directory) or not file.is_file() or file_sha256(file)!=row['sha256']:
                    raise ValueError('Candidate files have changed')
            model=Path(model_path or '').resolve()
            roots=[self.root.parent/'Strata-data/models',self.root/'output/model-exports',Path.home()/'.cache/huggingface',Path.home()/'.unsloth/.cache']
            if not any(model.is_relative_to(root.resolve()) for root in roots) or not model.is_file() or model.stat().st_size>1024**3:
                raise ValueError('Select a local GGUF smaller than 1 GiB from the configured model folders')
            with model.open('rb') as source:
                if source.read(4)!=(b'lmgg' if component=='whisper.cpp' else b'GGUF'):raise ValueError('Validation model format does not match the runtime')
            if not self.operational_idle():raise ValueError('Stop active engines and campaigns before candidate validation')
            self.job.update(state='validating',error=None,owner_pid=os.getpid())
            self._persist_job()
        handler={'audio.cpp':self._validate_audio,'whisper.cpp':self._validate_whisper,'llama.cpp':self._validate}[component]
        if component=='llama.cpp' and prepared.get('source','').endswith('windows-x64-rocm-gfx110X.zip'):handler=self._validate_gpu
        threading.Thread(target=handler,args=(binaries[0],model,prepared),daemon=True).start()
        return self.status()

    def validate_colibri(self):
        with self.lock:
            if self.job.get('state')!='prepared' or self.job.get('component')!='colibri':raise ValueError('Prepara prima un candidato Colibri isolato')
            if not self.operational_idle():raise ValueError('Arresta i motori prima della verifica Colibri')
            prepared={**self.job['result'],'published_version':self.job.get('version') or self.job['result'].get('published_version')}
            self.job.update(state='validating',error=None);self._persist_job()
        def run():
            try:
                from serve.colibri_update import validate
                result=validate(self.root,prepared)
                with self.lock:self.job.update(state='validated',result=result,error=None);self._persist_job()
            except Exception as error:
                with self.lock:self.job.update(state='prepared',error=str(error));self._persist_job()
        threading.Thread(target=run,daemon=True).start()
        return self.status()

    def validate_strata_inference(self):
        """One bounded request in a sidecar; no automatic selection or stress loop."""
        self.validate_strata_startup()
        with self.lock:
            if not self.operational_idle():raise ValueError('Stop active engines before validating Strata')
            self.job['result']['validation_started_at']=time.time()
            self.job.update(state='validating',owner_pid=os.getpid(),error=None);self._persist_job()
        def run():
            try:
                log=self.root/'output/verification/strata-candidate-validation-worker.log'
                with log.open('w',encoding='utf-8') as output:
                    process=subprocess.run([sys.executable,'-X','utf8',str(self.root/'tools/verify_strata_release_bounded.py'),'--full-profile'],cwd=self.root,stdout=output,stderr=subprocess.STDOUT,timeout=205)
                from serve.strata_update import candidate_proof
                proof=candidate_proof(self.root,self.job.get('result') or {})
                if process.returncode or not proof:raise ValueError('Strata inference check failed; see '+str(log))
                with self.lock:self.job.update(state='prepared',error=None);self._persist_job()
            except Exception as error:
                with self.lock:self.job.update(state='prepared',error=str(error));self._persist_job()
        threading.Thread(target=run,daemon=True).start()
        return self.status()

    def validate_strata_startup(self):
        """Check candidate dependencies and CLI startup; never certify GPU inference."""
        with self.lock:
            if self.job.get('component')!='strata' or self.job.get('state')!='prepared':
                raise ValueError('Prepare an isolated Strata candidate first')
            candidate=dict(self.job.get('result') or {})
            if not candidate.get('candidate_directory') or not candidate.get('files'):
                raise ValueError('Strata candidate manifest is incomplete')
            directory=Path(candidate['candidate_directory']).resolve()
            if not directory.is_relative_to((self.folder/'candidates').resolve()):
                raise ValueError('Invalid candidate directory')
            for item in candidate['files']:
                path=(directory/item['path']).resolve()
                if not path.is_relative_to(directory) or not path.is_file() or file_sha256(path)!=item['sha256']:
                    raise ValueError('Candidate files have changed')
            build=json.loads((directory/'BUILD.json').read_text(encoding='utf-8'))
            libs=[]
            for name in build.get('lib_dirs',[]):
                path=(directory/name).resolve()
                if not path.is_relative_to(directory) or not path.is_dir():
                    raise ValueError('Invalid bundled library directory')
                libs.append(str(path))
            env=dict(os.environ,HIP_VISIBLE_DEVICES='-1',ROCR_VISIBLE_DEVICES='-1',CUDA_VISIBLE_DEVICES='-1')
            env['PATH']=os.pathsep.join(libs+[env.get('PATH','')])
            process=subprocess.run([str(directory/'strata.exe'),'--help'],env=env,cwd=directory,
                capture_output=True,text=True,timeout=20,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if process.returncode or 'strata' not in (process.stdout+process.stderr).lower():
                raise ValueError('Strata startup failed: '+str(process.returncode))
            candidate.update(startup_validation={'passed':True,'version':build.get('version'),
                'backend':build.get('backend'),'gpu_inference_verified':False,'checked_at':time.time()},
                runtime_validated=False,activated=False)
            self.job.update(result=candidate,error=None)
            self._persist_job()
        return self.status()

    def _validate_whisper(self,binary,model,prepared):
        from serve.local_audio import LocalAudio
        engine=None
        try:
            fixture=self.root/'output/verification/audio-jfk.wav'
            if not fixture.is_file() or fixture.stat().st_size>20*1024**2:raise ValueError('A verified local speech validation fixture is required')
            engine=LocalAudio(self.root);engine.binary=binary;engine.candidate_validation=True
            engine.start({'model_path':str(model),'threads':2})
            result=engine.transcribe(fixture.read_bytes(),'validation.wav','en')
            if 'country' not in result['text'].lower():raise ValueError('Whisper candidate did not transcribe the expected validation phrase')
            prepared.update(runtime_validated=True,validation={'backend':'cpu','task':'asr','model':str(model),'text':result['text'],'request_seconds':result['elapsed_seconds'],'gpu_validated':False,'validated_at':time.time()})
            (Path(prepared['candidate_directory'])/'CANDIDATE-MANIFEST.json').write_text(json.dumps(prepared,indent=2),encoding='utf-8')
            with self.lock:self.job.update(state='validated',result=prepared);self._persist_job()
        except Exception as error:
            with self.lock:self.job.update(state='prepared',error=str(error));self._persist_job()
        finally:
            if engine:engine.stop()

    def _validate_audio(self,binary,model,prepared):
        from serve.local_speech import LocalSpeech
        engine=None
        try:
            engine=LocalSpeech(self.root);engine.binary=binary;engine.candidate_validation=True
            engine.start({'model_path':str(model)})
            deadline=time.monotonic()+65
            while engine.status()['status']!='ready':
                state=engine.status()
                if state['status']=='error':raise RuntimeError(state.get('error') or 'Audio candidate failed')
                if time.monotonic()>deadline:raise TimeoutError('Audio candidate loading timeout')
                time.sleep(.2)
            result=engine.generate({'input':'Ciao, questa è una verifica del motore vocale.','voice':'if_sara','language':'it','speed':1})
            import base64,io,wave
            output=base64.b64decode(result['audio_base64'],validate=True)
            with wave.open(io.BytesIO(output)) as audio:
                if audio.getnframes()<1:raise ValueError('Audio candidate produced no frames')
                report={'backend':'cpu','model':str(model),'task':'tts','frames':audio.getnframes(),'sample_rate':audio.getframerate(),'audio_sha256':hashlib.sha256(output).hexdigest(),'gpu_validated':False,'validated_at':time.time()}
            prepared.update(runtime_validated=True,validation=report)
            (Path(prepared['candidate_directory'])/'CANDIDATE-MANIFEST.json').write_text(json.dumps(prepared,indent=2),encoding='utf-8')
            with self.lock:self.job.update(state='validated',result=prepared);self._persist_job()
        except Exception as error:
            with self.lock:self.job.update(state='prepared',error=str(error));self._persist_job()
        finally:
            if engine:engine.stop()

    def _validate_gpu(self,binary,model,prepared):
        """A bounded real GPU probe whose evidence belongs to this archive."""
        try:
            directory=Path(prepared['candidate_directory'])
            with (directory/'GPU-validation-worker.log').open('wb') as log:
                child=subprocess.Popen([sys.executable,'-X','utf8',str(self.root/'tools/verify_llama_gpu_candidate.py'),'--candidate',str(directory),'--model',str(model)],cwd=self.root,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                try:code=child.wait(timeout=150)
                finally:
                    from serve.process_lifecycle import stop_owned_tree
                    stop_owned_tree(child,timeout=10)
            if code:raise ValueError('GPU candidate validation failed; inspect GPU-validation-worker.log')
            from serve.llama_gpu_update import proof
            verified=proof(self.root,prepared,verify=True)
            result={**prepared,'validation':verified['validation'],'runtime_validated':True,'gpu_validated':True,'activated':False}
            with self.lock:self.job.update(state='validated',result=result,error=None);self._persist_job()
        except Exception as error:
            with self.lock:self.job.update(state='prepared',error=str(error));self._persist_job()

    def _validate(self, binary, model, prepared):
        from serve.optional_backends import OptionalBackends
        manager=None
        try:
            manager=OptionalBackends(self.root);manager.binary=binary;manager.candidate_validation=True
            manager.start({'mode':'gguf','model_path':str(model),'gpu':False,'context':1024,
                'fit_mode':'manual','context_mode':'manual','runtime':{'threads':2,'threads_batch':2}},self.operational_idle())
            deadline=time.monotonic()+180
            while time.monotonic()<deadline:
                state=manager.status()
                if state['status']=='ready':break
                if state['status']=='error':raise RuntimeError(state.get('error') or 'Candidate failed to load')
                time.sleep(.25)
            else:raise TimeoutError('Candidate loading exceeded 180 seconds')
            started=time.monotonic()
            events=list(manager.chat({'messages':[{'role':'user','content':'Reply with a short greeting.'}],
                'max_tokens':16,'stream':False,'temperature':0},threading.Event()))
            content=''.join(event.get('choices',[{}])[0].get('message',{}).get('content','') or '' for event in events if event.get('choices'))
            if not content.strip():raise RuntimeError('Candidate returned no usable response')
            report={'backend':'cpu','model':str(model),'response':content[:1000],
                'request_seconds':time.monotonic()-started,'gpu_validated':False,'validated_at':time.time()}
            prepared.update(runtime_validated=True,validation=report)
            directory=Path(prepared['candidate_directory'])
            (directory/'CANDIDATE-MANIFEST.json').write_text(json.dumps(prepared,indent=2),encoding='utf-8')
            with self.lock:self.job.update(state='validated',result=prepared);self._persist_job()
        except Exception as error:
            with self.lock:self.job.update(state='prepared',error=str(error));self._persist_job()
        finally:
            if manager:manager.close()

    def activate(self):
        from serve.configuration import atomic_json
        from serve.customization_backup import snapshot
        with self.lock:
            component=self.job.get('component')
            if component=='colibri':
                if self.job.get('state')!='validated' or not self.operational_idle():raise ValueError('Candidato Colibri validato e motori arrestati richiesti')
                from serve.colibri_update import activate
                activate(self.root,self.job['result']);self.job.update(state='selected_colibri',error=None);self._persist_job()
                return self.status()
            if component=='strata':
                if self.job.get('error') or self.job.get('state') not in ('prepared','rolled_back'):raise ValueError('Prepare the Strata candidate before selection')
                if not self.operational_idle():raise ValueError('Stop active engines before activation')
                from serve.strata_update import activate
                selection=activate(self.root,self.configuration_provider(),self.job.get('result') or {})
                self.job.update(state='selected_strata',error=None);self._persist_job()
                from serve.update_restart import mark_restart_pending
                try:mark_restart_pending(self.root,'strata',self.job.get('version'),self.port)
                except (OSError,ValueError):pass
                return self.status()
            if self.job.get('state') not in ('validated','rolled_back') or component not in ('llama.cpp','audio.cpp','whisper.cpp'):
                raise ValueError('A functionally validated llama.cpp or audio.cpp candidate is required')
            if not self.operational_idle():raise ValueError('Stop active engines before activation')
            candidate=self.job['result']
            if not candidate.get('runtime_validated') or candidate.get('validation',{}).get('backend')!='cpu':
                raise ValueError('CPU functional validation is required')
            directory=Path(candidate['candidate_directory']).resolve()
            if not directory.is_relative_to((self.folder/'candidates').resolve()):raise ValueError('Invalid candidate directory')
            for row in candidate['files']:
                path=(directory/row['path']).resolve()
                if not path.is_relative_to(directory) or not path.is_file() or file_sha256(path)!=row['sha256']:
                    raise ValueError('Validated candidate has changed')
            servers=list(directory.rglob({'llama.cpp':'llama-server.exe','audio.cpp':'audiocpp_server.exe','whisper.cpp':'whisper-server.exe'}[component]))
            if len(servers)!=1:raise ValueError('Candidate server is ambiguous')
            backup=snapshot(self.root)
            registry=self.root/'data'/{'llama.cpp':'runtime-selection.json','audio.cpp':'audio-runtime-selection.json','whisper.cpp':'whisper-runtime-selection.json'}[component]
            try:previous=json.loads(registry.read_text(encoding='utf-8')).get('active')
            except (OSError,ValueError):previous=None
            published_version=candidate.get('published_version')
            if not published_version:
                marker={'audio.cpp':'UNSLOTH_AUDIO_CPP_PREBUILT_INFO.json','whisper.cpp':'UNSLOTH_WHISPER_PREBUILT_INFO.json','llama.cpp':'UNSLOTH_PREBUILT_INFO.json'}[component]
                try:
                    metadata=json.loads((directory/marker).read_text(encoding='utf-8'));published_version=metadata.get('release_tag') or metadata.get('tag')
                except (OSError,ValueError):pass
            selection={'binary':str(servers[0]),'directory':str(directory),'files':candidate['files'],
                'component':component,'version':published_version,
                'validation':candidate['validation'],'activated_at':time.time(),'scope':{'llama.cpp':'llama_cpu','audio.cpp':'audio_cpu','whisper.cpp':'whisper_cpu'}[component]}
            atomic_json(registry,{'active':selection,'previous':previous,'backup':backup})
            self.job.update(state='activated_cpu')
            self._persist_job()
        return self.status()

    def rollback(self,component='llama.cpp'):
        if component=='colibri':
            with self.lock:
                if not self.operational_idle():raise ValueError('Arresta i motori prima del ripristino Colibri')
                from serve.colibri_update import rollback
                rollback(self.root);self.job.update(state='rolled_back',component='colibri',error=None);self._persist_job()
                return self.status()
        with self.lock:
            if self.job.get('state') in ('downloading','preparing','validating','resolving','installing_candidate','validating_python'):
                raise ValueError('An update operation is already running')
            from serve.configuration import atomic_json
            if not self.operational_idle():raise ValueError('Stop active engines before rollback')
            if component=='strata':
                from serve.strata_update import rollback
                rollback(self.root);self.job.update(state='rolled_back');self._persist_job();return self.status()
            if component not in ('llama.cpp','audio.cpp','whisper.cpp'):raise ValueError('Unsupported runtime rollback')
            registry=self.root/'data'/{'llama.cpp':'runtime-selection.json','audio.cpp':'audio-runtime-selection.json','whisper.cpp':'whisper-runtime-selection.json'}[component]
            try:data=json.loads(registry.read_text(encoding='utf-8'))
            except (OSError,ValueError):raise ValueError('No runtime selection to roll back')
            atomic_json(registry,{'active':data.get('previous'),'previous':data.get('active'),
                'rolled_back_at':time.time(),'backup':data.get('backup')})
            self.job.update(state='rolled_back');self._persist_job()
        return self.status()

    def dependency_plan(self, environment_name, component=None, version=None):
        """Resolve exact candidate versions using wheels only; never install into the source env."""
        import re
        import uuid
        with self.lock:
            if self.job.get('state') in ('downloading','preparing','validating','resolving','installing_candidate','validating_python'):
                raise ValueError('An update operation is already running')
            environment=next((e for e in self.result.get('environments',[]) if e['name']==environment_name),None)
            if not environment or environment.get('update_check',{}).get('state')!='checked':
                raise ValueError('Check this environment against official PyPI first')
            if component is not None:
                if component not in ('transformers','airllm') or not any(normalize_package(p['name'])==component for p in environment['packages']):raise ValueError('Component is not installed in this environment')
                release=next((r for r in self.result.get('components',[]) if r['id']==component),None)
                if component=='transformers' and release:
                    from serve.transformers_compatibility import cached
                    release=cached(self.root,release)
                if not release or not version or release.get('version')!=version:raise ValueError('Recheck the official component version first')
            pins=[];protected=[]
            for package in environment['packages']:
                name=package['name'];package_version=(version if component and normalize_package(name)==component else package['version']) if component else package.get('available_version') or package['version']
                if not re.fullmatch(r'[A-Za-z0-9_.-]+',name) or not re.fullmatch(r'[A-Za-z0-9_.+!-]+',package_version):
                    raise ValueError('Invalid package metadata')
                # Vendor builds must never be replaced by generic PyPI wheels.
                if '+' in package['version'] or normalize_package(name) in ('torch','torchvision','torchaudio','triton','pytorch-triton-rocm'):
                    package_version=package['version'];protected.append(name)
                compatible_update=not component and name not in protected and bool(package.get('available_version'))
                # Let native dependency constraints choose compatible updates;
                # the resolver report locks the actual wheels and hashes afterward.
                pins.append(name+('>='+package['version'] if compatible_update else '=='+package_version))
            folder=self.folder/'python-plans'/uuid.uuid4().hex;folder.mkdir(parents=True)
            (folder/'requirements.txt').write_text('\n'.join(pins)+'\n',encoding='utf-8')
            self.job={'state':'resolving','name':environment_name,'started_at':time.time(),'owner_pid':os.getpid(),
                'plan_directory':str(folder),'source_python':environment['python'],'protected_packages':protected,'component':component,'version':version}
            self._persist_job()
        vendor=component=='transformers' and environment_name=='Unsloth' and any(normalize_package(p['name'])=='torch' and 'rocm' in p['version'].lower() for p in environment['packages'])
        threading.Thread(target=self._prepare_vendor_dependencies if vendor else self._resolve_dependencies,args=(environment['python'],version) if vendor else (environment['python'],folder),daemon=True).start()
        return self.status()

    def _prepare_vendor_dependencies(self,executable,version):
        from serve.vendor_python_update import prepare
        from serve.customization_backup import snapshot
        def progress(**fields):
            with self.lock:self.job.update(fields);self._persist_job()
        try:
            if not self.operational_idle():raise ValueError('Stop active engines before preparing the vendor candidate')
            from serve.python_inference_update import candidate
            for path in sorted((self.folder/'python-plans').glob('*/environment-manifest.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:64]:
                try:
                    saved=json.loads(path.read_text(encoding='utf-8'))
                    if saved.get('original_source_python')!=str(Path(executable).resolve()) or not saved.get('vendor_copy') or saved.get('source_packages',{}).get('transformers')!=version:continue
                    _,manifest=candidate(self.root,path.parent)
                    manifest['reused_verified_copy']=True
                    progress(state='candidate_installed',plan_directory=str(path.parent),result=manifest,error=None)
                    return
                except (OSError,ValueError,KeyError,TypeError):continue
            from serve.vendor_python_validation import validation_model
            validation_model(self.root)
            backup=snapshot(self.root)
            result=prepare(self.root,executable,version,progress);result['customization_backup']=backup
            progress(state='candidate_installed',plan_directory=result['plan_directory'],result=result,error=None)
        except Exception as error:progress(state='candidate_failed',error=str(error))

    def _resolve_dependencies(self, executable, folder):
        import os
        from serve.configuration import atomic_json
        report=folder/'pip-report.json'
        try:
            requirements=(folder/'requirements.txt').read_text(encoding='utf-8').splitlines()
            cpu_wheels=any(re.fullmatch(r'(torch|torchvision|torchaudio)==[^\s]+\+cpu',line.strip(),re.I) for line in requirements)
            indexes=['--extra-index-url','https://download.pytorch.org/whl/cpu'] if cpu_wheels else []
            environment={**os.environ,'PIP_CONFIG_FILE':os.devnull,'PIP_INDEX_URL':'https://pypi.org/simple',
                'PIP_EXTRA_INDEX_URL':'','PIP_FIND_LINKS':'','PIP_NO_CACHE_DIR':'1'}
            for saved_report in sorted((self.folder/'python-plans').glob('*/pip-report.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:8]:
                if saved_report.parent==folder or time.time()-saved_report.stat().st_mtime>3600:continue
                saved_requirements=saved_report.parent/'requirements.txt'
                if saved_requirements.is_file() and saved_requirements.read_bytes()==(folder/'requirements.txt').read_bytes():
                    saved_data=json.loads(saved_report.read_text(encoding='utf-8'))
                    if saved_data.get('environment',{}).get('python_full_version')=='.'.join(map(str,sys.version_info[:3])):
                        shutil.copyfile(saved_report,report);break
            if not report.is_file():
                process=subprocess.run([executable,'-I','-m','pip','install','--dry-run','--ignore-installed',
                    '--only-binary=:all:','--disable-pip-version-check','--index-url','https://pypi.org/simple',
                    *indexes,'--timeout','8','--retries','0','--report',str(report),'-r',str(folder/'requirements.txt')],
                    env=environment,capture_output=True,text=True,timeout=180,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                (folder/'resolver.log').write_text((process.stdout+'\n'+process.stderr)[-200000:],encoding='utf-8')
                if process.returncode:raise ValueError('Candidate dependency set is incompatible or vendor wheels are unavailable; see resolver.log')
            data=json.loads(report.read_text(encoding='utf-8'))
            if not isinstance(data.get('install'),list):raise ValueError('Invalid resolver report')
            from urllib.parse import urlparse,unquote,quote
            for package in data['install']:
                download=package['download_info'];parsed=urlparse(download['url']);metadata=package['metadata']
                if parsed.hostname not in ('download.pytorch.org','download-r2.pytorch.org') or normalize_package(metadata['name']) in ('torch','torchvision','torchaudio'):continue
                request=urllib.request.Request('https://pypi.org/pypi/'+quote(metadata['name'],safe='')+'/'+quote(metadata['version'],safe='')+'/json',headers={'User-Agent':'Strata-Update-Centre'})
                with urllib.request.urlopen(request,timeout=15) as response:official=json.loads(response.read(2*1024*1024))
                digest=download.get('archive_info',{}).get('hashes',{}).get('sha256')
                match=next((row for row in official.get('urls',[]) if row.get('filename')==unquote(Path(parsed.path).name) and row.get('digests',{}).get('sha256')==digest and urlparse(row.get('url','')).hostname=='files.pythonhosted.org'),None)
                if not match:raise ValueError('Vendor index library is not the identical official PyPI wheel')
                download['url']=match['url']
            atomic_json(report,data)
            result={'plan_directory':str(folder),'packages':len(data['install']),
                'installed':False,'runtime_validated':False,'source':'https://pypi.org/simple'}
            with self.lock:self.job.update(state='resolved',result=result);self._persist_job()
        except Exception as error:
            with self.lock:self.job.update(state='resolution_failed',error=str(error));self._persist_job()

    def install_dependencies(self):
        from urllib.parse import urlparse
        with self.lock:
            if self.job.get('state')!='resolved':raise ValueError('Resolve a compatible dependency plan first')
            if not self.operational_idle():raise ValueError('Stop active engines before preparing the candidate environment')
            folder=Path(self.job['plan_directory']).resolve()
            if not folder.is_relative_to((self.folder/'python-plans').resolve()):raise ValueError('Invalid dependency plan path')
            report=json.loads((folder/'pip-report.json').read_text(encoding='utf-8'))
            pins=[]
            for package in report.get('install',[]):
                download=package['download_info'];url=download['url'];parsed=urlparse(url)
                digest=download.get('archive_info',{}).get('hashes',{}).get('sha256','')
                metadata=package.get('metadata',{})
                cpu_vendor=parsed.hostname in ('download.pytorch.org','download-r2.pytorch.org') and parsed.path.startswith('/whl/cpu/') and normalize_package(metadata.get('name','')) in ('torch','torchvision','torchaudio') and str(metadata.get('version','')).endswith('+cpu')
                if any(c.isspace() for c in url) or parsed.scheme!='https' or (parsed.hostname!='files.pythonhosted.org' and not cpu_vendor) or parsed.username or parsed.password or not parsed.path.endswith('.whl'):
                    raise ValueError('Candidate packages must be official PyPI wheels')
                if len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):raise ValueError('Missing wheel SHA-256')
                pins.append(url+' --hash=sha256:'+digest)
            if not pins or len(pins)>500:raise ValueError('Invalid candidate package count')
            if shutil.disk_usage(self.folder).free<8*1024**3:raise ValueError('Candidate environment requires at least 8 GiB free disk reserve')
            (folder/'locked-wheels.txt').write_text('\n'.join(pins)+'\n',encoding='utf-8')
            executable=self.job.get('source_python')
            if not executable or not Path(executable).is_file():raise ValueError('Source Python runtime unavailable; resolve the plan again')
            self.job.update(state='installing_candidate',owner_pid=os.getpid());self._persist_job()
        threading.Thread(target=self._install_dependencies,args=(executable,folder),daemon=True).start()
        return self.status()

    def _install_dependencies(self, executable, folder):
        import os
        from serve.customization_backup import snapshot
        candidate=folder/'environment'
        try:
            backup=snapshot(self.root)
            if candidate.exists():raise ValueError('Candidate environment already exists; prepare a new plan')
            flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
            process=subprocess.run([executable,'-I','-m','venv',str(candidate)],capture_output=True,text=True,timeout=120,creationflags=flags)
            if process.returncode:raise ValueError('Isolated environment creation failed: '+process.stderr[-2000:])
            python=candidate/'Scripts/python.exe'
            environment={**os.environ,'PIP_CONFIG_FILE':os.devnull,'PIP_INDEX_URL':'https://pypi.org/simple',
                'PIP_EXTRA_INDEX_URL':'','PIP_FIND_LINKS':'','PIP_NO_CACHE_DIR':'1'}
            with (folder/'installation.log').open('w',encoding='utf-8') as log:
                process=subprocess.run([str(python),'-I','-m','pip','install','--no-index','--no-deps',
                    '--only-binary=:all:','--require-hashes','--disable-pip-version-check','--timeout','15','--retries','0',
                    '-r',str(folder/'locked-wheels.txt')],env=environment,stdout=log,stderr=subprocess.STDOUT,timeout=600,creationflags=flags)
            if process.returncode:raise ValueError('Candidate installation failed; active environment unchanged')
            health=check_dependencies(python)
            if health['state']!='healthy':raise ValueError('Candidate dependency check failed: '+health.get('details',''))
            result={'python':str(python),'plan_directory':str(folder),'dependency_health':health,
                'installed':True,'activated':False,'runtime_validated':False,'customization_backup':backup}
            (folder/'environment-manifest.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
            with self.lock:self.job.update(state='candidate_installed',result=result);self._persist_job()
        except Exception as error:
            with self.lock:self.job.update(state='candidate_failed',error=str(error));self._persist_job()

    def select_python(self, rollback=False):
        with self.lock:
            if self.job.get('state') in ('downloading','preparing','validating','resolving','installing_candidate','validating_python'):
                raise ValueError('An update operation is already running')
            from serve.configuration import atomic_json
            registry=self.root/'data/dashboard-python-selection.json'
            if not self.operational_idle():raise ValueError('Stop engines before changing the dashboard runtime')
            try:previous=json.loads(registry.read_text(encoding='utf-8'))
            except (OSError,ValueError):previous={}
            if rollback:
                selection={'active':previous.get('previous'),'previous':previous.get('active'),'changed_at':time.time()}
            else:
                if self.job.get('state')!='candidate_installed' or self.job.get('name')!='Strata':raise ValueError('Install an isolated Strata candidate first')
                if self.job.get('error'):raise ValueError('Last candidate validation failed; validate it again before selection')
                folder=Path(self.job['result']['plan_directory']).resolve()
                if not folder.is_relative_to((self.folder/'python-plans').resolve()):raise ValueError('Invalid environment path')
                manifest=json.loads((folder/'environment-manifest.json').read_text(encoding='utf-8'))
                if manifest.get('dependency_health',{}).get('state')!='healthy' or not manifest.get('server_suite',{}).get('passed') or not manifest.get('dashboard_start_verified'):
                    raise ValueError('Candidate must pass server tests and actual dashboard startup before selection')
                if manifest.get('core_source_sha256')!=source_fingerprint(self.root):raise ValueError('Project sources have changed; validate the candidate again')
                python=Path(manifest['python']).resolve()
                if not python.is_relative_to(folder) or not python.is_file():raise ValueError('Invalid candidate Python')
                selection={'active':str(python),'previous':previous.get('active'),'changed_at':time.time()}
            registry.parent.mkdir(parents=True,exist_ok=True)
            atomic_json(registry,selection)
        return self.status()

    def audio_python(self,operation):
        if not self.operational_idle():raise ValueError('Stop active engines before audio runtime changes')
        from serve.audio_python_update import validate,activate
        with self.lock:
            if self.job.get('state') in ('downloading','preparing','validating','resolving','installing_candidate','validating_python'):raise ValueError('An update operation is already running')
            if operation=='rollback':activate(self.root,rollback=True)
            else:
                if self.job.get('state')!='candidate_installed' or self.job.get('name')!='Audio generativo':raise ValueError('Install an isolated generative audio candidate first')
                folder=Path(self.job['result']['plan_directory'])
                if operation=='validate':
                    self.job.update(state='validating_python',error=None,owner_pid=os.getpid());self._persist_job()
                    threading.Thread(target=self._validate_audio_python,args=(folder,self.job['source_python']),daemon=True).start()
                elif operation=='activate':
                    if self.job.get('error'):raise ValueError('Audio validation failed; current runtime preserved')
                    activate(self.root,folder)
                else:raise ValueError('Unknown audio runtime operation')
        return self.status()

    def _validate_audio_python(self,folder,source):
        from serve.audio_python_update import validate
        try:
            manifest=validate(self.root,folder,source)
            with self.lock:self.job.update(state='candidate_installed',result=manifest,error=None);self._persist_job()
        except Exception as error:
            with self.lock:self.job.update(state='candidate_installed',error=str(error));self._persist_job()

    def visual_python(self,operation):
        if not self.operational_idle():raise ValueError('Stop active engines before visual runtime changes')
        from serve.visual_python_update import validate,activate
        with self.lock:
            if self.job.get('state') in ('downloading','preparing','validating','resolving','installing_candidate','validating_python'):raise ValueError('An update operation is already running')
            if operation=='rollback':activate(self.root,rollback=True)
            else:
                if self.job.get('state')!='candidate_installed' or self.job.get('name')!='Visuale':raise ValueError('Install an isolated visual candidate first')
                folder=Path(self.job['result']['plan_directory'])
                if operation=='validate':
                    self.job.update(state='validating_python',error=None,owner_pid=os.getpid());self._persist_job()
                    threading.Thread(target=self._validate_visual_python,args=(folder,self.job['source_python']),daemon=True).start()
                elif operation=='activate':
                    if self.job.get('error'):raise ValueError('Visual validation failed; current runtime preserved')
                    activate(self.root,folder)
                else:raise ValueError('Unknown visual runtime operation')
        return self.status()

    def _validate_visual_python(self,folder,source):
        from serve.visual_python_update import validate
        try:
            manifest=validate(self.root,folder,source)
            with self.lock:self.job.update(state='candidate_installed',result=manifest,error=None);self._persist_job()
        except Exception as error:
            with self.lock:self.job.update(state='candidate_installed',error=str(error));self._persist_job()

    def document_python(self,operation):
        if not self.operational_idle():raise ValueError('Stop active engines before document runtime changes')
        from serve.open_webui_python_update import validate,activate
        with self.lock:
            if self.job.get('state') in ('downloading','preparing','validating','resolving','installing_candidate','validating_python'):raise ValueError('An update operation is already running')
            if operation=='rollback':activate(self.root,rollback=True)
            else:
                if self.job.get('state')!='candidate_installed' or self.job.get('name')!='Open WebUI':raise ValueError('Install an isolated document candidate first')
                folder=Path(self.job['result']['plan_directory'])
                if operation=='validate':
                    self.job.update(state='validating_python',error=None,owner_pid=os.getpid());self._persist_job()
                    threading.Thread(target=self._validate_document_python,args=(folder,self.job['source_python']),daemon=True).start()
                elif operation=='activate':
                    if self.job.get('error'):raise ValueError('Document validation failed; current runtime preserved')
                    activate(self.root,folder)
                else:raise ValueError('Unknown document runtime operation')
        return self.status()

    def _validate_document_python(self,folder,source):
        from serve.open_webui_python_update import validate
        try:
            manifest=validate(self.root,folder,source)
            with self.lock:self.job.update(state='candidate_installed',result=manifest,error=None);self._persist_job()
        except Exception as error:
            with self.lock:self.job.update(state='candidate_installed',error=str(error));self._persist_job()

    def inference_python(self, operation):
        if not self.operational_idle():raise ValueError('Stop active engines before inference runtime changes')
        from serve.python_inference_update import validate,activate
        default=Path.home()/'.unsloth/studio/unsloth_studio/Scripts/python.exe'
        with self.lock:
            if self.job.get('state') in ('downloading','preparing','validating','resolving','installing_candidate','validating_python'):raise ValueError('An update operation is already running')
            if operation=='rollback':activate(self.root,None,default,rollback=True)
            else:
                if self.job.get('state')!='candidate_installed' or self.job.get('name')!='Unsloth':raise ValueError('Install an isolated Unsloth candidate first')
                folder=Path(self.job['result']['plan_directory'])
                if operation=='validate':
                    self.job.update(state='validating_python',error=None,owner_pid=os.getpid());self._persist_job()
                    threading.Thread(target=self._validate_inference_python,args=(folder,),daemon=True).start()
                elif operation=='activate':
                    if self.job.get('error'):raise ValueError('Last inference validation failed; validate again before selection')
                    activate(self.root,folder,default)
                else:raise ValueError('Unknown inference runtime operation')
        return self.status()

    def _validate_inference_python(self,folder):
        from serve.python_inference_update import validate
        try:
            saved=json.loads((Path(folder)/'environment-manifest.json').read_text(encoding='utf-8'))
            if saved.get('vendor_copy'):
                from serve.vendor_python_validation import validate as validate_vendor
                manifest=validate_vendor(self.root,folder)
            else:manifest=validate(self.root,folder)
            with self.lock:self.job.update(state='candidate_installed',result=manifest,error=None);self._persist_job()
        except Exception as error:
            with self.lock:self.job.update(state='candidate_installed',error=str(error));self._persist_job()

    def validate_python(self):
        with self.lock:
            if self.job.get('state') not in ('candidate_installed','interrupted') or self.job.get('name')!='Strata' or not self.job.get('result',{}).get('installed'):raise ValueError('Install an isolated Strata candidate first')
            if not self.operational_idle():raise ValueError('Stop active engines before candidate validation')
            folder=Path(self.job['result']['plan_directory']).resolve()
            if not folder.is_relative_to((self.folder/'python-plans').resolve()):raise ValueError('Invalid environment path')
            manifest=json.loads((folder/'environment-manifest.json').read_text(encoding='utf-8'))
            python=Path(manifest['python']).resolve()
            if not python.is_relative_to(folder) or not python.is_file() or manifest.get('dependency_health',{}).get('state')!='healthy':raise ValueError('Candidate dependency health is invalid')
            configuration=self.configuration_provider()
            if not configuration or not Path(configuration).is_file():raise ValueError('Dashboard configuration is unavailable')
            self.job.update(state='validating_python',owner_pid=os.getpid(),error=None);self._persist_job()
        threading.Thread(target=self._validate_python,args=(folder,python,Path(configuration)),daemon=True).start()
        return self.status()

    def _validate_python(self,folder,python,configuration):
        import re,socket,uuid
        child=None
        try:
            fingerprint=source_fingerprint(self.root)
            environment={**os.environ,'CUDA_VISIBLE_DEVICES':'-1','HIP_VISIBLE_DEVICES':'-1','ROCR_VISIBLE_DEVICES':'-1'}
            environment.pop('STRATA_PYTHON_CANDIDATE_PROBE',None)
            log=folder/'server-suite.log'
            with log.open('w',encoding='utf-8') as stream:
                run=subprocess.run([str(python),'-m','unittest','discover','-s','serve','-p','test_*.py'],cwd=self.root,env=environment,stdout=stream,stderr=subprocess.STDOUT,timeout=240,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            text=log.read_text(encoding='utf-8',errors='replace');count=re.search(r'Ran (\d+) tests? in ([\d.]+)s',text)
            if run.returncode or not count or int(count[1])<1:raise ValueError('Candidate server suite failed; see server-suite.log')
            cfg=json.loads(configuration.read_text(encoding='utf-8-sig'));identity='candidate-probe-'+uuid.uuid4().hex
            cfg.update(model_name=identity,api_key='',mcp_servers={},api_monitor=False,vision=False)
            probe_config=folder/'dashboard-probe.json';probe_config.write_text(json.dumps(cfg),encoding='utf-8')
            with socket.socket() as listener:listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
            with (folder/'dashboard-probe.log').open('wb') as output:
                environment['STRATA_PYTHON_CANDIDATE_PROBE']='1'
                child=subprocess.Popen([str(python),str(self.root/'serve/server.py'),'--engine','strata','--config',str(probe_config),'--lazy','--host','127.0.0.1','--port',str(port)],cwd=self.root,env=environment,stdout=output,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                deadline=time.monotonic()+45
                while time.monotonic()<deadline:
                    if child.poll() is not None:raise ValueError('Candidate dashboard failed to start; see dashboard-probe.log')
                    try:
                        with urllib.request.urlopen(f'http://127.0.0.1:{port}/v1/models',timeout=1) as response:models=json.load(response)
                        with urllib.request.urlopen(f'http://127.0.0.1:{port}/metrics',timeout=1) as response:metrics=json.load(response)
                        if any(row.get('id')==identity for row in models.get('data',[])) and metrics.get('live',{}).get('state')=='unloaded':break
                    except (OSError,ValueError):pass
                    time.sleep(.25)
                else:raise TimeoutError('Candidate dashboard readiness timeout')
            if source_fingerprint(self.root)!=fingerprint:raise ValueError('Sources changed during validation; run validation again')
            manifest_path=folder/'environment-manifest.json';manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
            manifest.update(server_suite={'passed':True,'tests':int(count[1]),'seconds':float(count[2]),'log':str(log)},dashboard_start_verified=True,core_source_sha256=fingerprint,validated_at=time.time(),gpu_validated=False)
            from serve.configuration import atomic_json
            atomic_json(manifest_path,manifest)
            with self.lock:self.job.update(state='candidate_installed',result=manifest,error=None);self._persist_job()
        except Exception as error:
            with self.lock:self.job.update(state='candidate_installed',error=str(error));self._persist_job()
        finally:
            if child and child.poll() is None:
                child.terminate()
                try:child.wait(timeout=5)
                except subprocess.TimeoutExpired:child.kill();child.wait(timeout=5)

    def cancel(self):
        self.cancel_download.set()
        return self.status()

    def _download(self, asset, target):
        partial=target.with_name(target.name+'.partial');count=0;checksum=hashlib.sha256();started=time.monotonic();last_persist=0
        try:
            from serve.customization_backup import snapshot
            backup=snapshot(self.root)
            with self.lock:self.job.update(customization_backup=backup);self._persist_job()
            if self.cancel_download.is_set():raise InterruptedError('Download cancelled')
            req=urllib.request.Request(asset['url'],headers={'User-Agent':'Strata-Update-Center'})
            with urllib.request.urlopen(req,timeout=30) as response, partial.open('xb') as output:
                while block:=response.read(1024*1024):
                    if self.cancel_download.is_set():raise InterruptedError('Download cancelled')
                    count+=len(block)
                    if count>asset['bytes']: raise ValueError('Download exceeds declared size')
                    output.write(block);checksum.update(block)
                    with self.lock:
                        now=time.monotonic();self.job.update(bytes=count,bytes_per_second=count/max(.01,now-started))
                        if now-last_persist>=.5:last_persist=now;self._persist_job()

            if self.cancel_download.is_set():raise InterruptedError('Download cancelled')
            if count!=asset['bytes'] or checksum.hexdigest()!=asset['digest'][7:]:
                raise ValueError('Release size or SHA-256 verification failed')
            partial.replace(target)
            manifest={'path':str(target),'sha256':checksum.hexdigest(),'bytes':count,'source':asset['url'],
                'published_version':self.job.get('version'),
                'integrity_verified':True,'runtime_validated':False,'activated':False}
            manifest['customization_backup']=backup
            target.with_name(target.name+'.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
            with self.lock:self.job.update(state='staged',result=manifest);self._persist_job()
        except Exception as error:
            partial.unlink(missing_ok=True)
            with self.lock:self.job.update(state='cancelled' if isinstance(error,InterruptedError) else 'failed',error=str(error));self._persist_job()


def refresh_running_environment(environment,executable):
    """Cached available versions may be reused; installed versions must match this process."""
    import importlib.metadata
    previous={normalize_package(row['name']):row for row in environment.get('packages',[])}
    packages=[]
    for distribution in importlib.metadata.distributions():
        name=distribution.metadata.get('Name')
        if not name:continue
        cached=previous.get(normalize_package(name),{});available=cached.get('available_version')
        packages.append({'name':name,'version':distribution.version,'available_version':available,
            'update_state':'current' if available==distribution.version else 'available' if available else 'unavailable'})
    environment.update(python=str(executable),python_version=sys.version.split()[0],packages=sorted(packages,key=lambda row:row['name'].lower()),
        state='inventoried',inventory_refreshed_at=time.time(),inventory_scope='running_dashboard_environment',dependency_health=check_dependencies(executable))

def check_dependencies(executable):
    """Read-only consistency check; never resolves or upgrades the active environment."""
    try:
        process=subprocess.run([str(executable),'-I','-m','pip','check'],capture_output=True,
            text=True,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        details=(process.stdout+'\n'+process.stderr).strip()
        if len(details)>32768:
            return {'state':'unavailable','details':'Dependency check output exceeds limit'}
        if process.returncode==0:
            return {'state':'healthy','details':details}
        if process.returncode==1 and 'No module named pip' not in details:
            return {'state':'conflicts','details':details}
        return {'state':'unavailable','details':details or 'Dependency check failed'}
    except (OSError,subprocess.TimeoutExpired) as error:
        return {'state':'unavailable','details':str(error)}


def normalize_package(name):
    import re
    return re.sub(r'[-_.]+','-',name).lower()


def library_updates(executable):
    """Query only official PyPI metadata; no package is downloaded or installed."""
    try:
        process=subprocess.run([str(executable),'-I','-m','pip','list','--outdated','--format=json',
            '--disable-pip-version-check','--index-url','https://pypi.org/simple','--timeout','8','--retries','0'],capture_output=True,
            text=True,timeout=60,env={**__import__('os').environ,'PIP_CONFIG_FILE':__import__('os').devnull,'PIP_INDEX_URL':'https://pypi.org/simple','PIP_EXTRA_INDEX_URL':'','PIP_FIND_LINKS':''},creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if process.returncode or len(process.stdout)>2*1024**2:
            raise ValueError((process.stderr or 'Package index check failed')[:2000])
        # Partial index failures must never be interpreted as an up-to-date environment.
        if any(word in process.stderr.lower() for word in ('error','warning','could not','failed')):
            raise ValueError(process.stderr[:2000])
        rows=json.loads(process.stdout)
        if not isinstance(rows,list) or any(not isinstance(row,dict) or not all(isinstance(row.get(key),str) for key in ('name','version','latest_version')) for row in rows):
            raise ValueError('Invalid package update response')
        return {'state':'checked','source':'https://pypi.org/simple','checked_at':time.time(),'outdated':rows}
    except (OSError,ValueError,subprocess.TimeoutExpired) as error:
        return {'state':'unavailable','error':str(error),'outdated':[]}


def shared_libraries(environments):
    packages={}
    for environment in environments:
        for package in environment.get('packages',[]):
            key=normalize_package(package['name'])
            packages.setdefault(key,[]).append({'environment':environment['name'],
                'installed_version':package['version'],'available_version':package.get('available_version')})
    return [{'name':name,'environments':rows,'versions_differ':len({row['installed_version'] for row in rows})>1,
        'scope':'separate_python_environments'} for name,rows in sorted(packages.items()) if len(rows)>1]


def platform_compatibility(filename):
    import platform
    name=filename.lower();system=platform.system().lower();machine=platform.machine().lower()
    named_os=next((value for value in ('windows','linux','macos','darwin') if value in name),None)
    expected='darwin' if system=='darwin' else system
    if named_os and ('darwin' if named_os=='macos' else named_os)!=expected:
        return {'state':'incompatible','reason':'Package is built for a different operating system'}
    arm=machine in ('arm64','aarch64')
    if ('arm64' in name or 'aarch64' in name) and not arm:
        return {'state':'incompatible','reason':'ARM package cannot run on this x64 host'}
    if ('x64' in name or 'x86_64' in name or 'amd64' in name) and arm:
        return {'state':'incompatible','reason':'x64 package requires separate validation on an ARM host'}
    return {'state':'platform_matches' if named_os else 'not_declared',
        'reason':'Platform match does not certify GPU, model or runtime compatibility'}


def recommend_package(row):
    """Match installed runtime flavor; never infer GPU compatibility from OS alone."""
    candidates=[a for a in row.get('assets',[]) if
        a.get('platform_compatibility',{}).get('state')=='platform_matches'
        and str(a.get('digest') or '').startswith('sha256:')
        and not any(word in a.get('name','').lower() for word in ('source','manifest','sha256','cudart'))]
    backend=str(row.get('installed_backend') or '').lower()
    if row.get('id')=='colibri':
        suffix='windows-x86_64-cuda.zip' if backend=='cuda' else 'windows-x86_64.zip' if backend in ('vulkan','cpu') else None
        matches=[a for a in candidates if suffix and a['name'].endswith(suffix)]
        return {'asset_id':matches[0]['id'] if len(matches)==1 else None,'reason':'official_colibri_backend_package' if len(matches)==1 else 'compatible_package_unavailable','backend':backend}
    target=str(row.get('installed_gpu_target') or '').lower()
    flavor={'rocm':'rocm','hip':'hip','cuda':'cuda','vulkan':'vulkan','cpu':'cpu'}.get(backend)
    if flavor:
        candidates=[a for a in candidates if flavor in a['name'].lower()]
        if target:candidates=[a for a in candidates if target in a['name'].lower()]
        if not candidates:return {'asset_id':None,'reason':'installed_runtime_variant_unavailable','backend':backend,'gpu_target':target}
    elif row.get('id')=='unsloth':
        candidates=[a for a in candidates if 'desktop' in a['name'].lower()]
    else:
        return {'asset_id':None,'reason':'runtime_variant_not_detected'}
    if not candidates:return {'asset_id':None,'reason':'no_verified_package'}
    # Prefer the regular CPU build over portable when both exist.
    candidates.sort(key=lambda a:('portable' in a['name'].lower(),a['name']))
    return {'asset_id':candidates[0]['id'],'reason':'installed_runtime_match' if flavor else 'desktop_platform_match','backend':backend,'gpu_target':target}

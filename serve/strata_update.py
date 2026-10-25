"""Select a proven isolated Strata build, preserving the previous configuration."""
import json,time,uuid
from pathlib import Path
from serve.configuration import atomic_json

def candidate_proof(root,candidate):
    try:
        proof_path=Path(root)/'output/verification/strata-candidate-inference-real.json'
        if not proof_path.is_file():proof_path=Path(root)/'output/verification/strata-v0142-bounded-real.json'
        report=json.loads(proof_path.read_text(encoding='utf-8'))
        if report.get('finished_at',0)<candidate.get('validation_started_at',0):return None
        cfg=report['validated_configuration']
        directory=Path(candidate['candidate_directory']).resolve()
        executable=Path(cfg['exe']).resolve()
        manifest=next(row for row in candidate['files'] if (directory/row['path']).resolve()==executable)
        if report.get('passed') is not True or report.get('full_profile') is not True or report.get('watchdog_errors') or time.time()-report['finished_at']>86400:return None
        if executable!=directory/'strata.exe' or report['exe_sha256']!=manifest['sha256']:return None
        if not report.get('response',{}).get('choices',[{}])[0].get('message',{}).get('content'):return None
        return report
    except (OSError,ValueError,KeyError,TypeError,StopIteration,IndexError):return None

def activate(root,config_path,candidate):
    from serve.update_center import file_sha256
    from serve.customization_backup import snapshot
    root=Path(root);path=Path(config_path or '').resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():raise ValueError('Active configuration must be inside the workspace')
    proof=candidate_proof(root,candidate)
    if not proof:raise ValueError('A recent full-profile Strata response is required before selection')
    directory=Path(candidate['candidate_directory']).resolve()
    if not directory.is_relative_to((root/'output/updates/candidates').resolve()):raise ValueError('Invalid candidate directory')
    for row in candidate['files']:
        file=(directory/row['path']).resolve()
        if not file.is_relative_to(directory) or not file.is_file() or file_sha256(file)!=row['sha256']:raise ValueError('Validated candidate has changed')
    previous=json.loads(path.read_text(encoding='utf-8-sig'));profile=proof['validated_configuration']
    if previous.get('model_name')!=profile.get('model_name') or previous.get('tokenizer')!=profile.get('tokenizer'):raise ValueError('Validated profile belongs to a different model')
    backup=snapshot(root)
    folder=root/'output/updates/strata-configs';folder.mkdir(parents=True,exist_ok=True)
    original=folder/(uuid.uuid4().hex+'.json');original.write_bytes(path.read_bytes())
    # UI, sampling, API keys, model metadata and custom source files stay intact.
    updated={**previous,**{key:profile[key] for key in ('exe','lib_dirs','backend')}}
    atomic_json(path,updated)
    selection=dict(config=str(path),config_sha256=file_sha256(path),previous_config=str(original),
        previous_sha256=file_sha256(original),directory=str(directory),version=proof['engine']['version'],
        validation_scope=proof['scope'],selected_at=time.time(),restart_required=True)
    atomic_json(root/'data/strata-runtime-selection.json',dict(active=selection,backup=backup))
    return selection

def rollback(root):
    from serve.update_center import file_sha256
    root=Path(root);registry=root/'data/strata-runtime-selection.json'
    data=json.loads(registry.read_text(encoding='utf-8'));active=data.get('active')
    if not active:raise ValueError('No selected Strata build to restore')
    path=Path(active['config']).resolve();previous=Path(active['previous_config']).resolve()
    if not path.is_relative_to(root.resolve()) or not previous.is_relative_to((root/'output/updates/strata-configs').resolve()):raise ValueError('Invalid saved configuration path')
    if file_sha256(path)!=active['config_sha256']:raise ValueError('Configuration changed after selection; restore manually to preserve your edits')
    if file_sha256(previous)!=active['previous_sha256']:raise ValueError('Saved configuration has changed')
    # Atomic replace restores original bytes, including formatting and encoding.
    from tempfile import NamedTemporaryFile
    import os
    with NamedTemporaryFile(dir=path.parent,delete=False) as stream:
        stream.write(previous.read_bytes());temporary=stream.name
    try:os.replace(temporary,path)
    finally:
        if Path(temporary).exists():Path(temporary).unlink()
    atomic_json(registry,dict(active=None,previous=active,rolled_back_at=time.time(),backup=data.get('backup')))
    return active


def selected_configuration(root,configuration):
    """Apply the selected verified engine to profiles sharing its original install.

    Model arguments and tuning remain profile-owned. Rollback clears this override.
    A changed candidate fails visibly rather than silently starting an old engine.
    """
    from serve.update_center import file_sha256
    root=Path(root).resolve();registry=root/'data/strata-runtime-selection.json'
    if not registry.is_file():return configuration
    saved=json.loads(registry.read_text(encoding='utf-8'));active=saved.get('active')
    if not active:return configuration
    directory=Path(active['directory']).resolve();previous=Path(active['previous_config']).resolve()
    if not directory.is_relative_to(root/'output/updates/candidates') or not previous.is_relative_to(root/'output/updates/strata-configs'):raise ValueError('Invalid selected engine paths')
    if file_sha256(previous)!=active['previous_sha256']:raise ValueError('Saved engine configuration changed')
    original=json.loads(previous.read_text(encoding='utf-8-sig'))
    def executable(value):
        path=Path(value);return path.resolve() if path.is_absolute() else (root/path).resolve()
    current=executable(configuration.get('exe',''))
    if current not in (executable(original['exe']),directory/'strata.exe'):return configuration
    manifest=json.loads((directory/'CANDIDATE-MANIFEST.json').read_text(encoding='utf-8'))
    if Path(manifest['candidate_directory']).resolve()!=directory:raise ValueError('Engine manifest mismatch')
    for row in manifest['files']:
        path=(directory/row['path']).resolve()
        if not path.is_relative_to(directory) or not path.is_file() or file_sha256(path)!=row['sha256']:raise ValueError('Selected engine candidate changed')
    build=json.loads((directory/'BUILD.json').read_text(encoding='utf-8'))
    if str(build['version'])!=str(active['version']):raise ValueError('Selected engine version mismatch')
    return {**configuration,'exe':str(directory/'strata.exe'),
            'lib_dirs':[str((directory/name).resolve()) for name in build.get('lib_dirs',[])],
            'selected_engine_version':active['version']}

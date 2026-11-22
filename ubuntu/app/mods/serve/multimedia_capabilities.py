"""Report each specialized media workflow that this build actually wires."""


def _worker_row(identifier, service, attribute, endpoints, models=None, extra=None):
    row = {'id': identifier, 'implemented': service is not None, 'available': False,
           'endpoints': list(endpoints) if service is not None else [],
           'models': list(models or []), 'quality_verified': None,
           'verification_scope': 'registered_local_models_only' if service is not None else 'not_implemented'}
    if service is None:
        row['reason'] = 'No ' + identifier.replace('_', ' ') + ' worker is integrated.'
        return row
    if extra:
        row.update(extra)
    return row
def _audio_task(service, task, attribute, endpoints):
    row = {'id': task, 'implemented': True, 'available': False,
           'endpoints': endpoints, 'quality_verified': None,
           'verification_scope': 'runtime_and_local_model_presence_only'}
    try:
        state = getattr(service, attribute).status()
        installed = state.get('installed') is True
        models = state.get('models') or []
        row.update(runtime_installed=installed, models=models,
                   status=state.get('status'), device=state.get('device'),
                   busy=state.get('busy') is True,
                   available=installed and bool(models) and state.get('status') != 'error')
        if state.get('error'):
            row['error'] = state['error']
        if task == 'asr':
            row['formats'] = state.get('formats') or []
            row['limits'] = {'input_bytes': state.get('input_limit_bytes'),
                             'duration_seconds': state.get('duration_limit_s')}
    except (OSError, ValueError, RuntimeError) as error:
        row.update(status='error', error=str(error))
    return row


def capabilities(service):
    """Read current worker metadata; never start a model or import GPU frameworks."""
    tasks = [
        _audio_task(service, 'asr', 'local_audio',
                    ['/v1/audio/transcriptions', '/v1/audio/translations']),
        _audio_task(service, 'tts', 'local_speech', ['/v1/audio/speech']),
    ]
    visual = getattr(service, 'local_visual', None)
    visual_models = []
    if visual:
        try:
            visual_models = visual.status().get('models') or []
        except (OSError, ValueError, RuntimeError):
            visual_models = []
    for kind in ('image', 'video'):
        rows = [row for row in visual_models if row.get('kind') == kind]
        tasks.append(_worker_row(kind + '_generation', visual, 'local_visual',
                                 ['/local-visual/start'], rows,
                                 extra={'available': any(not row.get('test_fixture') for row in rows),
                                        'supported_families': ['StableDiffusionPipeline',
                                                               'StableDiffusionXLPipeline',
                                                               'TextToVideoSDPipeline']}))
    audio = getattr(service, 'local_generative_audio', None)
    audio_models = []
    if audio:
        try:
            audio_state = audio.status()
            audio_models = audio_state.get('models') or []
            runtime_installed = audio_state.get('runtime_installed')
        except (OSError, ValueError, RuntimeError):
            runtime_installed = None
    else:
        runtime_installed = None
    for task in ('music', 'voice_conversion'):
        rows = [row for row in audio_models if row.get('task') == task]
        tasks.append(_worker_row(task, audio, 'local_generative_audio',
                                 ['/local-generative-audio/start'], rows,
                                 extra={'runtime_installed': runtime_installed,
                                        'available': runtime_installed and bool(rows)}))
    separation = getattr(service, 'local_separation', None)
    row = _worker_row('separation', separation, 'local_separation', ['/local-separation/run'])
    if separation:
        try:
            state = separation.status()
            row.update(status=state.get('status'), busy=separation.lock.locked()
                       if hasattr(separation, 'lock') else None,
                       models=state.get('models') or [],
                       available=bool(state.get('models')) and state.get('status') != 'error')
            if state.get('error'):
                row['error'] = state['error']
        except (OSError, ValueError, RuntimeError) as error:
            row.update(status='error', error=str(error))
    tasks.append(row)
    return {'schema_version': 1, 'tasks': tasks}

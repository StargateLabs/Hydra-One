"""Bounded read-only history of software checks, separate from model benchmarks."""
import json
import math
from pathlib import Path


def verification_history(root):
    root=Path(root).resolve();folder=root/'output/verification';rows=[]
    paths=list(folder.glob('server-suite-isolated-*/server-suite.json'))
    paths.extend(folder.glob('implementation-checks-*/report.json'))
    paths.extend(folder/name for name in ('server-isolated-current.json','implementation-checks-current.json'))
    seen=set()
    for path in sorted(paths,key=lambda p:p.stat().st_mtime if p.exists() else 0,reverse=True)[:50]:
        try:
            if not path.resolve().is_relative_to(folder.resolve()) or not path.is_file() or path.is_symlink() or path.stat().st_size>65536:continue
            report=json.loads(path.read_text(encoding='utf-8-sig'))
            log=Path(report['log']).resolve()
            if not log.is_relative_to(folder.resolve()) or not log.is_file():continue
            canonical=log.parent/('report.json' if log.name=='checks.log' else 'server-suite.json')
            if path.resolve()!=canonical and canonical.is_file():continue
            if str(log) in seen:continue
            code=report.get('exit_code');seconds=report.get('seconds')
            if type(code) is not int or type(seconds) not in (int,float) or not math.isfinite(seconds) or seconds<0:continue
            rows.append(dict(id=log.parent.name if log.parent!=folder.resolve() else path.stem,
                             status='passed' if code==0 else 'failed',seconds=seconds,
                             completed_at=report.get('completed_at'),source=path.relative_to(root).as_posix(),
                             scope=report.get('scope',''),source_sha256=report.get('source_sha256')))
            seen.add(str(log))
        except (OSError,ValueError,KeyError,TypeError):continue
    evidence={
        'strata-update-selection-rollback-real.json':lambda r:r.get('passed') is True and r.get('selected_version')=='0.1.42' and r.get('restored_version')=='0.1.40.3' and r.get('original_executable_preserved') is True and r.get('final_state')=='unloaded',
        'strata-v0142-bounded-real.json':lambda r:r.get('passed') is True and r.get('full_profile') is True and not r.get('watchdog_errors') and bool(r.get('response',{}).get('choices',[{}])[0].get('message',{}).get('content')),
        'safetensors-gpu-bounded-real.json':lambda r:r.get('passed') is True and r.get('backend',{}).get('device')=='cuda' and r.get('backend',{}).get('dtype')=='torch.float16' and r.get('final_backend_status')=='idle',
        'strata-update-startup-real.json':lambda r:r.get('startup_validation',{}).get('passed') is True and r.get('startup_validation',{}).get('gpu_inference_verified') is False and r.get('runtime_validated') is False and r.get('activated') is False,
        'gguf-parts-cpu-real.json':lambda r:r.get('greedy_response_equal') is True and r.get('gpu_used') is False and len(r.get('parts',[]))>1,
        'whisper-update-cpu-real.json':lambda r:r.get('original_preserved') is True and r.get('gpu_used') is False and bool(r.get('response',{}).get('text')),
        'audio-update-cpu-real.json':lambda r:r.get('gpu_used') is False and r.get('validated',{}).get('state')=='validated',
        'audio-library-browser.json':lambda r:r.get('played_seconds',0)>0 and len(r.get('layouts',[]))>=6,
        'gguf-parts-catalogue-browser.json':lambda r:r.get('entry',{}).get('parts',0)>1 and len(r.get('layouts',[]))>=6,
        'software-history-browser.json':lambda r:len(r.get('layouts',[]))>=6,
        'chat-regenerate-real.json':lambda r:r.get('regenerated',{}).get('busy') is False and bool(r.get('regenerated',{}).get('text')) and not r.get('regenerated',{}).get('error') and r.get('regenerated',{}).get('time',0)>r.get('original',{}).get('time',0),
        'optional-benchmark-browser-real.json':lambda r:r.get('history_visible') is True and r.get('job',{}).get('status')=='complete' and r.get('job',{}).get('completed_samples')==6,
        'optional-benchmark-safetensors-browser-real.json':lambda r:r.get('history_visible') is True and r.get('job',{}).get('status')=='complete' and r.get('job',{}).get('completed_samples')==6,
    }
    evidence.update({
        'llama-b11541-gpu-real.json':lambda r:r.get('passed') is True and r.get('gpu_offload_confirmed') is True and r.get('owned_process_stopped') is True and r.get('original_preserved') is True,
        'llama-b11541-gpu-selection-real.json':lambda r:r.get('passed') is True and r.get('cpu_selection_unchanged') is True and r.get('rollback_to_original_verified') is True and r.get('final_gpu_selected') is True,
        'llama-gpu-update-browser-real.json':lambda r:r.get('passed') is True and r.get('realApiActions') is True and len(r.get('layouts',[]))==6 and not r.get('errors'),
        'llama-b11541-gpu-app-benchmark-real.json':lambda r:r.get('passed') is True and r.get('job',{}).get('status')=='complete' and r.get('job',{}).get('completed_samples')==4 and r.get('final_backend_status')=='idle',
        'unsloth-native-nf4-gpu-real.json':lambda r:r.get('passed') is True and r.get('quantization')=='nf4' and r.get('quantized_gpu_modules',0)>0 and r.get('device')=='cuda:0' and bool(r.get('answer')),
        'unsloth-nf4-app-benchmark-real.json':lambda r:r.get('passed') is True and r.get('state',{}).get('quantization')=='nf4' and r.get('benchmark',{}).get('status')=='complete' and r.get('final_backend_status')=='idle',
        'qlora-checkpoint-menu-browser.json':lambda r:r.get('passed') is True and r.get('configurationRestored') is True and len(r.get('layouts',[]))==6,
        'qlora-checkpoint-resume-api-real.json':lambda r:r.get('passed') is True and r.get('source_checkpoint_unchanged') is True and r.get('checkpoint_integrity_verified') is True and r.get('resumed_step')==2,
        'qlora-conversation-api-real.json':lambda r:r.get('passed') is True and r.get('state',{}).get('status')=='complete' and r.get('state',{}).get('workflow',{}).get('loss_scope')=='assistant_only' and r.get('state',{}).get('workflow',{}).get('export_greedy_tokens_equal') is True,
        'unsloth-qlora-managed-api-real.json':lambda r:r.get('passed') is True and r.get('state',{}).get('status')=='complete' and r.get('state',{}).get('runner')=='unsloth_qlora' and r.get('state',{}).get('workflow',{}).get('export_greedy_tokens_equal') is True,
        'unsloth-qlora-native-gpu-real.json':lambda r:r.get('passed') is True and r.get('device')=='cuda' and r.get('steps')==1 and r.get('changed_lora_modules',0)>0 and type(r.get('loss')) in (int,float) and math.isfinite(r['loss']) and r.get('export_greedy_tokens_equal') is True,
        'training-history-restore-browser.json':lambda r:r.get('passed') is True and r.get('configurationRestored') is True,
        'audio-editor-language-browser.json':lambda r:r.get('passed') is True and r.get('intervalValidation') is True and r.get('liveLanguageChange') is True,
        'draft-controls-browser.json':lambda r:r.get('passed') is True and r.get('runtime',{}).get('draft_max')==24 and r.get('runtime',{}).get('draft_probability')==.8,
        'draft-runtime-capabilities.json':lambda r:r.get('passed') is True and all(r.get('flags',{}).get(k) is True for k in ('--spec-draft-n-min','--spec-draft-n-max','--spec-draft-p-min')),
        'whisper-subtitles-real.json':lambda r:r.get('passed') is True and bool(r.get('result',{}).get('segments')) and bool(r.get('result',{}).get('srt')),
        'audio-import-browser-real.json':lambda r:r.get('passed') is True and r.get('result',{}).get('artifact',{}).get('audio_seconds')==1,
        'chat-history-context-browser.json':lambda r:r.get('passed') is True and r.get('draftCleared') is True and r.get('historyRestored') is True,
        'audio-edit-browser-real.json':lambda r:r.get('passed') is True and r.get('result',{}).get('artifact',{}).get('audio_seconds')==.5 and r.get('result',{}).get('operation',{}).get('channels')==1 and len(r.get('layouts',[]))==4,
        'audio-compressed-export-browser-real.json':lambda r:r.get('passed') is True and r.get('formats')==['mp3','flac','ogg'] and len(r.get('layouts',[]))==6 and not r.get('errors'),
        'safetensors-generation-timing-real.json':lambda r:r.get('passed') is True and len(r.get('runs',[]))==2 and all(x.get('timings',{}).get('generation_ms',0)>0 and x.get('timings',{}).get('timing_scope')=='model.generate_including_prefill' for x in r.get('runs',[])),
        'harness-shared-browser-memory-real.json':lambda r:r.get('passed') is True and r.get('real_browser_navigation') is True and r.get('shared_memory_write_read') is True and r.get('existing_memory_preserved') is True and r.get('browser_tools',0)>0 and r.get('memory_tools')==9,
        'localai-four-official-logos-browser.json':lambda r:r.get('passed') is True and len(r.get('rows',[]))==4 and r.get('titleRestored') is True and not r.get('errors'),
        'localai-four-harness-ports.json':lambda r:r.get('passed') is True and len(r.get('rows',[]))==4 and r.get('strata_8088_left_running') is True,
        'localai-storage-migration-real.json':lambda r:r.get('passed') is True and r.get('originalRetained') is True and r.get('existingPreserved') is True,
        'context-mode-global-real.json':lambda r:r.get('passed') is True and r.get('global_install') is True and r.get('stats_call_passed') is True,
        'localai-mcp-real.json':lambda r:r.get('passed') is True and len(r.get('calls',[]))==5 and all(row.get('passed') is True for row in r['calls']),
        'localai-mcp-status-browser.json':lambda r:r.get('passed') is True and r.get('disabledCount')==0 and r.get('selectedCount')==1,
        'localai-model-files-memory-real.json':lambda r:r.get('passed') is True and len(r.get('rows',[]))==2 and all(row.get('passed') is True for row in r['rows']),
        'chat-delete-localai-real.json':lambda r:r.get('passed') is True and r.get('persistedAfterReload') is True and not r.get('errors'),
        'chat-toolbar-layout.json':lambda r:r.get('passed') is True and len(r.get('rows',[]))==4,
        'harness-official-logos-browser.json':lambda r:r.get('passed') is True and len(r.get('rows',[]))==3 and r.get('titleRestored') is True and not r.get('errors'),
        'harness-native-three-inline-real.json':lambda r:r.get('passed') is True and r.get('draftPreserved') is True and len(r.get('rows',[]))==9 and not r.get('errors'),
        'trueforge-pc-memory-real.json':lambda r:r.get('passed') is True and r.get('tools')==47 and r.get('readme_read') is True and r.get('memory_tools',0)>0,
        'harness-native-inline-real.json':lambda r:r.get('passed') is True and r.get('draftPreserved') is True and len(r.get('rows',[]))==6 and not r.get('errors'),
        'audio-compressed-export-api-real.json':lambda r:r.get('passed') is True and r.get('original_preserved') is True and {x.get('format') for x in r.get('formats',[])}=={'mp3','flac','ogg'},
        'soup-streaming-app-real.json':lambda r:r.get('passed') is True and r.get('state',{}).get('status')=='complete' and r.get('state',{}).get('workflow',{}).get('streaming_active') is True and r.get('state',{}).get('workflow',{}).get('export_greedy_tokens_equal') is True,
        'htdemucs-long-chunks-real.json':lambda r:r.get('passed') is True and r.get('result',{}).get('input_seconds')==61 and r.get('result',{}).get('chunks')==2 and len(r.get('result',{}).get('stems',[]))==4,
        'htdemucs-minute-real.json':lambda r:r.get('passed') is True and r.get('result',{}).get('input_seconds')==60 and len(r.get('result',{}).get('stems',[]))==4,
        'local-model-manager-browser.json':lambda r:r.get('passed') is True and r.get('searchVerified') is True and r.get('deleteRequests')==0 and len(r.get('layouts',[]))==6 and not r.get('errors'),
        'qlora-managed-menu-browser.json':lambda r:r.get('passed') is True and r.get('adapterConfigMatchesRealTraining') is True and len(r.get('layouts',[]))==6 and not r.get('errors'),
        'unsloth-qlora-adapter-app-real.json':lambda r:r.get('passed') is True and r.get('state',{}).get('quantization')=='nf4' and r.get('benchmark',{}).get('status')=='complete' and r.get('final_backend_status')=='idle',
        'htdemucs-batch-real.json':lambda r:r.get('passed') is True and r.get('outputs')==4 and len(r.get('result',{}).get('stems',[]))==4,
        'performance-spectrum-browser.json':lambda r:r.get('passed') is True and r.get('metricsVerifiedAgainstRealReports') is True and len(r.get('layouts',[]))==12 and not r.get('errors'),
        'performance-workspace-browser.json':lambda r:r.get('passed') is True and r.get('realDataPagination') is True and r.get('filteredCsv') is True and len(r.get('layouts',[]))==12 and not r.get('errors'),
        'benchmark-future-quality-browser.json':lambda r:r.get('passed') is True and r.get('caseCount')==12 and r.get('categories')==4 and r.get('disclosuresPreservedDuringRefresh') is True and len(r.get('layouts',[]))==6 and not r.get('errors'),

        'ai-lab-p95-gpu-real.json':lambda r:r.get('passed') is True and r.get('job',{}).get('status')=='complete' and r.get('job',{}).get('results',[{}])[0].get('summary',{}).get('wall_tok_s',{}).get('count')==20 and type(r.get('job',{}).get('results',[{}])[0].get('summary',{}).get('wall_tok_s',{}).get('p95')) in (int,float),
        'ai-lab-one-click-gpu-real.json':lambda r:r.get('passed') is True and r.get('job',{}).get('status')=='complete' and r.get('job',{}).get('completed_samples')==18 and r.get('job',{}).get('results',[{}])[0].get('quality',{}).get('total')==12 and len(r.get('layouts',[]))==6 and not r.get('errors'),
        'soup-0752-gpu-dashboard-real.json':lambda r:r.get('passed') is True and r.get('state',{}).get('status')=='complete' and r.get('state',{}).get('device')=='cuda' and r.get('state',{}).get('workflow',{}).get('soup_version')=='0.75.2' and r.get('state',{}).get('workflow',{}).get('export_greedy_tokens_equal') is True,
        'separation-browser-real.json':lambda r:r.get('passed') is True and r.get('outputs')==4 and len(r.get('layouts',[]))==6 and not r.get('errors'),
        'soup-selection-rollback-real.json':lambda r:r.get('passed') is True and r.get('versions')==['0.75.2','0.75.0','0.75.2'] and r.get('original_environment_preserved') is True,
        'web-assets-cache-real.json':lambda r:r.get('passed') is True and r.get('logo_repeat_status')==304 and r.get('logo_repeat_body_bytes')==0,
        'safetensors-unsloth-gpu-bounded-real.json':lambda r:r.get('passed') is True and r.get('backend',{}).get('native_loader')=='unsloth' and r.get('benchmark',{}).get('status')=='complete' and r.get('final_backend_status')=='idle',
        'pocket-tts-dashboard-real.json':lambda r:r.get('passed') is True and r.get('result',{}).get('audio_seconds',0)>0 and bool(r.get('result',{}).get('artifact',{}).get('sha256')) and r.get('final_state')=='idle',
        'model-delete-menu-browser.json':lambda r:r.get('passed') is True and r.get('cancelled') is True and r.get('noModelDeleted') is True and not r.get('errors'),
        'training-gpu-api-real.json':lambda r:r.get('passed') is True and r.get('state',{}).get('device')=='cuda' and r.get('state',{}).get('status')=='complete' and r.get('state',{}).get('workflow',{}).get('export_logits_verified') is True,
        'chat-delete-browser.json':lambda r:r.get('passed') is True and not r.get('errors') and r.get('state',{}).get('count')==0,
        'chat-unified-toolbar.json':lambda r:r.get('passed') is True and r.get('mcp_popover') is True and len(r.get('results',[]))==3,
        'official-engine-logos.json':lambda r:r.get('passed') is True and r.get('details')==6 and all(row.get('loaded') is True for row in r.get('rows',[])),
    })
    # The same proof contract applies to both local chat runtimes.
    for name in ('chat-regenerate-gguf-real.json','chat-regenerate-safetensors-real.json'):
        evidence[name]=evidence['chat-regenerate-real.json']
    evidence['optional-benchmark-gguf-browser-real.json']=evidence['optional-benchmark-browser-real.json']
    for name,verified in evidence.items():
        path=folder/name
        try:
            if not path.resolve().is_relative_to(folder.resolve()) or path.is_symlink() or path.stat().st_size>1024**2:continue
            report=json.loads(path.read_text(encoding='utf-8-sig'))
            if not verified(report):continue
            rows.append(dict(id=path.stem,status='passed',seconds=None,completed_at=path.stat().st_mtime,
                             source=path.relative_to(root).as_posix(),scope=report.get('scope',''),kind='functional_evidence'))
        except (OSError,ValueError,KeyError,TypeError,AttributeError):continue
    return sorted(rows,key=lambda row:row.get('completed_at') if type(row.get('completed_at')) in (int,float) else 0,reverse=True)

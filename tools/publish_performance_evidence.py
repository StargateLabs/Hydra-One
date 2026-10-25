"""Publish verified local evidence for the two performance pages, without GPU work."""
import json
import re
from pathlib import Path
from summarize_full_resident_abba import summarize

ROOT = Path(__file__).resolve().parents[1]

def summary_files(directory, kind, phase):
    pattern = re.compile(r'\d{8}-\d{6}-'+re.escape(kind)+'-'+re.escape(phase)+r'-summary\.json')
    return sorted(path for path in directory.glob(f'*-{kind}-{phase}-summary.json') if pattern.fullmatch(path.name))

def investigations(model):
    rows = []
    for suffix, title in (('adapt-lag2-measure', 'Scambi ritardati'), ('adapt-async-measure', 'Scambi asincroni'), ('draft-it-measure', 'Draft italiano')):
        paths = sorted((ROOT / 'data/benchmarks').glob(f'*-iq3-memory-{suffix}.json'))
        if not paths:
            continue
        report = json.loads(paths[-1].read_text(encoding='utf-8'))
        if report.get('status') != 'complete' or report.get('engine', {}).get('model') != model:
            continue
        samples = [r for r in report.get('rows', []) if r.get('warmup') is False]
        if len(samples) != 5 or any(r.get('output_tokens') != 256 or r.get('reused') != 0 for r in samples):
            raise RuntimeError('Invalid investigative report')
        rows.append({'title': title, 'decode': report['summary']['decode_tok_s']['median'],
                     'status': 'Prova singola · non adottato', 'source': paths[-1].relative_to(ROOT).as_posix()})
    return rows

def main():
    summaries = sorted((ROOT / 'output/verification').glob('*-full-resident-abba-summary.json'))
    if not summaries:
        raise RuntimeError('No verified ABBA summary')
    latest = json.loads(summaries[-1].read_text(encoding='utf-8'))
    summarize(latest['stamp'])  # Revalidate complete raw reports, pairing and executable.
    latest = json.loads(summaries[-1].read_text(encoding='utf-8'))
    raw = ROOT / 'data/benchmarks' / f"{latest['stamp']}-iq3-memory-ram16-auto-a1.json"
    reference = json.loads(raw.read_text(encoding='utf-8'))
    payload = {'schema_version': 1, 'model': reference['engine']['model'],
               'measured_at': reference['started_at'], 'comparison': latest,
               'source': summaries[-1].relative_to(ROOT).as_posix(),
               'decision': 'candidate', 'quality': 'pending', 'endurance': 'pending',
               'investigations': investigations(reference['engine']['model'])}
    drafts = sorted((ROOT/'output/verification').glob('*-draft-it-abba-summary.json'))
    if drafts:
        from summarize_draft_abba import summarize as summarize_draft
        draft = json.loads(drafts[-1].read_text(encoding='utf-8'))
        validated = summarize_draft(draft['stamp'])
        if validated['model'] == payload['model']:
            payload['draft_comparison'] = validated
            qualities = sorted((ROOT/'output/verification').glob('*-draft-quality-summary.json'))
            if qualities:
                quality = json.loads(qualities[-1].read_text(encoding='utf-8'))
                if (quality.get('status') == 'complete' and quality.get('candidate_sha256') == validated['draft_candidate_sha256']
                    and quality.get('total') == 12 and quality.get('model') == payload['model']):
                    payload['draft_quality'] = quality
    tsum_paths = sorted((ROOT/'output/verification').glob('*-tsum-abba-summary.json'))
    if tsum_paths:
        from summarize_tsum_abba import summarize as summarize_tsum
        tsum = json.loads(tsum_paths[-1].read_text(encoding='utf-8'))
        validated_tsum = summarize_tsum(tsum['stamp'])
        if validated_tsum['model'] == payload['model']:
            payload['tsum_comparison'] = validated_tsum
            change = validated_tsum['pooled']['decode_tok_s']['change_percent']
            payload['investigations'].append({
                'title':'Somme raggruppate · ABBA',
                'decode':validated_tsum['pooled']['decode_tok_s']['candidate'],
                'status':f'{change:+.2f}% vs controllo · non adottato',
                'source':tsum_paths[-1].relative_to(ROOT).as_posix()})
            quality_paths = sorted((ROOT/'output/verification').glob('*-tsum-quality-summary.json'))
            if quality_paths:
                from summarize_tsum_quality import summarize as summarize_tsum_quality
                quality_stamp = quality_paths[-1].name.removesuffix('-tsum-quality-summary.json')
                quality_tsum = summarize_tsum_quality(quality_stamp)
                if quality_tsum['model'] == payload['model']:
                    payload['tsum_quality'] = quality_tsum
                    regression = f" · {len(quality_tsum['regressed_cases'])} regressioni nei 12 compiti" if quality_tsum['regressed_cases'] else ' · nessuna regressione nei 12 compiti'
                    payload['investigations'][-1]['status'] += f" · qualità {quality_tsum['control_correct']}/12 → {quality_tsum['candidate_correct']}/12" + regression
    learned_paths = sorted((ROOT/'output/verification').glob('*-learned-profile-abba-summary.json'))
    if learned_paths:
        from summarize_learned_profile import summarize as summarize_learned
        learned = json.loads(learned_paths[-1].read_text())
        validated_learned = summarize_learned(learned['stamp'])
        if validated_learned['model'] == payload['model']:
            payload['learned_comparison'] = validated_learned
            payload['latest_comparison'] = validated_learned
            payload['latest_kind'] = 'learned_profile'
            payload['latest_decision'] = 'not_adopted'
            metric = validated_learned['pooled']['decode_tok_s']
            payload['investigations'].append(dict(title='Cache appresa · ABBA',decode=metric['candidate'],
                status=f"{metric['change_percent']:+.2f}% vs controllo {metric['control']:.2f} t/s · non adottato",
                source=learned_paths[-1].relative_to(ROOT).as_posix()))
            profile_quality_paths = sorted((ROOT/'output/verification').glob('*-profile-quality-summary.json'))
            if profile_quality_paths:
                from summarize_profile_quality import summarize as summarize_profile_quality
                quality_stamp = profile_quality_paths[-1].name.removesuffix('-profile-quality-summary.json')
                quality_profile = summarize_profile_quality(quality_stamp)
                if quality_profile['candidate_sha256'] == validated_learned['candidate_sha256'] and quality_profile['binary_sha256'] == validated_learned['binary_sha256']:
                    payload['learned_quality'] = quality_profile
                    payload['latest_quality'] = quality_profile
                    regression = f" · {len(quality_profile['regressed_cases'])} regressioni nei 12 compiti" if quality_profile['regressed_cases'] else ' · nessuna regressione nei 12 compiti'
                    payload['investigations'][-1]['status'] += f" · qualità {quality_profile['control_correct']}/12 → {quality_profile['candidate_correct']}/12" + regression
    for percent in (55,20):
        kind=f'pcie{percent}'
        paths=summary_files(ROOT/'output/verification',kind,'abba')
        if not paths:continue
        from summarize_pcie_abba import summarize as summarize_pcie
        item=json.loads(paths[-1].read_text());comparison=summarize_pcie(item['stamp'],percent)
        if comparison['model']!=payload['model']:continue
        payload[kind+'_comparison']=comparison
        quality=None
        qualities=summary_files(ROOT/'output/verification',kind,'quality')
        if qualities:
            from summarize_pcie_quality import summarize as summarize_quality
            quality=summarize_quality(qualities[-1].name.removesuffix(f'-{kind}-quality-summary.json'),percent)
            if quality['model']==payload['model'] and quality['binary_sha256']==comparison['binary_sha256']:payload[kind+'_quality']=quality
            else:quality=None
        if comparison['stamp']>payload.get('latest_comparison',{}).get('stamp',''):
            payload.update(latest_comparison=comparison,latest_kind=kind,
                latest_decision='candidate' if comparison['pooled']['decode_tok_s']['change_percent']>1 and not (quality and quality['regressed_cases']) else 'not_adopted')
            payload.pop('latest_quality',None)
            if quality:payload['latest_quality']=quality
    from feature_plans import FEATURES,PARAMETERS
    from summarize_feature import summarize_abba as summarize_feature_abba, summarize_quality as summarize_feature_quality
    for feature in (*FEATURES,*PARAMETERS):
        paths = summary_files(ROOT/'output/verification',feature,'abba')
        if not paths:continue
        stamp = paths[-1].name.removesuffix(f'-{feature}-abba-summary.json')
        comparison = summarize_feature_abba(stamp,feature)
        if comparison['model'] != payload['model']:continue
        payload[feature+'_comparison'] = comparison
        qualities = summary_files(ROOT/'output/verification',feature,'quality')
        if qualities:
            quality = summarize_feature_quality(qualities[-1].name.removesuffix(f'-{feature}-quality-summary.json'),feature)
            if quality['model'] == comparison['model'] and quality['binary_sha256'] == comparison['binary_sha256']:
                payload[feature+'_quality'] = quality
        if comparison['stamp']>payload.get('latest_comparison',{}).get('stamp',''):
            quality=payload.get(feature+'_quality')
            payload.update(latest_comparison=comparison,latest_kind=feature,latest_decision='not_adopted' if quality and quality['regressed_cases'] else 'verify' if comparison.get('confounded') else 'candidate' if comparison['pooled']['decode_tok_s']['change_percent']>1 and not (quality and quality['regressed_cases']) else 'not_adopted')
            payload.pop('latest_quality',None)
            if quality:payload['latest_quality']=quality
    campaigns = []
    for key,title,quality_key,state in (
        ('comparison','Esperti residenti in RAM',None,'Beneficio sul prefill'),
        ('draft_comparison','Vocabolario draft italiano','draft_quality','Da confermare'),
        ('tsum_comparison','Somme raggruppate','tsum_quality','Da confermare'),
        ('learned_comparison','Cache appresa','learned_quality','Non adottata'),
        ('pcie55_comparison','Quota PCIe 55%','pcie55_quality','Non adottata'),
        ('pcie20_comparison','Quota PCIe 20%','pcie20_quality','Da confermare'),
        ('qfuse_comparison','QFUSE','qfuse_quality','Da verificare'),
        ('qfuse-pcie20_comparison','QFUSE su PCIe 20%','qfuse-pcie20_quality','Da verificare'),
        ('device-plan_comparison','Pianificazione GPU dei gruppi residenti','device-plan_quality','Da verificare'),
        ('minp70_comparison','Soglia del draft 70%','minp70_quality','Da verificare'),
        ('fill-workers_comparison','Thread di lettura persistenti','fill-workers_quality','Da verificare'),
        ('fetch4_comparison','Quattro thread di lettura','fetch4_quality','Da verificare'),
        ('iq3-spec3_comparison','Finestra speculativa 3 su IQ3_XXS','iq3-spec3_quality','Da verificare'),
        ('qfuse-draft_comparison','QFUSE con draft italiano su IQ3_XXS','qfuse-draft_quality','Da verificare'),
        ('tsum-draft_comparison','Somme raggruppate con draft italiano','tsum-draft_quality','Da verificare'),
        ('hc-small_comparison','Letture tra layer sulla RX 7900 XTX','hc-small_quality','Da verificare')):
        summary = payload.get(key)
        if not summary:continue
        metric = summary['pooled']['decode_tok_s']
        quality = payload.get(quality_key) if quality_key else None
        if key in ('qfuse_comparison','qfuse-pcie20_comparison','device-plan_comparison','minp70_comparison','fill-workers_comparison','fetch4_comparison','iq3-spec3_comparison','qfuse-draft_comparison','tsum-draft_comparison','hc-small_comparison'):
            state = 'Non adottata' if metric['change_percent'] <= 1 or (quality and quality['regressed_cases']) else 'Da confermare'
        if summary.get('confounded') and not (quality and quality['regressed_cases']):state='Da verificare'
        campaigns.append(dict(title=title,stamp=summary['stamp'],
            control=metric.get('control',metric.get('ram16')),
            candidate=metric.get('candidate',metric.get('full_resident')),
            change_percent=metric['change_percent'],quality=quality,state=state,limitations=summary.get('limitations',''),confounded=summary.get('confounded',False)))
    confirmations=summary_files(ROOT/'output/verification','minp70','interleaved')
    if confirmations:
        from summarize_interleaved import summarize as summarize_interleaved
        confirmation=summarize_interleaved(confirmations[-1].name.removesuffix('-minp70-interleaved-summary.json'))
        if confirmation['model']==payload['model']:
            payload['minp70_confirmation']=confirmation
            quality=payload.get('minp70_quality')
            campaigns.append(dict(title='Conferma alternata della soglia draft',stamp=confirmation['stamp'],control=confirmation['control'],candidate=confirmation['candidate'],change_percent=confirmation['change_percent'],quality=quality,state='Non adottata',limitations=confirmation['limitations'],confounded=False))
            if confirmation['stamp']>payload.get('latest_comparison',{}).get('stamp',''):
                payload.update(latest_comparison=confirmation,latest_kind='minp70-interleaved',latest_decision='not_adopted')
                payload.pop('latest_quality',None)
                if quality:payload['latest_quality']=quality
    payload['campaigns'] = campaigns
    payload['alternative_trials']=[]
    alternatives=sorted((ROOT/'data/benchmarks').glob('*-iq3-memory-hybrid-measure.json'))
    if alternatives:
        import hashlib,math
        report_path=alternatives[-1];report=json.loads(report_path.read_text());label=report['label'];config=json.loads((ROOT/f'output/verification/{label}.json').read_text());margin=json.loads((ROOT/f'output/verification/{label}-startup-margin.json').read_text())
        if report['status']!='complete' or len(report['rows'])!=10 or report['protocol']!=dict(warmup=5,runs=5,tokens=256,paragraphs=24,prompt_set='iq3-chunk-v1'):raise RuntimeError('Incomplete Hybrid protocol')
        if report['engine']['model']!=config['model_name'] or report['binary_sha256']!=hashlib.sha256(Path(config['exe']).read_bytes()).hexdigest() or margin['vram_free_mib']<1536:raise RuntimeError('Hybrid identity or margin differs')
        for index,row in enumerate(report['rows']):
            if row['warmup']!=(index<5) or row['output_tokens']!=256 or row['reused']!=0 or not all(isinstance(row[k],(int,float)) and math.isfinite(row[k]) and row[k]>0 for k in ('decode_tok_s','prefill_tok_s','wall_s')):raise RuntimeError('Invalid Hybrid samples')
        qualities=sorted((ROOT/'output/verification').glob('*-iq3-memory-quality-hybrid-tasks.json'));quality=None
        if qualities:
            from verify_iq3_tasks import CASES,evaluate
            q=json.loads(qualities[-1].read_text())
            if q['status']!='complete' or q['model']!=report['engine']['model'] or len(q['cases'])!=12:raise RuntimeError('Incomplete Hybrid quality')
            for row,(name,prompt,expected) in zip(q['cases'],CASES):
                if row['case']!=name or row['passed'] is not evaluate(row['answer'],expected):raise RuntimeError('Hybrid task result differs')
            if q['correct']!=sum(row['passed'] for row in q['cases']):raise RuntimeError('Hybrid task count differs')
            quality=dict(correct=q['correct'],total=12,source=qualities[-1].relative_to(ROOT).as_posix())
        payload['alternative_trials'].append(dict(title='Qwen3.8 Flash Next Hybrid',model=report['engine']['model'],quant='IQ3/Q2',core_parameters=125743653760,summary=report['summary'],protocol=report['protocol'],quality=quality,source=report_path.relative_to(ROOT).as_posix(),status='Modello alternativo · non adottato come riferimento',limitations='Single measured series; not a paired speedup against IQ3_XXS. No broad quality or endurance claim.'))
    payload['alternative_comparisons']=[]
    for feature,title in (('hybrid-it','Draft italiano su Hybrid'),('hybrid-minp03','Soglia draft 0,3 su Hybrid'),('hybrid-spec3','Finestra draft 3 su Hybrid')):
        files=summary_files(ROOT/'output/verification',feature,'abba')
        if not files:continue
        from summarize_feature import summarize_abba,summarize_quality
        result=summarize_abba(files[-1].name.removesuffix(f'-{feature}-abba-summary.json'),feature)
        quality_files=summary_files(ROOT/'output/verification',feature,'quality');quality=summarize_quality(quality_files[-1].name.removesuffix(f'-{feature}-quality-summary.json'),feature) if quality_files else None
        payload['alternative_comparisons'].append(dict(title=title,comparison=result,quality=quality,status=('Confronto instabile: da ripetere' if result.get('confounded') else 'Scartato: nessun vantaggio misurato' if result['pooled']['decode_tok_s']['change_percent'] <= 0 else 'Da confermare; configurazione del modello invariata')))
    target = ROOT / 'serve/web/performance-evidence.json'
    from serve.configuration import atomic_json
    atomic_json(target,payload)
    print(f'Published {target.relative_to(ROOT)}')

if __name__ == '__main__':
    main()

from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
p=ROOT/'tools/publish_performance_evidence.py';s=p.read_text();a=s.index('    pcie_paths =');b=s.index('    campaigns =',a)
s=s[:a]+'''    for percent in (55,20):
        kind=f'pcie{percent}'
        paths=sorted((ROOT/'output/verification').glob(f'*-{kind}-abba-summary.json'))
        if not paths:continue
        from summarize_pcie_abba import summarize as summarize_pcie
        item=json.loads(paths[-1].read_text());comparison=summarize_pcie(item['stamp'],percent)
        if comparison['model']!=payload['model']:continue
        payload[kind+'_comparison']=comparison
        quality=None
        qualities=sorted((ROOT/'output/verification').glob(f'*-{kind}-quality-summary.json'))
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
''' +s[b:]
s=s.replace("('pcie_comparison','Quota PCIe 55%','pcie_quality','Da confermare' if payload.get('latest_decision')=='candidate' else 'Non adottata')", "('pcie55_comparison','Quota PCIe 55%','pcie55_quality','Non adottata'),\n        ('pcie20_comparison','Quota PCIe 20%','pcie20_quality','Da confermare')")
p.write_text(s)
p=ROOT/'serve/web/app.js';s=p.read_text(encoding='utf-8');s=s.replace("    const title = isPcie ? 'Quota PCIe automatica → 55%'", "    const pciePercent=comparison.candidate_percent||Number(evidence.latest_kind?.replace('pcie',''))||55;\n    const title = isPcie ? `Quota PCIe automatica → ${pciePercent}%`")
s=s.replace("isPcie ? 'quota 55%'", "isPcie ? `quota ${pciePercent}%`");p.write_text(s,encoding='utf-8')

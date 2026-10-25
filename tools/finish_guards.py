from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
p=ROOT/'serve/benchmark_lab.py';s=p.read_text();s=s.replace('from serve.benchmark_monitor import snapshot','from serve.benchmark_monitor import snapshot\nfrom serve.gpu_lease import GpuLease,reserved')
s=s.replace("external=bool(feed and feed['active'] and state['status'] not in ACTIVE)","external=bool(((feed and feed['active']) or reserved(self.root)) and state['status'] not in ACTIVE)")
s=s.replace("            self.directory=self.root/'data/benchmark-lab'/identity;self.directory.mkdir(parents=True)","            self.lease=GpuLease(self.root,'lab-'+identity).acquire()\n            self.directory=self.root/'data/benchmark-lab'/identity\n            try:self.directory.mkdir(parents=True)\n            except BaseException:\n                self.lease.release();raise")
s=s.replace("            if own_lock:(self.root/'data/benchmarks/.benchmark.lock').unlink(missing_ok=True)","            if own_lock:\n                path=self.root/'data/benchmarks/.benchmark.lock'\n                try:\n                    if path.read_text().strip()==str(getattr(self.child,'pid',None)):path.unlink()\n                except OSError:pass\n            self.lease.release()")
p.write_text(s)
p=ROOT/'tools/iq3_memory_ab.py';s=p.read_text();s=s.replace("if __name__ == '__main__':\n    main()", "if __name__ == '__main__':\n    from serve.gpu_lease import GpuLease\n    with GpuLease(ROOT,'iq3-memory-cli'):main()")
p.write_text(s)
p=ROOT/'serve/server.py';s=p.read_text(encoding='utf-8');anchor="        if getattr(self,'switch_in_progress',False):raise GpuBusy('Cambio modello in corso')";s=s.replace(anchor,anchor+"\n        from serve.gpu_lease import reserved\n        if getattr(self,'port',None)==8088 and reserved(ROOT):raise GpuBusy('GPU riservata al benchmark')")
s=s.replace("if self.benchmark_lab.active():raise ValueError('Attendi la fine della campagna Benchmark')", "from serve.gpu_lease import reserved\n        if self.benchmark_lab.active() or reserved(ROOT):raise ValueError('Attendi la fine della campagna Benchmark')")
s=s.replace("                            payload=json.loads(self._read_body() or b'{}')\n                            result=svc.benchmark_lab.start", "                            if getattr(svc,'cat_job',{}).get('state') in ('starting','downloading','packing','registering'):raise RuntimeError('Attendi la preparazione del catalogo')\n                            payload=json.loads(self._read_body() or b'{}')\n                            result=svc.benchmark_lab.start")
p.write_text(s,encoding='utf-8')
p=ROOT/'serve/catalogue_verified.py';s=p.read_text();s=s.replace("    result=dict(at=time.time(),revision=revision,groups=grouped", "    grouped={quant:items for quant,items in grouped.items() if complete_group(items)}\n    result=dict(at=time.time(),revision=revision,groups=grouped")
anchor='def repo_info(repo):'
s=s.replace(anchor,"""def complete_group(items):
    shards=[re.search(r'-(\\d{5})-of-(\\d{5})\\.gguf$',i['path'],re.IGNORECASE) for i in items]
    if not any(shards):return len(items)==1
    if not all(shards):return False
    totals={int(m.group(2)) for m in shards}
    return len(totals)==1 and len(items)==next(iter(totals)) and {int(m.group(1)) for m in shards}==set(range(1,len(items)+1))

"""+anchor);p.write_text(s)

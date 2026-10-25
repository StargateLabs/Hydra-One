from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
p=ROOT/'serve/web/app.js';s=p.read_text(encoding='utf-8')
s=s.replace('toLocaleString(undefined,','toLocaleString(uiLocale(),').replace('toLocaleString([],','toLocaleString(uiLocale(),').replace('toLocaleTimeString([],','toLocaleTimeString(uiLocale(),')
s=s.replace("'it-IT'",'uiLocale()').replace('"it-IT"','uiLocale()')
s=s.replace('toLocaleString()','toLocaleString(uiLocale())')
s=s.replace("button.dataset.chatStarter.replace(/\\\\n/g,'\\n')",'StrataI18n.prompt(button.dataset.chatStarter)')
s+='''
// Refresh displayed measurements, never reset forms or conversation content.
window.addEventListener('strata:languagechange',()=>{
 if(lastMetrics)render(lastMetrics);
 updateChatWorkspace();
 if(tab==='tuning'){renderPerformanceReports();renderPerformanceRecord();}
 if(tab==='benchmark')loadBenchmarkLab();
 if(tab==='about')loadAboutBenchmarks();
});
'''
p.write_text(s,encoding='utf-8')
p=ROOT/'serve/web/index.html';s=p.read_text(encoding='utf-8').replace('refinements.css?v=20261009-monitor-header-1','refinements.css?v=20261009-languages-1');p.write_text(s,encoding='utf-8')

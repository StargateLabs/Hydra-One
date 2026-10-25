# Strata MOD — recupero HYDRA completato

Progetto: `C:\Users\Stargate\Desktop\Strata-main`. Dashboard: [Apri Strata](http://127.0.0.1:8090/).

## Cinque file ripristinati

- `feature-matrix.json`: recuperate dal database originale tutte le 56 definizioni, con identità, nomi e prove storiche conservate.
- `protocol-v15.1.json`: ricostruito un protocollo CPU limitato e identificato con un nuovo SHA-256. Le vecchie certificazioni di prestazione non autorizzano questa nuova identità.
- `protocol.json` storico: recuperati sei benchmark autentici, inclusi campioni, identificativi e date. Nessun risultato inventato.
- `graph_hybrid.py`: ricostruita ricerca locale con embedding multilingue già presenti; ripristinato anche `graph_hybrid_v2.py`.
- `prism-loader-manifest.json`: generato dai binari CPU realmente compilati dal commit ufficiale Prism `e3de715222b2667c54a267441159a5729f11155e`, collegati al lettore IOCP della MOD. Ripristinato anche il manifest Qwen.

Ricostruiti inoltre il helper nativo di scoring CPU, `decision_scoring.py` e il contratto locale delle domande a scelta. Corretto il rifiuto dei provider chiusi prima dell'avvio.

## Verifiche completate

- Suite HYDRA: **443 test, nessun errore o fallimento, una esclusione**.
- Centro aggiornamenti, ammissione e integrazione: **82 test superati**; recupero, integrità e backup: **21 test superati**. Alcuni test si sovrappongono alla suite HYDRA.
- Generazione reale con letture standard e IOCP: stessa risposta «Hello!», 269.100.288 byte di tensori verificati e 416 completamenti IOCP, sullo SmolLM2 recuperato.
- Ricerca H1/H1v2 reale: vettori da 384 dimensioni, risultati da fonti autorizzate, rifiuto delle fonti modificate e arresto del processo.
- Scoring CPU reale: log-probabilità ripetibili e rifiuto dei prefissi con confini di token incompatibili.
- HYDRA ONE dalla dashboard: risposta completa «Hello!» usando SmolLM2 recuperato, poi runtime liberato.
- Controllo integrato: **19 controlli pronti, nessun mancante** nel perimetro controllato; 36 file HYDRA verificati tramite manifest e hash.

## Recupero automatico e conservazione MOD

Il Centro aggiornamenti può ripristinare i file HYDRA mancanti dal pacchetto locale `HYDRA/recovery/assets.zip`, verificando l'intero archivio prima della scrittura. Scrittura atomica dei nuovi file; i file esistenti modificati vengono conservati e segnalati. Nessun download automatico di pesi.

Il pacchetto HYDRA è incluso nei backup verificati della MOD. Sorgenti precedenti conservati in `ripristino-originali/prima-ricostruzione-hydra`. Il backup originale su D: non è stato modificato durante questo lavoro.

## Perimetro delle prove

Queste prove riguardano i componenti ricostruiti e i modelli locali indicati. Non certificano parità con ogni esperimento storico, né prestazioni su qualsiasi modello. I controlli sperimentali GPU HYDRA, checkpoint/tiering avanzato, MoE e nodi remoti conservano i propri prerequisiti e blocchi; i test software non li promuovono.

LFM2.5 e gli altri nuovi pesi restano da aggiungere a tua scelta. Non sono stati scaricati. Il loader ricostruito è provato su SmolLM2: non è una nuova validazione dei modelli canonici Qwen 0.6B o Bonsai 27B assenti in questa installazione.

Le precedenti prove sul modello Qwen principale, GPU, SOUP, QLoRA e TRL restano nei rispettivi rapporti; non sono state rieseguite integralmente in questo passaggio. La vecchia suite generale da 1.452 test non descrive lo stato corrente della sottosuite HYDRA appena verificata.

# Prestazioni e Benchmark — il banco di lavoro della mod

## Dalla modifica alla prova ripetibile

Prestazioni e Benchmark sono il banco di lavoro con cui osserviamo i modelli e valutiamo i potenziamenti della mod. La prima sezione raccoglie e rende leggibili le misure; la seconda prepara ed esegue le prove sul motore selezionato. Il legame tra le due non è una classifica promozionale: serve a ricondurre un risultato al modello, al runtime, al protocollo e alla configurazione che lo hanno prodotto. Un cambiamento di cache, contesto, thread o backend deve essere confrontato con una prova coerente, non con un numero appartenente a un modello diverso.

## Prestazioni: leggere il comportamento del sistema

Il workspace Prestazioni comprende archivio delle misure, selezione del modello e della sessione, ricerca per nome o runtime, filtro HYDRA One, paginazione ed esportazione CSV dei risultati filtrati. La fascia delle versioni mostra i componenti rilevati; i contatori separano rapporti caricati, completati e altri esiti. Anche gli esiti non riusciti restano leggibili: eliminarli trasformerebbe lo storico in una selezione dei soli successi. La telemetria del PC e le metriche della richiesta hanno significati diversi e non devono essere confuse.

## Benchmark: eseguire un protocollo esplicito

Il benchmark del backend connesso richiede un motore pronto e acquisisce la prenotazione della conversazione. Il codice accetta 3–10, 20 o 30 misure, precedute da un riscaldamento, e un budget di uscita da 32 a 1.024 token. Registra prompt hash, parametri di generazione, streaming, contesto e metadati del runtime. Ogni campione mantiene il numero di token realmente restituiti e segnala se ha raggiunto il budget. L’annullamento interrompe il lavoro; la presenza di risultati parziali non equivale al completamento del protocollo.

## Ogni metrica conserva il proprio perimetro

Il tempo HTTP comprende l’intera richiesta fino alla risposta completa; il throughput complessivo divide i token per quel tempo. Il TTFT viene misurato fino al primo contenuto non vuoto quando si usa lo streaming. Decode e prefill vengono mostrati soltanto quando il backend li espone: non vengono ricavati arbitrariamente dalla latenza totale. Il confronto tra 2 e 8 rapporti verifica campioni, warmup e protocollo; l’identità del checkpoint può essere calcolata sui contenuti locali, non dedotta dal solo alias del modello.

## Qualità e velocità sono verifiche separate

Il controllo opzionale delle risposte usa 12 compiti a riferimento chiuso con identità del dataset. È un controllo circoscritto: non misura l’intelligenza generale del modello e non sostituisce valutazioni di dominio. Un throughput alto senza risposta utilizzabile non costituisce una prova riuscita. Nel registro dei record, risultati incompleti e campioni fuori contratto non devono diventare nuovi primati.

## Il laboratorio HYDRA e i potenziamenti

Il laboratorio persistente conserva prove importate e nuove esecuzioni come origini distinte. Collega identità di modello e runtime, profilo, campioni, eventi, artefatti e pulizia del processo. Il centro delle funzioni permette di ispezionare dipendenze e vincoli prima dell’esecuzione. Cache, checkpoint, retrieval, scoring, scheduling e I/O appartengono a percorsi specifici: un contratto software o una prova storica non certificano automaticamente il percorso GPU, un nuovo modello o un miglioramento prestazionale.

## Come valutiamo una modifica

Si sceglie il modello e se ne verifica l’identità; si fissa il protocollo; si registra una baseline; si cambia un parametro o un percorso identificabile; si ripete la prova e si confrontano metriche dello stesso tipo. Si controllano output, errori, memoria e chiusura dei processi, poi si conserva il rapporto. Questa documentazione descrive gli strumenti implementati: non dichiara che tutti i potenziamenti abbiano già superato una campagna end-to-end.

## Implementation / Implementazione

- [serve/optional_benchmark.py](../serve/optional_benchmark.py)
- [serve/optional_reports.py](../serve/optional_reports.py)
- [serve/benchmark_comparison.py](../serve/benchmark_comparison.py)
- [serve/lab_metrics.py](../serve/lab_metrics.py)
- [serve/quality_suite.py](../serve/quality_suite.py)
- [serve/hydra_lab_benchmarks.py](../serve/hydra_lab_benchmarks.py)
- [serve/hydra_feature_control.py](../serve/hydra_feature_control.py)
- [serve/web/performance-workspace.js](../serve/web/performance-workspace.js)

[Platform / Piattaforma](PLATFORM.it.md) · [Source inventory / Inventario](MODULES.md)

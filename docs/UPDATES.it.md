# Aggiornamenti, conservazione della mod e recupero

## Un sistema per integrare senza perdere le personalizzazioni

Il Centro aggiornamenti non è soltanto un elenco di versioni: collega inventario degli ambienti, fonti ufficiali, download verificati, candidati isolati, validazione e selezione dei componenti. L’obiettivo del nostro adattatore è preservare configurazioni, sorgenti modificati e dati mentre evolve la base dei motori e delle app. Versione disponibile, pacchetto scaricato, candidato validato e runtime attivo sono stati diversi e devono rimanere distinguibili.

## Inventario e provenienza

Le mappe dei componenti associano runtime e harness ai rispettivi repository o canali di distribuzione. L’inventario Python legge i metadati delle librerie senza importare automaticamente framework GPU. Mostra versioni installate, ambienti selezionati e dipendenze; il controllo delle release è limitato e usa cache. Consultare il Centro non deve equivalere a scaricare pesi LLM.

## Prima di cambiare qualcosa

Il percorso controlla che motore, agenti e generatori siano inattivi, recupera risorse dai servizi inattivi quando previsto e verifica il margine di memoria. Il backup della mod raccoglie sorgenti editabili e configurazioni, produce un archivio recuperabile e verifica gli hash dopo la scrittura. Gli ambienti generati, i pesi e le cache non vengono confusi con i file sorgente da preservare.

## Candidati separati, verifiche specifiche

I download hanno limiti di dimensione, spazio libero e integrità; l’estrazione resta in directory candidate e rifiuta percorsi pericolosi. Integrità dell’archivio non significa compatibilità del runtime. Perciò preparazione, controllo delle dipendenze e verifica funzionale sono fasi diverse. I canali Python per inferenza, audio, documenti e visuale hanno contratti propri; la selezione di uno non deve sostituire implicitamente l’ambiente di training.

## Selezione, rollback e coda automatica

Il codice mantiene registri di selezione e candidati precedenti per i percorsi implementati, con controlli di hash al momento dell’uso. La coda automatica è persistente e serializzata: può procedere soltanto sui componenti autorizzati dalla politica esistente, mentre gli altri restano protetti. Non tutti i componenti hanno lo stesso grado di validazione. Il semplice rilevamento di una release non costituisce attivazione né garanzia di successo.

## Recupero HYDRA

Il recupero verifica manifest, inventario e hash dell’intera capsula prima della scrittura. Ripristina file mancanti senza sovrascrivere quelli esistenti modificati. La pubblicazione GitHub contiene una capsula di soli sorgenti: non include né rigenera magicamente i binari personali della workstation. I loader nativi ricompilati richiedono una nuova ammissione con identità verificata.

## Implementation / Implementazione

- [serve/update_center.py](../serve/update_center.py)
- [serve/automatic_updates.py](../serve/automatic_updates.py)
- [serve/safe_update.py](../serve/safe_update.py)
- [serve/dependency_supervisor.py](../serve/dependency_supervisor.py)
- [serve/customization_backup.py](../serve/customization_backup.py)
- [serve/hydra_recovery.py](../serve/hydra_recovery.py)
- [serve/harness_updates.py](../serve/harness_updates.py)
- [serve/python_inference_update.py](../serve/python_inference_update.py)
- [serve/audio_python_update.py](../serve/audio_python_update.py)
- [serve/open_webui_python_update.py](../serve/open_webui_python_update.py)
- [serve/visual_python_update.py](../serve/visual_python_update.py)

[Platform / Piattaforma](PLATFORM.it.md) · [Source inventory / Inventario](MODULES.md)

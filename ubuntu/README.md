# Hydra One per Ubuntu · sorgenti sperimentali

Questa cartella conserva uno snapshot separato della variante Ubuntu, senza sostituire la versione Windows alla radice. Comprende la dashboard e l'integrazione HYDRA (`app/`), il codice Python dell'archivio HYDRA (`hydra-bundle-source/`), lo snapshot del motore nativo sperimentale (`native-engine/`) e i file locali della variante llama.cpp (`llama-cpp-b10438/`). Il runtime `hydra_one_bundle_v3.pyz` è incluso perché l'app ne verifica l'identità; i suoi sorgenti leggibili sono conservati separatamente.

Non sono inclusi modelli, ambienti Python, configurazioni personali, log, compilazioni locali o istruzioni specifiche della macchina originale. I componenti di terze parti mantengono le rispettive licenze nella repository e nelle sottocartelle. Gli indirizzi di esempio nei test e un commento sono stati anonimizzati; i percorsi personali nel catalogo sperimentale sono stati rimossi e richiedono una nuova configurazione.

## Preparare la copia dell'app

Alcune parti del catalogo web sono identiche ai file già presenti nella repository principale. Per evitare duplicazioni, questo comando verifica i loro checksum e assembla una copia dell'app in una **nuova** directory:

```sh
python3 ubuntu/prepare-app.py /percorso/nuovo/hydra-ubuntu-app
```

Il comando copia soltanto file: non installa dipendenze, non avvia servizi e non scarica modelli. La copia richiede ancora un ambiente Python compatibile, i pacchetti indicati in `requirements.txt`, un runtime e i modelli necessari. Le configurazioni, il binding di rete e i permessi devono essere scelti dall'installatore per il proprio ambiente. Non esporre servizi senza autenticazione alla rete.

## Stato e limiti

Lo snapshot deriva da un porting Ubuntu sperimentale: il percorso HYDRA con llama.cpp e il motore nativo sono componenti distinti. La presenza dei sorgenti non garantisce che ogni backend, GPU, modello o funzione sia disponibile o funzionante su un altro PC. Sono stati superati 36 controlli isolati del porting Ubuntu e dei percorsi HTTP di sicurezza, oltre al controllo sintattico dei file Python. Un test è stato aggiornato per riconoscere il rifiuto intenzionale del caricamento nativo dal motore simulato; non sono stati avviati modelli, dispositivi o servizi durante la preparazione. La compilazione del motore nativo e una nuova installazione end-to-end restano da verificare.

Origini e attribuzioni: [crediti della repository](../ACKNOWLEDGEMENTS.md) e [licenze](../licenses/).

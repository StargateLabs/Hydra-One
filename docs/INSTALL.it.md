# Installazione — Hydra One beta

Questa è una distribuzione di sorgenti. Usa una cartella dedicata e conserva separatamente modelli, configurazioni e installazioni già funzionanti.

## Requisiti

Python 3.10 o successivo. Per compilare il motore nativo: CMake 3.24+, compilatore C++ e il toolchain GPU appropriato al backend scelto. Su Windows usa un Developer Command Prompt di Visual Studio per i helper C++. Pesi e runtime opzionali si installano separatamente.

## Ambiente Python

```powershell
git clone https://github.com/StargateLabs/Hydra-One.git
cd Hydra-One
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m serve.server --help
```

Su Linux/macOS il percorso dell’interprete è `.venv/bin/python`. Il backend nativo documentato dalla base richiede Windows/Linux e hardware supportato: il solo ambiente Python non installa i driver GPU.

## Configurazione e avvio reali

Il percorso operativo usa il server in `serve/server.py`. Per configurare il motore nativo consulta `python setup.py --help` e la [guida tecnica della base](reference/AI_SETUP.md): setup può scaricare modelli e pacchetti voluminosi, quindi scegli modello e backend prima di eseguirlo. Le istruzioni upstream sono documentazione di riferimento, non una verifica di questa beta.

Una configurazione valida del motore contiene `exe`, `args`, `cwd`, `tokenizer` e `model_name`; usa i percorsi della tua macchina. Poi avvia:

```powershell
.venv\Scripts\python.exe -m serve.server --engine strata --config percorso\configurazione.json --host 127.0.0.1 --port 8090 --lazy
```

Apri `http://127.0.0.1:8090`. `--lazy` avvia il server senza caricare subito il modello. `strata` è il nome tecnico del driver ereditato: l’identità visibile della nostra applicazione è Hydra One. Se scegli un altro backend, installane le dipendenze attraverso i controlli dell’interfaccia e verifica il relativo stato prima di generare.

## Laboratorio HYDRA

Il laboratorio separato si avvia tramite `python -m serve.hydra_lab_app --help`. Richiede attivazione esplicita `HYDRA_LAB_MODE=1`, profilo e asset compatibili; i controlli bloccati restano tali fino al completamento delle dipendenze. Non riutilizzare manifest storici come attestazioni di un nuovo eseguibile. Le sorgenti native specifiche sono in `hydra-engine/native-overlays`; [istruzioni native](NATIVE-BUILD.md).

## Test e aggiornamenti

I test offline di esempio si eseguono con `python -m unittest serve.test_hydra_one serve.test_hydra_budget serve.test_hydra_request_guard`. Il [record di verifica](VALIDATION.json) indica il perimetro eseguito. Aggiorna questa repository con Git; non sovrascrivere Hydra One con un archivio dell’upstream Strata.

## Compatibilità dei nomi

Le intestazioni pubbliche sono in `include/hydra/`. Namespace C++, flag CMake, variabili `STRATA_*`, formato dei pack, nomi del driver e chiavi di integrazione sono conservati quando fanno parte del contratto tecnico. Rinominare ciecamente questi identificatori romperebbe configurazioni e runtime. Provenienza e licenze upstream restano nei crediti.

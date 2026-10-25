# AirLLM locale

AirLLM 4.0.0 è installato in un ambiente CPU separato, con PyTorch CPU e Transformers 5.19.0. Il Python Unsloth esistente non è stato modificato.

In **Control → Motori e modelli**, selezionare Safetensors e **AirLLM · streaming dei livelli · CPU**. È possibile usare una cartella locale con `config.json`, tokenizer e checkpoint Safetensors completo. La preparazione o l’aggiornamento dell’ambiente è disponibile nelle impostazioni del loader e nel Centro aggiornamenti.

I livelli vengono salvati separatamente in `data/airllm-layer-cache`. Gli originali sono conservati. La prima conversione richiede spazio per una copia dei pesi. Il controllo RAM tiene conto dei frammenti caricati durante la conversione, dei livelli e della cache del contesto.

Il supporto attuale riguarda modelli testuali causali con struttura Transformers standard. Codice remoto, checkpoint pickle, compressione, adapter, draft e GPU non sono abilitati in questo percorso. Le architetture speciali o multimodali che richiedono implementazioni dedicate upstream non vengono dichiarate compatibili.

Verificato: conversione reale, quattro token generati su fixture Qwen2 CPU non addestrata, integrità dei pesi originali e risposta attraverso l’alias `strata` nella dashboard 8090. Prova: `output/verification/airllm-real-runtime.json`; verifica completa del collegamento: `output/playwright/verify-local-integrations.cjs`.

Questa prova verifica il funzionamento, non la qualità del modello o le prestazioni di un 70B. Il risparmio di memoria dei pesi non equivale a maggiore velocità: lo streaming dipende anche dal disco.

Fonti: [AirLLM ufficiale](https://github.com/lyogavin/airllm), [pacchetto ufficiale](https://pypi.org/project/airllm/).

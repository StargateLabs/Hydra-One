# Cataloghi LLM, identità dei modelli e selezione del motore

## Una libreria orientata alla compatibilità

La mod non tratta ogni risultato di ricerca come un modello eseguibile. I cataloghi collegano ricerca Hugging Face, metadati delle pubblicazioni, varianti, file, modelli locali e compatibilità dei runtime. Il percorso nativo e il catalogo opzionale hanno criteri diversi: un pack esperti del motore nativo non deve essere avviato come GGUF generico, e un formato Prism non deve essere inoltrato silenziosamente a un runtime incompatibile.

## Ricerca e dettaglio della pubblicazione

Il catalogo opzionale distingue categorie chat, codice, ragionamento e modelli compatti. Il dettaglio riunisce panoramica, versioni/file e autore/modifiche. La model card conserva provenienza, base model, licenza e informazioni dell’editore; le sezioni vengono recuperate e limitate senza dedurre capacità da testi promozionali. Le varianti della stessa pubblicazione possono essere selezionate senza trattarle come una nuova ricerca indipendente.

## Formati, parti e memoria

Il codice legge gli header GGUF, identifica architetture e ruoli dei file, distingue pesi da projector e draft, riconosce gli shard e verifica i gruppi completi. La valutazione dell’host considera dimensioni e risorse; valori mancanti non diventano memoria zero. Safetensors e LoRA passano attraverso adapter Python specifici. Il fatto che un nome compaia nel catalogo non dimostra che il modello possa entrare nella RAM/VRAM disponibile.

## Inventario locale e download

L’inventario cerca modelli nelle radici configurate e nelle cache note, deduplica i percorsi e associa i metadati al modello reale. Download e import hanno percorsi dedicati: progressi in byte, gestione delle parti e collegamento dell’identità della pubblicazione ai file. Le model card e i pesi mantengono le proprie licenze e condizioni di accesso. Consultare autore e varianti non autorizza implicitamente ogni download.

## Logo, autore e modello non sono la stessa cosa

L’avatar originale dell’editore identifica il publisher; non certifica che tutte le varianti appartengano alla stessa architettura o abbiano le stesse capacità. Il renderer dei marchi mantiene i loghi verificati della mod. Quando manca una risorsa ufficiale adatta, un’etichetta testuale è preferibile a un simbolo inventato. L’identità della nostra piattaforma resta Hydra One.

## Il supporto viene dal percorso effettivo

Per ogni modello occorre verificare formato, architettura, quantizzazione, tokenizer/template, versione del motore, eventuale projector e risorse. Le capacità multimodali e gli strumenti sono dichiarati dal backend selezionato. La guida della piattaforma elenca architetture nominate dal codice e catalogo sperimentale; non trasforma quell’elenco in una promessa di supporto universale.

## Implementation / Implementazione

- [serve/catalogue.py](../serve/catalogue.py)
- [serve/catalogue_verified.py](../serve/catalogue_verified.py)
- [serve/optional_catalogue.py](../serve/optional_catalogue.py)
- [serve/local_model_discovery.py](../serve/local_model_discovery.py)
- [serve/model_inventory.py](../serve/model_inventory.py)
- [serve/model_engine_requirements.py](../serve/model_engine_requirements.py)
- [serve/gguf_parts.py](../serve/gguf_parts.py)
- [serve/gguf_runtime_compatibility.py](../serve/gguf_runtime_compatibility.py)
- [serve/studio_model_download.py](../serve/studio_model_download.py)
- [serve/studio_model_import.py](../serve/studio_model_import.py)
- [serve/web/model-brands.js](../serve/web/model-brands.js)

[Platform / Piattaforma](PLATFORM.it.md) · [Source inventory / Inventario](MODULES.md)

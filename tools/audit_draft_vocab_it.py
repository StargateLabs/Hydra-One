"""Read-only Italian coverage audit; does not generate or replace draft vocabularies."""
from array import array
from collections import Counter
import hashlib
import json
from pathlib import Path
from strata_tokenizer import Tokenizer

ROOT = Path(__file__).resolve().parents[1]
TEXTS = [
    'La configurazione utilizza una GPU AMD e ventiquattro gigabyte di memoria video.',
    'L’efficienza energetica dipende dalla potenza misurata e dalla velocità di generazione.',
    'Verifica l’affidabilità delle risposte, la correttezza dei risultati e la stabilità del sistema.',
    'Il monitor mostra temperatura, frequenza, utilizzo della memoria e trasferimenti PCIe.',
    'Riduci il tempo di attesa mantenendo qualità, precisione e possibilità di annullare la richiesta.',
    'Perché questa ottimizzazione può migliorare le prestazioni? Qual è il rischio di regressione?',
    'Confronta i risultati delle prove ripetute: mediana, minimo, massimo e durata complessiva.',
    'Un’applicazione locale conserva il controllo dei dati e permette di lavorare senza servizi esterni.',
    'Calcola il totale delle fatture, ordina gli elementi e restituisci un oggetto JSON valido.',
    'Scrivi una funzione Python che rimuova i duplicati conservando l’ordine originale.',
]

def main():
    cfg = json.loads((ROOT / 'strata-iq3_xxs.json').read_text())
    args = cfg['args']
    tokenizer = Tokenizer.from_gguf(args[args.index('--native') + 1])
    subset_path = Path(args[args.index('--mtp') + 1]) / 'draft_vocab.bin'
    raw = subset_path.read_bytes()
    subset = set(array('i', raw))
    if not subset or any(i < 0 or i >= len(tokenizer.tokens) for i in subset):
        raise ValueError('Invalid draft subset')
    ids = [i for text in TEXTS for i in tokenizer.encode(text)]
    missing = Counter(i for i in ids if i not in subset)
    result = {'kind': 'static vocabulary coverage, not generation or acceptance measurement',
              'model': cfg['model_name'], 'subset_sha256': hashlib.sha256(raw).hexdigest(),
              'subset_tokens': len(subset), 'sample_tokens': len(ids), 'covered_tokens': len(ids) - sum(missing.values()),
              'coverage_percent': 100 * (len(ids) - sum(missing.values())) / len(ids),
              'missing': [{'id': i, 'text': tokenizer.token_bytes(i).decode('utf-8', errors='replace'), 'count': count} for i, count in missing.most_common()],
              'limitations': 'Ten hand-written Italian samples; not representative of all outputs and not proof of a speed gain.'}
    (ROOT / 'output/verification/italian-draft-coverage.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()

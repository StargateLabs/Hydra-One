# Headroom

Headroom ufficiale 0.40.0 installato in `output/tools/headroom-runtime`, separato dai runtime dei modelli. Dipendenze verificate senza modificare PyTorch.

Attivo nella configurazione MCP condivisa `data/mcp-dashboard.json`: `headroom_compress`, `headroom_retrieve`, `headroom_stats`. Il dashboard ha confermato il server pronto senza errori. La disponibilità degli strumenti agli harness segue la sincronizzazione MCP già presente; gli harness già avviati possono richiedere una nuova sessione.

Compressione su richiesta degli agenti, non intercettazione automatica di tutte le richieste. Nessun provider globale modificato. Il proxy opzionale 8092 non rimane avviato: i tool locali funzionano, ma possono includere un avviso sul proxy non raggiungibile.

Prova reale su dati ripetitivi: 10.841 token iniziali, 4.437 finali, 6.404 risparmiati (59,1%). Errore critico preservato e recupero originale identico. Il risultato non garantisce la stessa percentuale sulle conversazioni reali. Prove in `output/verification/headroom-mcp-proof.json` e `headroom-dashboard-mcp.json`.

Fonte ufficiale: https://github.com/headroomlabs-ai/headroom

## Attivazione proxy

Proxy ufficiale attivo su `127.0.0.1:18198`, inoltro esclusivamente al gateway locale 8090. Verificati `/livez` e discovery `/v1/models` attraverso il proxy. I nuovi manager degli harness usano questo collegamento automaticamente; le sessioni già avviate conservano la propria configurazione fino al successivo avvio. La chat normale resta sul suo collegamento diretto e dispone dei tool MCP. Compressore ML disabilitato, compressione strutturale disponibile. Nessun nuovo test di generazione o misura dei risparmi sul traffico reale effettuato.

Attivazione persistente: `data/headroom/enabled.json`; rimuovere il file disabilita l instradamento per i nuovi manager. Nessuna configurazione globale modificata.

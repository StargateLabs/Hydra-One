# Porte di Strata su questo PC

Questo è l'elenco autorevole delle porte usate da Strata su questo computer.
Se una pagina o una guida indica una porta diversa, vale questo documento.

Stato dal vivo: `powershell -File tools\Stato-porte.ps1`

## Le porte di Strata

| Porta | Servizio | Come si avvia | Modello caricato |
| --- | --- | --- | --- |
| **8090** | **L'unica dashboard di questo PC.** Comprende MCP, i ponti per gli agenti e Headroom. | `Avvia-LocalAI.bat`, `Avvia-Strata.bat` o `Strata-Web.bat` | letto da `strata-hf_85a248b2_q2_0.json` oppure dall'ultimo modello usato |
| **18198** | Proxy Headroom verso la 8090. Comprime le richieste locali degli agenti; non è una dashboard. | si avvia con la dashboard quando è abilitato | inoltra a 8090 |

## Porte usate dai motori interni

Non sono dashboard e si avviano da sole quando servono:

| Porta | Servizio |
| --- | --- |
| 8093 | Whisper (trascrizione) |
| 8094 | Kokoro / PocketTTS (sintesi vocale) |
| 8091 | server interno Unsloth llama.cpp, quando un backend opzionale è collegato |
| porta effimera | separazione audio HTDemucs |

## Porte che non sono di Strata

Sullo stesso PC possono essere in ascolto altri programmi. Strata non li gestisce e non li arresta:

| Porta | Programma |
| --- | --- |
| 6379 | Redis |
| 9222 | Chromium con debugging remoto |
| 9867, 9888 | PinchTab |
| 8070 | HapticService |

## Perché la documentazione parlava di 8080

La porta predefinita di Strata è `8080`. Su questo PC la 8080 è **occupata da un altro
programma**, quindi la dashboard è stata spostata sulla **8090**. In passato giravano anche
una seconda dashboard sulla 8080 con un altro modello: è stata fermata, così una sola
dashboard resta attiva e nessuno può confondersi. Le guide originali descrivevano la 8080 e
sono state allineate a questo documento.

## Regole pratiche

- Apri **http://127.0.0.1:8090/** per l'unica dashboard.
- Se una porta non risponde, controlla con `tools\Stato-porte.ps1` prima di avviare un secondo
  servizio: due server sulla stessa porta non possono convivere.
- `tools\restart_idle_dashboard.ps1` riavvia la 8090 e rifiuta il riavvio se un motore,
  un agente o una generazione è attiva.
- Non esporre mai queste porte oltre `127.0.0.1` senza `--api-key`.

## Una sola dashboard, per Construction

I tre launcher avviano tutti la **8090**. Il primo server che parte acquisisce
`data/dashboard.lock` con la propria porta e il proprio PID; un secondo avvio su qualsiasi
altra porta viene **rifiutato** con un messaggio che indica l'indirizzo già attivo:

```
[strata] Una dashboard Strata è già in asecuzione sulla porta 8090:
apri http://127.0.0.1:8090/ invece di avviarne una seconda.
```

- Se un processo muore senza chiudersi, il lock rimane ma riferisce a un PID morto: viene
  ignorato e rimosso, quindi un riavvio normale non è bloccato.
- I sidecar interni (la verifica dei candidati del motore, che usa una porta di servizio
  mentre la dashboard resta attiva) portano `STRATA_VALIDATION_LEASE_TOKEN` e non sono
  bloccati.
- `toolsestart_idle_dashboard.ps1` ferma prima il processo in ascolto, quindi il lock è
  già libero quando riparte.

## Gli harness si fermano da soli

Un harness aperto consuma RAM finché qualcuno non lo chiude. Con
`STRATA_HARNESS_IDLE_STOP=<secondi>` (impostato a 900 dai launcher) un harness che nessuno
usa da quel tempo viene fermato. Le conversazioni stanno in `data/<tipo>-home` su disco,
quindi non si perde nessuna sessione: l'harness riparte dalla stessa home.

Un harness **non** viene mai fermato mentre ha una sessione aperta, mentre sta partendo, o
se la sua attività non è leggibile.

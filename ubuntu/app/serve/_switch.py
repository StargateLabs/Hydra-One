"""serve/_switch.py — cambia il modello in uso dalla dashboard.

Perche' serve un processo separato: la configurazione del motore (quale pack, quale modello) viene
letta all'AVVIO del server e tenuta in memoria. Cambiare modello significa quindi riavviare il server
con un'altra configurazione. Pero' il server attuale tiene occupata la porta: se il nuovo partisse
subito, troverebbe la porta occupata e morirebbe.

Quindi questo aiutante, lanciato dal server morente:
  1. aspetta che la porta si liberi (il server vecchio sta uscendo);
  2. aspetta qualche secondo perche' il motore rilasci la GPU;
  3. avvia il server con la NUOVA configurazione, sulla STESSA porta, staccato dal genitore.

Uso: python serve/_switch.py <config.json> <porta> <cartella-del-repo>
"""
import os
import pathlib
import socket
import subprocess
import sys
import time


def porta_libera(porta: int, tentativi: int = 90, attesa: float = 1.0) -> bool:
    """True quando nessuno risponde piu' su quella porta (il server precedente e' uscito)."""
    for _ in range(tentativi):
        with socket.socket() as s:
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", porta)) != 0:
                return True
        time.sleep(attesa)
    return False


def main() -> int:
    if len(sys.argv) < 4:
        print("uso: _switch.py <config.json> <porta> <cartella>", flush=True)
        return 2
    config = pathlib.Path(sys.argv[1])
    porta = int(sys.argv[2])
    root = pathlib.Path(sys.argv[3])
    if not config.exists():
        print(f"configurazione inesistente: {config}", flush=True)
        return 1

    print(f"[switch] attendo che la porta {porta} si liberi...", flush=True)
    if not porta_libera(porta):
        print("[switch] la porta non si e' liberata: il server precedente e' ancora vivo. Non faccio niente.", flush=True)
        return 1
    # il motore impiega un istante a rilasciare la VRAM dopo che il server muore
    time.sleep(4)

    log = root / f"strata-avvio-{config.stem}.log"
    cmd = [sys.executable, str(root / "serve" / "server.py"),
           "--engine", "strata", "--config", str(config), "--port", str(porta), "--lazy", "--api-monitor", "--idle-unload", "900"]
    # staccato dal genitore: deve sopravvivere alla morte del server che l'ha lanciato
    flag = 0
    for nome in ("CREATE_NEW_PROCESS_GROUP", "DETACHED_PROCESS"):
        flag |= getattr(subprocess, nome, 0)
    try:
        with open(log, "ab") as fh:
            fh.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} cambio modello -> {config.name}\n".encode())
            subprocess.Popen(cmd, cwd=str(root), stdout=fh, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, creationflags=flag, close_fds=True)
    except OSError as e:
        print(f"[switch] non riesco ad avviare il server: {e}", flush=True)
        return 1
    print(f"[switch] avviato: {' '.join(cmd)}  (log: {log})", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

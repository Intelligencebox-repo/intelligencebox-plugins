r"""
Esempio di MCP client (stdio) che avvia il server `checkcorporate_server`
come subprocess e invoca i tools `get-bilancio` e `get-piano-dei-conti`.

Prerequisiti:
- attiva il venv e installa le dipendenze (in `servers/mcp-checkcorporate-server`):
    python -m venv .venv
    .\.venv\Scripts\Activate.ps1
    pip install -r requirements.txt

Esecuzione:
    python test_client_mcp.py

Lo script mostra l'elenco tool e i risultati delle chiamate.
"""
import json
import sys
import os
import subprocess
import time
import threading


def send_line(proc, obj):
    line = json.dumps(obj, ensure_ascii=False)
    proc.stdin.write((line + "\n").encode("utf-8"))
    proc.stdin.flush()


def read_response(proc, timeout=5.0):
    start = time.time()
    while True:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                raise RuntimeError("Server process exited")
            if time.time() - start > timeout:
                raise TimeoutError("Timed out waiting for response")
            time.sleep(0.01)
            continue
        try:
            text = line.decode("utf-8").strip()
        except Exception:
            text = line.decode(errors="replace").strip()
        if not text:
            continue
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            print("[NON_JSON]", text, file=sys.stderr)
            continue


def main():
    # NOTE: questo script implementa un client semplice e sincrono che
    # comunica con il server tramite stdin/stdout (JSON-RPC su linee). Usiamo
    # un approccio sincrono (subprocess + readline) perché è molto
    # prevedibile su Windows e non dipende da anyio/asyncio internals.

    # Passo 1: calcola il percorso `src/` del server e aggiungilo a PYTHONPATH
    # quando eseguiamo il processo figlio, così il server può importare il
    # pacchetto `checkcorporate_server` senza dover installare il package.

    here = os.path.dirname(__file__)
    src_dir = os.path.join(here, "src")

    # Stampa l'endpoint API configurato per debug
    api_endpoint = os.environ.get("API_ENDPOINT_URL", "(non configurato)")
    print(f"API_ENDPOINT_URL: {api_endpoint}")
    ignore_ssl = os.environ.get("IGNORE_SSL_CERT", "0")
    print(f"IGNORE_SSL_CERT: {ignore_ssl}")

    env = os.environ.copy()
    # Prepend local src/ to PYTHONPATH for the child process so it can import
    # the package while we're developing locally (editable install alternative).
    env["PYTHONPATH"] = src_dir + (os.pathsep + env.get("PYTHONPATH", ""))

    # Avvia il server come processo figlio:
    # - sys.executable: assicura che usiamo la stessa versione di Python
    # - -u: modalità unbuffered (aiuta a ricevere le linee immediatamente)
    # - -m checkcorporate_server: esegue il package come modulo
    proc = subprocess.Popen(
        [sys.executable, "-u", "-m", "checkcorporate_server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )

    # Avviamo un thread che legge lo stderr del server e lo inoltra sullo
    # stderr del client: questo ci permette di vedere i log del server senza
    # inquinare stdout (che usiamo per il protocollo JSON-RPC).
    def stderr_reader(p):
        try:
            for line in iter(p.stderr.readline, b""):
                if not line:
                    break
                try:
                    text = line.decode("utf-8", errors="replace").rstrip()
                except Exception:
                    text = repr(line)
                print(f"[SERVER STDERR] {text}", file=sys.stderr)
        except Exception as e:
            print(f"[stderr_reader error] {e}", file=sys.stderr)

    t = threading.Thread(target=stderr_reader, args=(proc,), daemon=True)
    t.start()

    try:
        # --- Handshake: initialize
        # Invia una richiesta `initialize` al server e attende la risposta.
        # Il server risponderà con informazioni sul protocollo e le capability.
        print("Initializing client session...")
        time.sleep(0.05)  # piccolo ritardo per stabilizzare l'ordine delle stampe

        init_req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "0.1"},
            },
        }
        print("-> sending initialize")
        send_line(proc, init_req)

        # Legge la singola linea JSON di risposta dall'stdout del server
        resp = read_response(proc, timeout=10.0)
        print("Server initialize result:")
        print(json.dumps(resp, indent=2, ensure_ascii=False))

        # --- Notifica al server che il client è inizializzato
        # Alcuni server si aspettano questa notifica prima di rispondere a
        # richieste successive (come `tools/list`).
        init_notify = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
        print("-> sending notifications/initialized")
        send_line(proc, init_notify)

        # --- Richiesta lista tools
        print("-> sending tools/list")
        list_req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        send_line(proc, list_req)
        resp = read_response(proc, timeout=10.0)
        print("Tools available:")
        print(json.dumps(resp, indent=2, ensure_ascii=False))

        # --- Esecuzione del tool `get-bilancio`
        print("Calling get-bilancio...")
        call_req = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "get-bilancio",
                "arguments": {"societa": "*all", "esercizio": 2024, "tipo": "Economico", "codiceConto": "G1211300", "descrizioneConto": "G1211300-F.DO AMM. COSTI DI COSTITUZIONE SOCIETÀ"},
            },
        }
        send_line(proc, call_req)
        resp = read_response(proc, timeout=10.0)
        print("get-bilancio result:")
        print(json.dumps(resp, indent=2, ensure_ascii=False))

        # --- Esecuzione del tool `get-piano-dei-conti`
        print("Calling get-piano-dei-conti...")
        call_req2 = {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "get-piano-dei-conti", "arguments": {"societa": "*all", "ricerca": "dip"}},
        }
        send_line(proc, call_req2)
        resp = read_response(proc, timeout=10.0)
        print("get-piano-dei-conti result:")
        print(json.dumps(resp, indent=2, ensure_ascii=False))

        # --- Elenco report disponibili
        print("Calling get-report-disponibili...")
        call_req3 = {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "get-report-disponibili", "arguments": {"societa": "*all", "ricerca": ""}},
        }
        send_line(proc, call_req3)
        resp = read_response(proc, timeout=10.0)
        print("get-report-disponibili result:")
        print(json.dumps(resp, indent=2, ensure_ascii=False))

    finally:
        # Pulizia: termina il processo figlio se ancora in esecuzione
        try:
            proc.kill()
        except Exception:
            pass


if __name__ == "__main__":
    main()

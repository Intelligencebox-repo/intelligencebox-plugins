# CheckCorporate MCP server (local dev notes)

> Questa cartella contiene un MCP server di esempio (`checkcorporate_server`) che espone due tool mock:
>
> - `get-bilancio` — restituisce dati aggregati di bilancio (mock)
> - `get-piano-dei-conti` — restituisce il piano dei conti (mock)
>
> Le risposte sono simulate per default così da non richiedere un database reale durante lo sviluppo.

## Requisiti

- Python 3.11/3.12/3.13
- `pip` per installare le dipendenze
- (opzionale) Docker per eseguire il server in container

Le dipendenze Python sono elencate in `requirements.txt`.

## Setup rapido (locale)

1. Crea e attiva un virtualenv nella cartella del server:

```powershell
cd .\servers\mcp-checkcorporate-server
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. Installa le dipendenze:

```powershell
pip install -r requirements.txt
```

3. Fornisci le credenziali richieste (vedi sotto) e avvia il client di test:

```powershell
# Impostare le variabili d'ambiente richieste per l'esecuzione locale
$env:CLIENT_ID = "my-client-id-abc123"
$env:CLIENT_SECRET = "supersecret"
$env:API_ENDPOINT_URL = "https://api.example.com"
python .\test_client_mcp.py
```

Nota: il server ora richiede obbligatoriamente `CLIENT_ID`, `CLIENT_SECRET` e `API_ENDPOINT_URL` all'avvio; se non sono presenti il processo terminerà con errore. Questo riflette il comportamento atteso in produzione, dove i secret devono essere forniti dal launcher/orchestrator.

## Variabili di configurazione richieste (manifest)

Il `manifest.json` del servizio dichiara i seguenti campi nel `configSchema` (obbligatori per il deploy):

- `CLIENT_ID` (string)
- `CLIENT_SECRET` (string)

Questi valori devono essere forniti al container/launcher dall'ambiente di esecuzione (registry/launcher, Docker, Kubernetes, ecc.).

## Esecuzione in Docker

Esempio veloce (non sicuro per segreti sensibili):

```bash
docker run -e CLIENT_ID=xxx -e CLIENT_SECRET=yyy -e API_ENDPOINT_URL=https://api.example.com ghcr.io/intelligencebox-repo/mcp-checkcorporate-server:latest
```

Raccomandazione: usare Docker secrets o il secret manager della piattaforma (o Kubernetes Secrets) per evitare di mettere i secret direttamente nella riga di comando o nei file di configurazione non protetti.

Esempio Compose (usare `secrets:`): è incluso un file di esempio `docker-compose.yml` nella stessa cartella che mostra come montare i secret e esportarli nelle env var prima dell'avvio del processo.

## Come i tool usano le credenziali

- Al bootstrap il server legge `CLIENT_ID`/`CLIENT_SECRET` e li passa al layer `DbTools`.
- Le risposte simulate includono un campo `client_id_masked` (quando `CLIENT_ID` è presente) per mostrare che il tool ha accesso alla credenziale. Il `CLIENT_SECRET` non viene mai stampato né incluso nelle risposte.
- Questo comportamento è solo dimostrativo: nelle integrazioni reali le credenziali dovrebbero essere usate per autenticare chiamate esterne e mai esposte nei risultati.

## Note sulla sicurezza

- Fornire i secret tramite meccanismi sicuri: Docker secrets, Kubernetes Secrets, o servizi di secret-management.
- Non committare secret nel repository.
- Non loggare i secret; il server stampa solo messaggi diagnostici su `stderr`.

## Abilitare un DB reale (opzionale)

Di default `DbTools` restituisce risposte simulate. Se desideri usare un database SQLite reale dovresti modificare l'istanza di `DbTools` nel file `server.py` per passare `use_db=True` e, se necessario, un percorso `db_path`.

Esempio rapido (modifica minima in `server.py`):

```py
# prima: db = DbTools(client_id=client_id, client_secret=client_secret)
# dopo (abilita DB reale):
db = DbTools(use_db=True, db_path='/data/bilancio.db', client_id=client_id, client_secret=client_secret)
```

Poi fornisci una cartella persistente montata nel container per `/data` in modo che il file sqlite sia persistente.

## Comportamento del client di test

- `test_client_mcp.py` è un esempio sincrono che avvia il server come processo figlio, effettua il handshake JSON-RPC (`initialize` + `notifications/initialized`), poi invoca `tools/list` e i due tool di esempio.
- È utile per sviluppo locale; se preferisci un esempio basato sull'API `mcp` (anyio) chiedimi e posso aggiungerlo come file separato.


---
File rilevanti:
- `manifest.json` — dichiara i campi di configurazione (CLIENT_ID/CLIENT_SECRET)
- `src/checkcorporate_server/server.py` — bootstrap del server e lettura env
- `src/checkcorporate_server/db_tools.py` — layer che simula le query e usa le credenziali
- `test_client_mcp.py` — client di test funzionante per sviluppo locale

##Docker

Build:
-docker build -t local/mcp-checkcorporate-server:latest .
Run:
- docker run --rm --name checkcorp-locale -d -i -e CLIENT_ID="my-client-id-abc123" -e CLIENT_SECRET="supersecret" -e API_ENDPOINT_URL="https://api.example.com" local/mcp-checkcorporate-server:latest
aggiungere -it per non farlo cadere
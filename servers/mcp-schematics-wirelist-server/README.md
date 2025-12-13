# Schematics Wirelist MCP Server

Estrae liste fili e componenti da schemi elettrici (PDF/immagini) e genera un file Excel multi‑foglio simile agli esempi contenuti in `filenewmpc/` (LISTA FILI, DISTINTA, ecc). Usa un modello OpenAI per interpretare il contenuto e scrive un workbook pronto per la produzione.

## Requisiti

- Node 20+
- `poppler-utils` e `tesseract-ocr` installati (già inclusi nell'immagine Docker) per convertire i PDF in immagini quando non contengono testo.
- Variabili d'ambiente:
  - `OPENAI_API_KEY` (obbligatoria)
- `OPENAI_MODEL` opzionale, default `gpt-5.2`
  - `OPENAI_BASE_URL` opzionale per endpoint compatibili OpenAI
  - `DEFAULT_MAX_PAGES` opzionale, default 3
  - `PDF_RENDER_DPI` opzionale, default 300 (aumentare se i numeri rossi sono piccoli/difficili da leggere)
  - `PDF_RENDER_TILE_GRID` opzionale, default 2 (es. 1=disattiva tile, 2=2x2, 3=3x3; utile per leggere numeri rossi molto piccoli/barrati)

## Sviluppo rapido

```bash
cd servers/mcp-schematics-wirelist-server
npm install
npm run dev # avvia il server MCP via stdio
```

Build di produzione:

```bash
npm run build
npm start
```

## Tool esposto

### `extract_wirelist`

Input (tutti JSON-schema, validati con Zod):
- `file_path` (stringa, richiesto): percorso a un PDF/immagine con lo schema elettrico.
- `output_excel_path` (stringa, opzionale): dove salvare l'xlsx generato (default `./outputs/wirelist-<timestamp>.xlsx`).
- `project` / `note` (stringhe, opzionali): metadati copiati nel foglio INDICAZIONI.
- `start_page` / `end_page` (int, opzionali): limita l'estrazione a un intervallo di pagine (default da pagina 1, rispettando `max_pages`).
- `max_pages` (int, opzionale): numero di pagine PDF da convertire in immagini per l'OCR (default 3, fino a 1000).
- `use_vision` (boolean, opzionale, default true): se convertire il PDF in immagini quando il testo è scarso.
- `add_raw_text_sheet` (boolean, opzionale, default true): aggiunge un foglio con il testo grezzo estratto.
- `model` (stringa, opzionale): overrides del modello.

Output:
- Risultato JSON con conteggi fili/componenti, percorso dell'xlsx generato, warning e metadati del documento.
- L'xlsx include i fogli: `INDICAZIONI`, `LISTA FILI`, `DISTINTA`, `SIGLATURA`, `TAGLIO FILI` (aggregazioni) e opzionalmente `RAW_TEXT`.

## Note operative

- Le pagine PDF vengono convertite in immagini (fino a `max_pages`) e ogni pagina viene inviata al modello singolarmente (una chiamata per pagina), mantenendo l’ordine. Il testo estratto viene comunque passato come contesto per ciascuna pagina.
- In assenza di `OPENAI_API_KEY` viene comunque creato un Excel vuoto/precompilato con il testo grezzo, ma l'estrazione strutturata non può funzionare.
- Adattare i campi del workbook modificando `buildWorkbook` in `src/extraction.ts` per replicare ulteriormente gli schemi in `filenewmpc/`.
- È possibile limitare l'estrazione a un intervallo di pagine con `start_page`/`end_page` (utile per saltare pagine di esempio/legenda); l'intervallo rispetta comunque `max_pages`.
- Post-process: vengono scartati fili con ID che iniziano per `W`, ID solo di fase (L1/L2/L3/N/PE) o estremi che sono solo coordinate numeriche. La sezione viene mantenuta solo se esplicita (mm²/AWG/x...); valori ambigui come rimandi pagina vengono lasciati vuoti.

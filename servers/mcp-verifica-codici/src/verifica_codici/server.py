import asyncio
import os
import json
import sys
import re
import csv
import time
from typing import List
from concurrent.futures import ThreadPoolExecutor, as_completed

# Import necessari da Pydantic per definire i parametri
from pydantic import BaseModel, Field

# Import necessari dal framework MCP
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.shared.exceptions import McpError
from mcp.types import Tool, ErrorData, TextContent, INTERNAL_ERROR, INVALID_PARAMS

# Import delle nostre funzioni logiche dai moduli separati
from .script1 import estrai_elenco_documenti
from .script2 import recupera_percorso_file
from .script5 import verifica_codici

# Import per la validazione con cartelle
from .code_extractor_folders import FolderCodeExtractor
from .master_list_parser import MasterListParser
import pdfplumber
import fitz  # PyMuPDF


# --- Definizione dei Parametri di Input con Pydantic ---
class VerificaCodiciParams(BaseModel):
    index_pdf_path: str = Field(..., description="Il percorso del file PDF che contiene l'elenco dei documenti da verificare.")
    codice_commessa: str = Field(..., description="Il codice della commessa da utilizzare per filtrare i documenti nell'elenco.")
    collection_id: str = Field(..., description="Collection ID dove cercare i documenti da verificare tramite RAG.")

class ExtractTableParams(BaseModel):
    master_list_pdf: str = Field(..., description="Percorso al PDF dell'elenco documenti da cui estrarre le righe (codice + titolo).")
    output_csv: str | None = Field(default=None, description="Percorso opzionale per salvare il CSV con le entries estratte. Se non specificato, viene creato accanto al PDF con suffisso _entries.csv.")

class ValidateFoldersParams(BaseModel):
    documents_folder: str = Field(..., description="Percorso alla cartella contenente i PDF dei documenti da validare (es. '/dataai/collection_name').")
    master_list_pdf: str = Field(..., description="Percorso al file PDF contenente l'elenco master dei documenti attesi (es. '/dataai/collection_name/elenco-documenti.pdf').")
    mode: str | None = Field(default="text_search", description="Strategia di validazione: 'text_search' per estrarre la tabella dal PDF elenco e cercare codice/titolo nel testo dei PDF; 'vlm' per la logica precedente basata su OCR/VLM.")
    max_pages_to_scan: int | None = Field(default=3, description="Numero massimo di pagine da leggere per ogni PDF nella modalità text_search (None per tutte le pagine).")

class CheckDocumentsParams(BaseModel):
    documents_folder: str = Field(..., description="Cartella con i PDF da controllare.")
    entries: list[dict] | str = Field(..., description="Lista di oggetti {code,title,...} oppure stringa JSON con la stessa lista.")
    max_pages_to_scan: int | None = Field(default=3, description="Numero massimo di pagine da leggere per ogni PDF (None per tutte le pagine).")

class ContentScanParams(BaseModel):
    entries_csv: str = Field(..., description="Percorso al CSV con almeno la colonna 'code' (e opzionalmente 'title').")
    documents_folder: str = Field(..., description="Cartella (scansione ricorsiva) con i PDF da confrontare.")
    max_pages: int | None = Field(default=2, description="Pagine da leggere per ogni PDF (None per tutte).")
    log_every: int | None = Field(default=20, description="Frequenza di log di avanzamento (numero di PDF).")
    max_workers: int | None = Field(default=4, description="Numero di thread per la scansione PDF (CPU bound I/O).")

def normalize_title_for_search(text: str) -> str:
    """Normalizza una stringa descrittiva per il confronto case-insensitive."""
    lowered = (text or "").lower()
    cleaned = re.sub(r"[^a-z0-9]+", " ", lowered)
    return re.sub(r"\s+", " ", cleaned).strip()

def normalize_code_for_search(code: str) -> str:
    """Normalizza un codice rimuovendo tutto tranne A-Z0-9."""
    return re.sub(r"[^A-Z0-9]", "", (code or "").upper())


def load_entries(entries_param: list[dict] | str) -> list[dict]:
    """Normalizza l'input entries in lista di dict con almeno 'code'/'title'."""
    raw_entries = entries_param
    if isinstance(entries_param, str):
        try:
            raw_entries = json.loads(entries_param)
        except json.JSONDecodeError as exc:
            raise McpError(ErrorData(code=INVALID_PARAMS, message=f"entries non è un JSON valido: {exc}"))

    if not isinstance(raw_entries, list):
        raise McpError(ErrorData(code=INVALID_PARAMS, message="entries deve essere una lista di oggetti o una stringa JSON di tale lista."))

    cleaned = []
    for item in raw_entries:
        if not isinstance(item, dict):
            continue
        cleaned.append({
            "code": item.get("code", "") or "",
            "title": item.get("title", "") or "",
            "row": item.get("row", []),
            "page": item.get("page"),
        })
    return cleaned


def extract_text_from_pdf(pdf_path: str, max_pages: int | None = None) -> str:
    """Estrae il testo da un PDF (prime max_pages, se specificato)."""
    with pdfplumber.open(pdf_path) as pdf:
        pages = pdf.pages if max_pages is None else pdf.pages[:max_pages]
        texts: list[str] = []
        for page in pages:
            try:
                texts.append(page.extract_text() or "")
            except Exception as exc:
                print(f"[WARN] Impossibile estrarre testo da {pdf_path}: {exc}", file=sys.stderr, flush=True)
        return "\n".join(texts)


def scan_pdfs_for_text(folder_path: str, max_pages: int | None = None) -> tuple[list[dict], list[str]]:
    """Legge tutti i PDF in una cartella e prepara testi normalizzati per la ricerca."""
    if not os.path.exists(folder_path):
        raise FileNotFoundError(f"Cartella non trovata: {folder_path}")

    pdf_files = sorted([f for f in os.listdir(folder_path) if f.lower().endswith(".pdf")])
    scanned: list[dict] = []
    errors: list[str] = []

    for filename in pdf_files:
        pdf_path = os.path.join(folder_path, filename)
        if os.path.isdir(pdf_path):
            continue
        try:
            text = extract_text_from_pdf(pdf_path, max_pages=max_pages)
        except Exception as exc:
            errors.append(f"{filename}: {exc}")
            text = ""

        upper_text = (text or "").upper()
        compact_text = re.sub(r"[^A-Z0-9]", "", upper_text)
        lower_text = normalize_title_for_search(text)

        scanned.append({
            "filename": filename,
            "path": pdf_path,
            "text_upper": upper_text,
            "text_lower": lower_text,
            "text_compact": compact_text,
            "file_upper": filename.upper(),
            "file_lower": filename.lower(),
            "file_compact": re.sub(r"[^A-Z0-9]", "", filename.upper()),
        })

    return scanned, errors


def match_entry_to_pdfs(entry: dict, scanned_pdfs: list[dict]) -> dict | None:
    """Trova il PDF che contiene codice e/o titolo dell'entry."""
    code = entry.get("code", "")
    compact_code = re.sub(r"[^A-Z0-9]", "", code.upper())
    title_norm = normalize_title_for_search(entry.get("title", ""))

    best_match: dict | None = None
    for pdf in scanned_pdfs:
        code_found = False
        if code:
            code_found = (
                code in pdf["text_upper"]
                or (compact_code and compact_code in pdf["text_compact"])
                or code in pdf["file_upper"]
                or (compact_code and compact_code in pdf["file_compact"])
            )

        title_found = False
        if title_norm:
            title_found = (
                title_norm in pdf["text_lower"]
                or title_norm in pdf["file_lower"]
            )

        status = None
        if code_found and title_found:
            status = "matched"
        elif code_found:
            status = "code_found"
        elif title_found:
            status = "title_found"

        if status:
            best_match = {
                "code": code,
                "title": entry.get("title", ""),
                "matched_file": pdf["filename"],
                "code_found": code_found,
                "title_found": title_found,
                "status": status,
                "page_hint": entry.get("page"),
                "row": entry.get("row", []),
            }
            if status == "matched":
                break

    return best_match


async def run_text_check(entries: list[dict], documents_folder: str, max_pages: int | None) -> list[TextContent]:
    """Esegue la validazione text-only su una lista di entries contro i PDF in cartella."""
    scanned_pdfs, scan_errors = await asyncio.to_thread(
        scan_pdfs_for_text,
        documents_folder,
        max_pages,
    )

    pdf_match_counts = {pdf["filename"]: 0 for pdf in scanned_pdfs}
    matches: list[dict] = []
    missing_entries: list[dict] = []

    for entry in entries:
        match = match_entry_to_pdfs(entry, scanned_pdfs)
        if match:
            matches.append(match)
            pdf_match_counts[match["matched_file"]] += 1
        else:
            missing_entries.append({
                "code": entry.get("code"),
                "title": entry.get("title"),
                "page": entry.get("page"),
            })

    pdfs_without_matches = [name for name, count in pdf_match_counts.items() if count == 0]

    summary = {
        "expected_entries": len(entries),
        "pdfs_scanned": len(scanned_pdfs),
        "matches": len([m for m in matches if m["status"] == "matched"]),
        "code_only": len([m for m in matches if m["status"] == "code_found"]),
        "title_only": len([m for m in matches if m["status"] == "title_found"]),
        "missing_entries": len(missing_entries),
        "pdfs_with_no_matches": len(pdfs_without_matches),
        "scan_errors": len(scan_errors),
    }

    result = {
        "summary": summary,
        "matches": matches,
        "missing_entries": missing_entries,
        "pdfs_with_no_matches": pdfs_without_matches,
        "scan_errors": scan_errors,
    }

    return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]


def load_entries_from_csv(csv_path: str) -> list[dict]:
    """Carica entries da un CSV con almeno colonna 'code' (opzionale 'title')."""
    entries: list[dict] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = (row.get("code") or "").strip()
            title = (row.get("title") or "").strip()
            if not code and not title:
                continue
            entries.append({
                "code": code,
                "code_compact": normalize_code_for_search(code),
                "title": title,
                "title_norm": normalize_title_for_search(title),
            })
    return entries


def extract_text_from_pdf(pdf_path: str, max_pages: int | None) -> dict:
    """Estrae testo (upper/compact/lower) da un PDF."""
    try:
        doc = fitz.open(pdf_path)
        texts = []
        page_count = len(doc) if max_pages is None else min(len(doc), max_pages)
        for i in range(page_count):
            try:
                texts.append(doc.load_page(i).get_text("text") or "")
            except Exception:
                texts.append("")
        doc.close()
    except Exception:
        texts = []
        with pdfplumber.open(pdf_path) as pdf:
            pages = pdf.pages if max_pages is None else pdf.pages[:max_pages]
            for p in pages:
                try:
                    texts.append(p.extract_text() or "")
                except Exception:
                    texts.append("")
    full = "\n".join(texts)
    upper = full.upper()
    return {
        "upper": upper,
        "compact": re.sub(r"[^A-Z0-9]", "", upper),
        "lower": normalize_title_for_search(full),
    }


def scan_pdfs_content(folder: str, max_pages: int | None, log_every: int | None = 20, max_workers: int | None = 4) -> tuple[list[dict], list[str]]:
    """Scansione ricorsiva PDF con log periodici, parallela su thread."""
    scanned: list[dict] = []
    errors: list[str] = []
    pdf_files: list[str] = []
    for root, _, files in os.walk(folder):
        for name in files:
            if name.lower().endswith(".pdf"):
                pdf_files.append(os.path.join(root, name))

    total = len(pdf_files)
    start = time.perf_counter()

    def process(path: str):
        rel = os.path.relpath(path, folder)
        try:
            text = extract_text_from_pdf(path, max_pages)
        except Exception as exc:
            return rel, {"upper": "", "compact": "", "lower": ""}, str(exc)
        return rel, text, None

    with ThreadPoolExecutor(max_workers=max_workers or 4) as executor:
        futures = {executor.submit(process, p): p for p in pdf_files}
        for idx, future in enumerate(as_completed(futures), 1):
            rel, text, err = future.result()
            if err:
                errors.append(f"{rel}: {err}")
                text = {"upper": "", "compact": "", "lower": ""}
            scanned.append({
                "filename": rel,
                "path": os.path.join(folder, rel),
                **text,
                "file_upper": rel.upper(),
                "file_lower": rel.lower(),
                "file_compact": re.sub(r"[^A-Z0-9]", "", rel.upper()),
            })
            if log_every and (idx % log_every == 0 or idx == total):
                elapsed = time.perf_counter() - start
                print(f"[LOG] Processed {idx}/{total} PDFs in {elapsed:.1f}s", file=sys.stderr, flush=True)

    return scanned, errors


def match_entry_content(entry: dict, scanned: list[dict]) -> dict | None:
    """Match che richiede il codice nel testo o nel filename; il titolo aiuta ma non è obbligatorio."""
    code_compact = entry.get("code_compact", "")
    title_norm = entry.get("title_norm", "")
    for pdf in scanned:
        code_found = code_compact and (code_compact in pdf["compact"] or code_compact in pdf["file_compact"])
        title_found = title_norm and (title_norm in pdf["lower"] or title_norm in pdf["file_lower"])
        if code_found or (code_found and title_found):
            status = "matched" if title_found else "code_found"
            return {
                "matched_file": pdf["filename"],
                "status": status,
                "code_found": code_found,
                "title_found": title_found,
            }
    return None


async def handle_content_scan(arguments: dict) -> list[TextContent]:
    """Handler per scansione contenuto PDF vs CSV (codice nel testo)."""
    params = ContentScanParams(**arguments)
    entries = load_entries_from_csv(params.entries_csv)
    print(f"[LOG] Loaded {len(entries)} entries from {params.entries_csv}", file=sys.stderr, flush=True)

    scanned, scan_errors = await asyncio.to_thread(
        scan_pdfs_content,
        params.documents_folder,
        params.max_pages,
        params.log_every,
        params.max_workers,
    )

    matches: list[dict] = []
    missing: list[dict] = []
    for e in entries:
        m = match_entry_content(e, scanned)
        if m:
            m.update({"code": e.get("code"), "title": e.get("title")})
            matches.append(m)
        else:
            missing.append({"code": e.get("code"), "title": e.get("title")})

    summary = {
        "entries": len(entries),
        "pdfs_scanned": len(scanned),
        "matches": len(matches),
        "missing": len(missing),
        "scan_errors": len(scan_errors),
    }

    result = {
        "summary": summary,
        "matches": matches[:50],  # limit to avoid huge payloads
        "missing": missing[:50],
        "scan_errors": scan_errors[:20],
    }

    return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]


async def validate_folders_text_mode(params: ValidateFoldersParams) -> list[TextContent]:
    """Nuova modalità: estrai tabella dal PDF elenco e cerca codice/titolo nel testo dei PDF."""
    list_parser = MasterListParser()

    entries = await asyncio.to_thread(list_parser.parse_table_entries, params.master_list_pdf)
    if not entries:
        codes = await asyncio.to_thread(list_parser.parse_master_list, params.master_list_pdf)
        entries = [{"code": code, "title": "", "row": [], "page": None} for code in codes]
    return await run_text_check(entries, params.documents_folder, params.max_pages_to_scan)


# --- HANDLER PER VALIDATE_FOLDERS ---
async def handle_validate_folders(arguments: dict) -> list[TextContent]:
    """Handler per il tool validate_folders"""
    try:
        # Valida i parametri
        params = ValidateFoldersParams(**arguments)

        mode = (params.mode or "text_search").lower().strip()
        if mode == "text_search":
            return await validate_folders_text_mode(params)

        # Inizializza gli estrattori
        code_extractor = FolderCodeExtractor()
        list_parser = MasterListParser()

        # Estrai i codici dai documenti nella cartella
        print(f"[INFO] Scansione documenti in: {params.documents_folder}", file=sys.stderr, flush=True)
        extracted_codes = await asyncio.to_thread(
            code_extractor.extract_from_folder,
            params.documents_folder,
            recursive=False
        )
        print(f"[INFO] Estrazione completata: {len(extracted_codes)} file processati", file=sys.stderr, flush=True)

        # Estrai l'elenco dei codici attesi dalla master list
        print(f"[INFO] Parsing master list da: {params.master_list_pdf}", file=sys.stderr, flush=True)
        expected_codes = await asyncio.to_thread(
            list_parser.parse_master_list,
            params.master_list_pdf
        )
        print(f"[INFO] Master list parsed: {len(expected_codes)} codici attesi", file=sys.stderr, flush=True)

        # Prepara i set per il confronto (filtra i None)
        extracted_set = set(code for code in extracted_codes.values() if code is not None)
        expected_set = set(expected_codes)

        # Calcola le differenze
        matching = extracted_set & expected_set
        missing_from_documents = expected_set - extracted_set
        unexpected_in_documents = extracted_set - expected_set
        extraction_failures = [filename for filename, code in extracted_codes.items() if code is None]

        # Costruisci il risultato
        result = {
            "summary": {
                "total_pdfs_scanned": len(extracted_codes),
                "codes_extracted_successfully": len([c for c in extracted_codes.values() if c]),
                "extraction_failures": len(extraction_failures),
                "expected_codes_count": len(expected_codes),
                "matching_count": len(matching),
                "missing_count": len(missing_from_documents),
                "unexpected_count": len(unexpected_in_documents)
            },
            "matching": {
                "description": "Codici trovati nei documenti che corrispondono alla master list",
                "codes": sorted(list(matching)),
                "count": len(matching)
            },
            "missing_from_documents": {
                "description": "Codici presenti nella master list ma non trovati nei documenti",
                "codes": sorted(list(missing_from_documents)),
                "count": len(missing_from_documents)
            },
            "unexpected_in_documents": {
                "description": "Codici trovati nei documenti ma non presenti nella master list",
                "codes": sorted(list(unexpected_in_documents)),
                "count": len(unexpected_in_documents)
            },
            "extraction_failures": {
                "description": "File per i quali l'estrazione del codice è fallita",
                "files": extraction_failures,
                "count": len(extraction_failures)
            },
            "details": {
                "description": "Dettaglio di tutti i file scansionati",
                "files": {
                    filename: code if code else "ESTRAZIONE_FALLITA"
                    for filename, code in extracted_codes.items()
                }
            }
        }

        return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

    except FileNotFoundError as e:
        raise McpError(ErrorData(code=INVALID_PARAMS, message=str(e)))
    except Exception as e:
        raise McpError(ErrorData(code=INTERNAL_ERROR, message=f"Errore durante la validazione: {str(e)}"))


async def handle_extract_table(arguments: dict) -> list[TextContent]:
    """Estrae la tabella (codice + titolo) dal PDF elenco documenti."""
    params = ExtractTableParams(**arguments)
    list_parser = MasterListParser()
    entries = await asyncio.to_thread(list_parser.parse_table_entries, params.master_list_pdf)
    if not entries:
        codes = await asyncio.to_thread(list_parser.parse_master_list, params.master_list_pdf)
        entries = [{"code": code, "title": "", "row": [], "page": None} for code in codes]

    # Salva CSV vicino al file (o percorso custom)
    if params.output_csv:
        csv_path = params.output_csv
    else:
        base, _ = os.path.splitext(params.master_list_pdf)
        csv_path = f"{base}_entries.csv"

    def _clean(val: str) -> str:
        return re.sub(r"\s+", " ", (val or "")).strip()

    # Costruisce l'ordine dei campi di tabella unendo tutti gli header rilevati
    table_fields: list[str] = []
    for e in entries:
        for h in e.get("headers", []):
            if h not in table_fields:
                table_fields.append(h)

    try:
        os.makedirs(os.path.dirname(csv_path), exist_ok=True) if os.path.dirname(csv_path) else None
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["code", "title", "page", "source", *table_fields, "row_text"])
            for e in entries:
                row_cells = e.get("row", [])
                row_text = " | ".join([_clean(c) for c in row_cells if c])
                row_dict = e.get("row_dict", {}) or {}
                writer.writerow([
                    _clean(e.get("code", "")),
                    _clean(e.get("title", "")),
                    e.get("page", ""),
                    e.get("source", ""),
                    *[row_dict.get(field, "") for field in table_fields],
                    row_text,
                ])
    except Exception as exc:
        raise McpError(ErrorData(code=INTERNAL_ERROR, message=f"Errore salvataggio CSV: {exc}"))

    return [TextContent(type="text", text=json.dumps({"entries": entries, "csv_path": csv_path}, indent=2, ensure_ascii=False))]


async def handle_check_documents(arguments: dict) -> list[TextContent]:
    """Verifica una cartella di PDF usando entries già estratte."""
    params = CheckDocumentsParams(**arguments)
    entries = load_entries(params.entries)
    return await run_text_check(entries, params.documents_folder, params.max_pages_to_scan)


# --- CREAZIONE DEL SERVER MCP ---
def create_verifica_codici_server() -> Server:
    """
    Crea e configura il server MCP per la verifica dei codici.
    Questa funzione può essere riutilizzata per diversi tipi di trasporto.
    """
    server = Server("verifica-codici")

    # --- REGISTRAZIONE DEL TOOL ---
    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="start_verification",
                description="Avvia il processo di verifica dei documenti a partire da un file di elenco.",
                inputSchema=VerificaCodiciParams.model_json_schema(),
            ),
            Tool(
                name="extract_table",
                description="Estrae la tabella (codice + titolo) dal PDF elenco documenti.",
                inputSchema=ExtractTableParams.model_json_schema(),
            ),
            Tool(
                name="check_documents",
                description="Controlla i PDF in una cartella usando una lista di entries già estratte (code/title).",
                inputSchema=CheckDocumentsParams.model_json_schema(),
            ),
            Tool(
                name="content_scan",
                description="Scansione ricorsiva dei PDF: verifica che i codici presenti in un CSV compaiano nel contenuto dei PDF (o nei nomi file). Log di avanzamento su stderr.",
                inputSchema=ContentScanParams.model_json_schema(),
            ),
            Tool(
                name="validate_folders",
                description="Esegue end-to-end: estrae la tabella dal PDF elenco e verifica i PDF in cartella. Usare mode='text_search' (default) per controllo testuale o 'vlm' per OCR/VLM.",
                inputSchema=ValidateFoldersParams.model_json_schema(),
            )
        ]

    # --- GESTIONE DELLA CHIAMATA AL TOOL ---
    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        if name == "validate_folders":
            return await handle_validate_folders(arguments)
        if name == "extract_table":
            return await handle_extract_table(arguments)
        if name == "check_documents":
            return await handle_check_documents(arguments)
        if name == "content_scan":
            return await handle_content_scan(arguments)
        if name != "start_verification":
            raise McpError(ErrorData(code=INVALID_PARAMS, message=f"Tool '{name}' non definito."))

        try:
            # Validazione dei parametri di input tramite Pydantic
            params = VerificaCodiciParams(**arguments)

            # --- ESECUZIONE DELLA LOGICA DI ORCHESTRAZIONE ---

            folder_code_extractor = FolderCodeExtractor()

            # STEP 1 - script1: Estrazione dell'elenco documenti
            elenco_da_controllare = await asyncio.to_thread(estrai_elenco_documenti, params.index_pdf_path, params.codice_commessa)
            if not elenco_da_controllare:
                return [TextContent(type="text", text="Verifica completata: nessun documento trovato nell'elenco fornito.")]
            
            risultati_negativi = []
            risultati_positivi = []
            # Inizio ciclo di elaborazione
            for doc in elenco_da_controllare:
                titolo_documento = doc.get('titolo', 'Titolo Sconosciuto')
                
                try:
                    # STEP 2 - script2: Recupero del file specifico tramite RAG
                    percorso_file = await recupera_percorso_file(titolo_documento, params.collection_id)

                    # STEP 3 - Estrazione diretta del codice dal PDF tramite VLM
                    codice_estratto = await asyncio.to_thread(
                        folder_code_extractor.extract_from_pdf,
                        percorso_file,
                    )
                    if not codice_estratto:
                        raise ValueError("Estrazione del codice fallita tramite VLM.")

                    # STEP 5 - script5: Verifica dei codici
                    risultato_verifica = verifica_codici(doc, codice_estratto)

                    if risultato_verifica['status'] == 'FAILED':
                        risultati_negativi.append(risultato_verifica)
                    elif risultato_verifica['status'] == 'SUCCESS':
                        risultati_positivi.append(risultato_verifica)
                
                except Exception as e:
                    risultati_negativi.append({
                        'titolo_documento': titolo_documento,
                        'status': 'FAILED',
                        'error_details': f"Errore durante l'elaborazione: {str(e)}"
                    })
                    continue
            
            # --- Creazione del Report Finale ---
            if not risultati_negativi:
                report_lines = [f"Successo! I codici di tutti i {len(elenco_da_controllare)} documenti analizzati coincidono."]
                for ris in risultati_positivi:
                    line = (
                        f"- Titolo: {ris['titolo_documento']}\n"
                        f"  Codice Atteso:   {ris.get('codice_atteso', 'N/A')}\n"
                        f"  Codice Estratto: {ris.get('codice_estratto', 'N/A')}"
                    )
                    report_lines.append(line)
                report_finale = "\n".join(report_lines)
            else:
                report_lines = [f"Sono stati trovati {len(risultati_negativi)} documenti con errori:"]
                for res in risultati_negativi:
                    line = (
                        f"- Titolo: {res['titolo_documento']}\n"
                        f"  Codice Atteso:   {res.get('codice_atteso', 'N/A')}\n"
                        f"  Codice Estratto: {res.get('codice_estratto', 'N/A')}\n"
                        f"  Dettagli Errore: {res.get('error_details', 'N/A')}"
                    )
                    report_lines.append(line)
                if risultati_positivi:
                    report_lines.append(f"\n--- DOCUMENTI CORRETTI ({len(risultati_positivi)}) ---")
                    for ris in risultati_positivi:
                        line = (
                            f"- Titolo: {ris['titolo_documento']}\n"
                            f"  Codice Atteso:   {ris.get('codice_atteso', 'N/A')}\n"
                            f"  Codice Estratto: {ris.get('codice_estratto', 'N/A')}"
                        )
                        report_lines.append(line)

                report_finale = "\n".join(report_lines)

            return [TextContent(type="text", text=report_finale)]

        except Exception as e:
            # Cattura errori di validazione Pydantic o altri errori imprevisti
            raise McpError(ErrorData(code=INTERNAL_ERROR, message=f"Errore durante l'esecuzione del tool: {e}"))

    return server


# --- FUNZIONE PRINCIPALE DEL SERVER (STDIO MODE) ---
async def serve():
    """
    Funzione principale che configura e avvia il server MCP per la verifica dei codici in modalità stdio.
    """
    server = create_verifica_codici_server()

    # --- AVVIO DEL SERVER IN MODALITÀ STDIO ---
    options = server.create_initialization_options()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, options)

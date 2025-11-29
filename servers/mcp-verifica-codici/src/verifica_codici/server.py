import asyncio
import os
import json
import sys
import re
import csv
import time
from typing import Any, List
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
from .rag_client import query_documents

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
    mode: str | None = Field(default="rag_query", description="Strategia di validazione: 'rag_query' (default) usa il servizio di query già indicizzato; 'text_search' scansiona i PDF localmente; 'vlm' usa OCR/VLM precedente.")
    collection_id: str | None = Field(default=None, description="Collection ID da interrogare quando mode='rag_query'. Se assente, usa il basename di documents_folder.")
    query_limit: int | None = Field(default=5, description="Numero di documenti da recuperare per query in modalità rag_query.")
    search_mode: str | None = Field(default="standard", description="Search mode da passare all'endpoint di query (rag_query).")
    max_pages_to_scan: int | None = Field(default=3, description="Numero massimo di pagine da leggere per ogni PDF nella modalità text_search (None per tutte le pagine).")
    columns_to_check: list[str] | None = Field(default=None, description="Colonne da verificare nei PDF in modalità text_search. Supportate: 'code', 'title' (alias 'description'). Default: entrambe.")
    exclude_files: list[str] | None = Field(default=None, description="Lista di file (basename) da escludere dal controllo in modalità text_search (es. l'elenco documenti stesso).")
    recursive: bool = Field(default=True, description="Se true, scansiona ricorsivamente le sottocartelle alla ricerca di PDF.")

class CheckDocumentsParams(BaseModel):
    documents_folder: str = Field(..., description="Cartella con i PDF da controllare.")
    entries: list[dict] | str = Field(..., description="Lista di oggetti {code,title,...}, stringa JSON della lista oppure percorso a file CSV/JSON con i codici.")
    mode: str | None = Field(default="rag_query", description="Modalità: 'rag_query' (default) usa l'endpoint di query esistente; 'text_search' legge i PDF localmente.")
    collection_id: str | None = Field(default=None, description="Collection ID da interrogare quando mode='rag_query'. Se assente, usa il basename di documents_folder.")
    query_limit: int | None = Field(default=5, description="Numero di risultati da richiedere per query in rag_query.")
    search_mode: str | None = Field(default="standard", description="Search mode da passare al servizio di query.")
    max_pages_to_scan: int | None = Field(default=3, description="Numero massimo di pagine da leggere per ogni PDF (None per tutte le pagine).")
    columns_to_check: list[str] | None = Field(default=None, description="Colonne da verificare nei PDF. Supportate: 'code', 'title' (alias 'description'). Default: entrambe.")
    exclude_files: list[str] | None = Field(default=None, description="Lista di file (basename) da escludere dal controllo (es. l'elenco documenti).")
    recursive: bool = Field(default=True, description="Se true, scansiona ricorsivamente le sottocartelle alla ricerca di PDF.")

class ContentScanParams(BaseModel):
    entries_csv: str = Field(..., description="Percorso al CSV con almeno la colonna 'code' (e opzionalmente 'title').")
    documents_folder: str = Field(..., description="Cartella (scansione ricorsiva) con i PDF da confrontare.")
    max_pages: int | None = Field(default=2, description="Pagine da leggere per ogni PDF (None per tutte).")
    log_every: int | None = Field(default=20, description="Frequenza di log di avanzamento (numero di PDF).")
    max_workers: int | None = Field(default=4, description="Numero di thread per la scansione PDF (CPU bound I/O).")
    columns_to_check: list[str] | None = Field(default=None, description="Lista di colonne da verificare nei PDF. Supportate: 'code', 'title' (o 'description'). Default: entrambe.")
    exclude_files: list[str] | None = Field(default=None, description="Elenco di file (basename o percorso relativo) da escludere dalla scansione.")

def normalize_title_for_search(text: str) -> str:
    """Normalizza una stringa descrittiva per il confronto case-insensitive."""
    if not isinstance(text, str):
        text = "" if text is None else str(text)
    lowered = (text or "").lower()
    cleaned = re.sub(r"[^a-z0-9]+", " ", lowered)
    return re.sub(r"\s+", " ", cleaned).strip()

def normalize_code_for_search(code: str) -> str:
    """Normalizza un codice rimuovendo tutto tranne A-Z0-9."""
    if not isinstance(code, str):
        code = "" if code is None else str(code)
    return re.sub(r"[^A-Z0-9]", "", (code or "").upper())


def normalize_columns(cols: list[str] | None) -> list[str]:
    """Normalizza le colonne richieste; alias 'description' -> 'title'."""
    allowed = {"code", "title"}
    normalized: list[str] = []
    for c in cols or ["code", "title"]:
        name = str(c).strip().lower()
        if name == "description":
            name = "title"
        if name in allowed:
            normalized.append(name)
    return normalized or ["code", "title"]


def load_entries(entries_param: list[dict] | str) -> list[dict]:
    """Normalizza l'input entries in lista di dict con almeno 'code'/'title'."""
    raw_entries = entries_param

    if isinstance(entries_param, str):
        possible_path = entries_param.strip()

        # Percorso a file CSV/JSON
        if os.path.exists(possible_path):
            if possible_path.lower().endswith(".csv"):
                try:
                    raw_entries = load_entries_from_csv(possible_path)
                except Exception as exc:
                    raise McpError(ErrorData(code=INVALID_PARAMS, message=f"Impossibile leggere il CSV entries: {exc}"))
            else:
                try:
                    with open(possible_path, "r", encoding="utf-8") as f:
                        raw_entries = json.load(f)
                except json.JSONDecodeError as exc:
                    raise McpError(ErrorData(code=INVALID_PARAMS, message=f"Il file entries non è un JSON valido: {exc}"))
                except Exception as exc:
                    raise McpError(ErrorData(code=INVALID_PARAMS, message=f"Impossibile leggere il file entries: {exc}"))
        elif possible_path.lower().endswith((".csv", ".json")) or ("/" in possible_path or "\\" in possible_path):
            # L'utente ha passato qualcosa che sembra un percorso ma non esiste.
            raise McpError(ErrorData(code=INVALID_PARAMS, message=f"File entries non trovato: {possible_path}"))
        else:
            try:
                raw_entries = json.loads(entries_param)
            except json.JSONDecodeError as exc:
                raise McpError(ErrorData(
                    code=INVALID_PARAMS,
                    message=f"entries deve essere una lista JSON, un percorso CSV/JSON o una lista di oggetti. Errore di parsing JSON: {exc}"
                ))

    if not isinstance(raw_entries, list):
        raise McpError(ErrorData(code=INVALID_PARAMS, message="entries deve essere una lista di oggetti o un file CSV/JSON contenente tale lista."))

    cleaned = []
    for item in raw_entries:
        if not isinstance(item, dict):
            continue
        code_val = item.get("code", "")
        title_val = item.get("title", "")
        # Coerce to string to avoid attribute errors
        if not isinstance(code_val, str):
            code_val = "" if code_val is None else str(code_val)
        if not isinstance(title_val, str):
            title_val = "" if title_val is None else str(title_val)
        cleaned.append({
            "code": code_val or "",
            "title": title_val or "",
            "row": item.get("row", []),
            "page": item.get("page"),
        })
    return cleaned


def derive_collection_id(documents_folder: str | None, explicit_collection: str | None) -> str | None:
    """Ricava il collection_id partendo dall'input esplicito o dal basename della cartella."""
    if explicit_collection and str(explicit_collection).strip():
        return str(explicit_collection).strip()
    if documents_folder:
        folder = str(documents_folder).rstrip("/\\")
        return os.path.basename(folder)
    return None


async def send_progress(server: Server, current: float, total: float | None = None, label: str | None = None):
    """
    Invia notifiche di avanzamento MCP se il client ha fornito progressToken.
    """
    try:
        ctx = server.request_context
    except LookupError:
        if label:
            print(f"[PROGRESS] {current}/{total}: {label}", file=sys.stderr, flush=True)
        return

    if ctx.meta and ctx.meta.progressToken is not None:
        try:
            await ctx.session.send_progress_notification(ctx.meta.progressToken, current, total)
        except Exception as exc:
            print(f"[WARN] Progress notification failed: {exc}", file=sys.stderr, flush=True)
    if label:
        print(f"[PROGRESS] {current}/{total}: {label}", file=sys.stderr, flush=True)


def extract_text_from_pdf(pdf_path: str, max_pages: int | None = None) -> str:
    """Estrae il testo da un PDF (prime max_pages, se specificato). Usa PyMuPDF se disponibile, fallback pdfplumber."""
    texts: list[str] = []
    # Primo tentativo: PyMuPDF (fitz), più veloce/robusto
    try:
        doc = fitz.open(pdf_path)
        page_count = len(doc) if max_pages is None else min(len(doc), max_pages)
        for i in range(page_count):
            try:
                texts.append(doc.load_page(i).get_text("text") or "")
            except Exception:
                texts.append("")
        doc.close()
        return "\n".join(texts)
    except Exception:
        pass

    # Fallback: pdfplumber
    try:
        with pdfplumber.open(pdf_path) as pdf:
            pages = pdf.pages if max_pages is None else pdf.pages[:max_pages]
            for page in pages:
                try:
                    texts.append(page.extract_text() or "")
                except Exception as exc:
                    print(f"[WARN] Impossibile estrarre testo da {pdf_path}: {exc}", file=sys.stderr, flush=True)
    except Exception as exc:
        print(f"[WARN] Apertura PDF fallita {pdf_path}: {exc}", file=sys.stderr, flush=True)
    return "\n".join(texts)


def scan_pdfs_for_text(folder_path: str, max_pages: int | None = None, exclude_files: list[str] | None = None, recursive: bool = True) -> tuple[list[dict], list[str]]:
    """Legge PDF (anche ricorsivamente) e prepara testi normalizzati per la ricerca."""
    if not os.path.exists(folder_path):
        raise FileNotFoundError(f"Cartella non trovata: {folder_path}")

    exclude_norm = {f.lower().strip() for f in (exclude_files or []) if f}
    pdf_files: list[str] = []
    if recursive:
        for root, _, files in os.walk(folder_path):
            for name in files:
                if not name.lower().endswith(".pdf"):
                    continue
                if name.lower() in exclude_norm:
                    continue
                pdf_files.append(os.path.join(root, name))
    else:
        pdf_files = sorted([
            os.path.join(folder_path, f)
            for f in os.listdir(folder_path)
            if f.lower().endswith(".pdf") and f.lower() not in exclude_norm
        ])

    scanned: list[dict] = []
    errors: list[str] = []

    for pdf_path in sorted(pdf_files):
        try:
            text = extract_text_from_pdf(pdf_path, max_pages=max_pages)
        except Exception as exc:
            errors.append(f"{os.path.relpath(pdf_path, folder_path)}: {exc}")
            text = ""

        upper_text = (text or "").upper()
        compact_text = re.sub(r"[^A-Z0-9]", "", upper_text)
        lower_text = normalize_title_for_search(text)

        scanned.append({
            "filename": os.path.relpath(pdf_path, folder_path),
            "path": pdf_path,
            "text_upper": upper_text,
            "text_lower": lower_text,
            "text_compact": compact_text,
            "file_upper": os.path.basename(pdf_path).upper(),
            "file_lower": os.path.basename(pdf_path).lower(),
            "file_compact": re.sub(r"[^A-Z0-9]", "", os.path.basename(pdf_path).upper()),
        })

    return scanned, errors


def match_entry_to_pdfs(entry: dict, scanned_pdfs: list[dict], columns_to_check: list[str] | None = None) -> dict | None:
    """Trova il PDF che contiene codice e/o titolo dell'entry, rispettando le colonne richieste."""
    cols = normalize_columns(columns_to_check)
    check_code = "code" in cols
    check_title = "title" in cols

    code = entry.get("code", "")
    if not isinstance(code, str):
        code = "" if code is None else str(code)
    compact_code = re.sub(r"[^A-Z0-9]", "", code.upper())
    title_val = entry.get("title", "")
    if not isinstance(title_val, str):
        title_val = "" if title_val is None else str(title_val)
    title_norm = normalize_title_for_search(title_val)

    code_required = check_code and bool(code)
    title_required = check_title and bool(title_norm)

    best_match: dict | None = None
    for pdf in scanned_pdfs:
        code_found = False
        if code_required:
            code_found = (
                code in pdf["text_upper"]
                or (compact_code and compact_code in pdf["text_compact"])
                or code in pdf["file_upper"]
                or (compact_code and compact_code in pdf["file_compact"])
            )

        title_found = False
        if title_required:
            title_found = (
                title_norm in pdf["text_lower"]
                or title_norm in pdf["file_lower"]
            )

        status = None
        if code_required and title_required:
            if code_found and title_found:
                status = "matched"
            elif code_found:
                status = "code_found"
            elif title_found:
                status = "title_found"
        elif code_required:
            if code_found:
                status = "code_found"
        elif title_required:
            if title_found:
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


def _stringify_field(value: Any) -> str:
    if isinstance(value, list):
        return " ".join([v for v in value if isinstance(v, str)])
    if value is None:
        return ""
    return str(value)


def flatten_doc_text(doc: dict) -> dict:
    """Estrae testo aggregato e info filename da un documento di risposta RAG."""
    text_parts: list[str] = []

    for key in ("page_content", "content", "text", "chunk", "chunk_text"):
        val = doc.get(key)
        str_val = _stringify_field(val)
        if str_val:
            text_parts.append(str_val)

    metadata = doc.get("metadata") or {}
    if isinstance(metadata, dict):
        for key in ("text", "content", "chunk", "chunk_text", "description", "title", "body"):
            str_val = _stringify_field(metadata.get(key))
            if str_val:
                text_parts.append(str_val)

    combined = " ".join([t for t in text_parts if t]).strip()
    upper = combined.upper()
    lower = normalize_title_for_search(combined)
    compact = re.sub(r"[^A-Z0-9]", "", upper)

    file_path = None
    if isinstance(metadata, dict):
        file_path = (
            metadata.get("file_path")
            or metadata.get("path")
            or metadata.get("source")
            or metadata.get("filename")
        )
    file_path = file_path or doc.get("file_path") or doc.get("source")
    filename = os.path.basename(file_path) if file_path else ""

    return {
        "text_upper": upper,
        "text_lower": lower,
        "text_compact": compact,
        "file_path": file_path or "",
        "filename": filename or "",
        "file_upper": (filename or "").upper(),
        "file_lower": (filename or "").lower(),
        "file_compact": re.sub(r"[^A-Z0-9]", "", (filename or "").upper()),
    }


async def match_entry_via_rag(
    entry: dict,
    collection_id: str,
    limit: int = 5,
    search_mode: str | None = "standard",
    columns_to_check: list[str] | None = None,
) -> dict | None:
    """Interroga il servizio di query e verifica presenza di code/title nel testo indicizzato."""
    code = entry.get("code", "")
    if not isinstance(code, str):
        code = "" if code is None else str(code)
    code_compact = normalize_code_for_search(code)

    title_val = entry.get("title", "")
    if not isinstance(title_val, str):
        title_val = "" if title_val is None else str(title_val)
    title_norm = normalize_title_for_search(title_val)

    cols = normalize_columns(columns_to_check)
    check_code = "code" in cols
    check_title = "title" in cols

    query_text = " ".join([part for part in [code, title_val] if part]).strip() or code or title_val
    docs = await query_documents(
        query=query_text,
        collection_id=collection_id,
        limit=limit or 5,
        search_mode=search_mode or "standard",
    )

    if not isinstance(docs, list):
        return None

    for doc in docs:
        flat = flatten_doc_text(doc)

        code_found = bool(check_code and code_compact and (
            code_compact in flat["text_compact"] or code_compact in flat["file_compact"]
        ))

        title_found = bool(check_title and title_norm and (
            title_norm in flat["text_lower"] or title_norm in flat["file_lower"]
        ))

        code_required = check_code and bool(code_compact)
        title_required = check_title and bool(title_norm)

        status = None
        if code_required and title_required:
            if code_found and title_found:
                status = "matched"
            elif code_found or title_found:
                status = "partial"
        elif code_required:
            if code_found:
                status = "code_found"
        elif title_required:
            if title_found:
                status = "title_found"

        if status:
            return {
                "code": code,
                "title": title_val,
                "matched_file": flat["filename"] or flat["file_path"],
                "file_path": flat["file_path"],
                "status": status,
                "code_found": code_found,
                "title_found": title_found,
                "query": query_text,
                "score": doc.get("score"),
                "checked_columns": cols,
            }

    return None


async def run_text_check(entries: list[dict], documents_folder: str, max_pages: int | None, columns_to_check: list[str] | None = None, exclude_files: list[str] | None = None, recursive: bool = True) -> list[TextContent]:
    """Esegue la validazione text-only su una lista di entries contro i PDF in cartella."""
    cols = normalize_columns(columns_to_check)
    scanned_pdfs, scan_errors = await asyncio.to_thread(
        scan_pdfs_for_text,
        documents_folder,
        max_pages,
        exclude_files,
        recursive,
    )

    pdf_match_counts = {pdf["filename"]: 0 for pdf in scanned_pdfs}
    matches: list[dict] = []
    missing_entries: list[dict] = []

    for entry in entries:
        match = match_entry_to_pdfs(entry, scanned_pdfs, cols)
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
        "columns_checked": cols,
        "excluded_files": exclude_files or [],
        "recursive": recursive,
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
            code_val = row.get("code")
            title_val = row.get("title")
            if not isinstance(code_val, str):
                code_val = "" if code_val is None else str(code_val)
            if not isinstance(title_val, str):
                title_val = "" if title_val is None else str(title_val)
            code = (code_val or "").strip()
            title = (title_val or "").strip()
            if not code and not title:
                continue
            entries.append({
                "code": code,
                "code_compact": normalize_code_for_search(code),
                "title": title,
                "title_norm": normalize_title_for_search(title),
            })
    return entries


def extract_text_from_pdf_structured(pdf_path: str, max_pages: int | None) -> dict:
    """Estrae testo (upper/compact/lower) da un PDF in forma strutturata."""
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


def scan_pdfs_content(folder: str, max_pages: int | None, log_every: int | None = 20, max_workers: int | None = 4, exclude_files: list[str] | None = None) -> tuple[list[dict], list[str]]:
    """Scansione ricorsiva PDF con log periodici, parallela su thread."""
    scanned: list[dict] = []
    errors: list[str] = []
    pdf_files: list[str] = []

    exclude_norm = [e.lower().strip() for e in (exclude_files or []) if e and str(e).strip()]

    def is_excluded(path: str) -> bool:
        if not exclude_norm:
            return False
        rel = os.path.relpath(path, folder).lower()
        base = os.path.basename(path).lower()
        for pat in exclude_norm:
            if base == pat or rel == pat or rel.endswith(pat):
                return True
        return False

    for root, _, files in os.walk(folder):
        for name in files:
            if name.lower().endswith(".pdf"):
                path = os.path.join(root, name)
                if not is_excluded(path):
                    pdf_files.append(path)

    total = len(pdf_files)
    start = time.perf_counter()

    def process(path: str):
        rel = os.path.relpath(path, folder)
        try:
            text = extract_text_from_pdf_structured(path, max_pages)
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


def match_entry_content(entry: dict, scanned: list[dict], columns_to_check: list[str]) -> dict | None:
    """Match che richiede le colonne selezionate (code/title) nel testo o nel filename."""
    code_compact = entry.get("code_compact", "")
    title_norm = entry.get("title_norm", "")

    check_code = "code" in columns_to_check
    check_title = "title" in columns_to_check

    for pdf in scanned:
        code_in_text = bool(code_compact and code_compact in pdf["compact"]) if check_code else False
        code_in_filename = bool(code_compact and code_compact in pdf["file_compact"]) if check_code else False
        title_in_text = bool(title_norm and title_norm in pdf["lower"]) if check_title else False
        title_in_filename = bool(title_norm and title_norm in pdf["file_lower"]) if check_title else False

        # Colonne richieste ma vuote vengono ignorate.
        code_required = check_code and bool(code_compact)
        title_required = check_title and bool(title_norm)

        code_ok = (not code_required) or code_in_text or code_in_filename
        title_ok = (not title_required) or title_in_text or title_in_filename

        if code_required and title_required:
            if code_ok and title_ok:
                status = "matched"
            elif code_ok or title_ok:
                status = "partial"
            else:
                continue
        elif code_required:
            if not code_ok:
                continue
            status = "code_found"
        elif title_required:
            if not title_ok:
                continue
            status = "title_found"
        else:
            continue

        return {
            "matched_file": pdf["filename"],
            "status": status,
            "code_in_text": code_in_text,
            "code_in_filename": code_in_filename,
            "title_in_text": title_in_text,
            "title_in_filename": title_in_filename,
            "checked_columns": columns_to_check,
        }

    return None


async def handle_content_scan(arguments: dict) -> list[TextContent]:
    """Handler per scansione contenuto PDF vs CSV (codice nel testo)."""
    params = ContentScanParams(**arguments)

    def normalize_columns(cols: list[str] | None) -> list[str]:
        allowed = {"code", "title"}
        normalized: list[str] = []
        for c in cols or ["code", "title"]:
            name = str(c).strip().lower()
            if name == "description":
                name = "title"
            if name in allowed:
                normalized.append(name)
        return normalized or ["code", "title"]

    columns_to_check = normalize_columns(params.columns_to_check)

    entries = load_entries_from_csv(params.entries_csv)
    print(f"[LOG] Loaded {len(entries)} entries from {params.entries_csv}", file=sys.stderr, flush=True)

    scanned, scan_errors = await asyncio.to_thread(
        scan_pdfs_content,
        params.documents_folder,
        params.max_pages,
        params.log_every,
        params.max_workers,
        params.exclude_files,
    )

    matches: list[dict] = []
    missing: list[dict] = []
    for e in entries:
        m = match_entry_content(e, scanned, columns_to_check)
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
        "columns_checked": columns_to_check,
        "excluded_files": params.exclude_files or [],
    }

    result = {
        "summary": summary,
        "matches": matches[:50],  # limit to avoid huge payloads
        "missing": missing[:50],
        "scan_errors": scan_errors[:20],
    }

    return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]


async def validate_folders_rag_mode(params: ValidateFoldersParams, server: Server) -> list[TextContent]:
    """Modalità di verifica basata esclusivamente su RAG/query (niente OCR locale)."""
    list_parser = MasterListParser()
    entries = await asyncio.to_thread(list_parser.parse_table_entries, params.master_list_pdf)
    if not entries:
        codes = await asyncio.to_thread(list_parser.parse_master_list, params.master_list_pdf)
        entries = [{"code": code, "title": "", "row": [], "page": None} for code in codes]
    entries = load_entries(entries)

    collection_id = derive_collection_id(params.documents_folder, params.collection_id)
    if not collection_id:
        raise McpError(ErrorData(code=INVALID_PARAMS, message="collection_id mancante (fornisci esplicito o basename della cartella)."))

    total = len(entries) or 1
    await send_progress(server, 0, total, "Avvio verifica via query")

    matches: list[dict] = []
    missing: list[dict] = []
    query_errors: list[str] = []

    for idx, entry in enumerate(entries, start=1):
        try:
            match = await match_entry_via_rag(
                entry,
                collection_id=collection_id,
                limit=params.query_limit or 5,
                search_mode=params.search_mode or "standard",
                columns_to_check=params.columns_to_check,
            )
        except Exception as exc:
            match = None
            query_errors.append(f"{entry.get('code') or entry.get('title')}: {exc}")

        if match:
            matches.append(match)
        else:
            missing.append({"code": entry.get("code"), "title": entry.get("title"), "page": entry.get("page")})

        await send_progress(server, idx, total, f"Verifica {idx}/{total}")

    await send_progress(server, total, total, "Verifica completata")

    summary = {
        "expected_entries": len(entries),
        "matches": len([m for m in matches if m["status"] == "matched"]),
        "partial": len([m for m in matches if m["status"] != "matched"]),
        "missing": len(missing),
        "collection_id": collection_id,
        "query_limit": params.query_limit or 5,
        "search_mode": params.search_mode or "standard",
        "mode": "rag_query",
        "errors": len(query_errors),
    }

    result = {
        "summary": summary,
        "matches": matches[:100],
        "missing": missing[:100],
        "query_errors": query_errors[:50],
    }

    return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]


async def validate_folders_text_mode(params: ValidateFoldersParams) -> list[TextContent]:
    """Nuova modalità: estrai tabella dal PDF elenco e cerca codice/titolo nel testo dei PDF."""
    list_parser = MasterListParser()

    entries = await asyncio.to_thread(list_parser.parse_table_entries, params.master_list_pdf)
    if not entries:
        codes = await asyncio.to_thread(list_parser.parse_master_list, params.master_list_pdf)
        entries = [{"code": code, "title": "", "row": [], "page": None} for code in codes]
    # Normalizza tipi per evitare errori su .upper()/.lower()
    entries = load_entries(entries)
    return await run_text_check(entries, params.documents_folder, params.max_pages_to_scan, params.columns_to_check, params.exclude_files, params.recursive)


# --- HANDLER PER VALIDATE_FOLDERS ---
async def handle_validate_folders(arguments: dict, server: Server | None = None) -> list[TextContent]:
    """Handler per il tool validate_folders"""
    try:
        # Valida i parametri
        params = ValidateFoldersParams(**arguments)

        mode = (params.mode or "rag_query").lower().strip()
        if mode == "rag_query":
            if not server:
                raise McpError(ErrorData(code=INTERNAL_ERROR, message="Server non disponibile per progress notifications"))
            return await validate_folders_rag_mode(params, server)

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


async def check_documents_rag_mode(params: CheckDocumentsParams, server: Server) -> list[TextContent]:
    """Verifica via query RAG senza leggere i PDF localmente."""
    entries = load_entries(params.entries)
    collection_id = derive_collection_id(params.documents_folder, params.collection_id)
    if not collection_id:
        raise McpError(ErrorData(code=INVALID_PARAMS, message="collection_id mancante (fornisci esplicito o basename della cartella)."))

    cols = normalize_columns(params.columns_to_check)
    total = len(entries) or 1
    await send_progress(server, 0, total, "Avvio verifica via query")

    matches: list[dict] = []
    missing: list[dict] = []
    query_errors: list[str] = []

    for idx, entry in enumerate(entries, start=1):
        try:
            match = await match_entry_via_rag(
                entry,
                collection_id=collection_id,
                limit=params.query_limit or 5,
                search_mode=params.search_mode or "standard",
                columns_to_check=cols,
            )
        except Exception as exc:
            match = None
            query_errors.append(f"{entry.get('code') or entry.get('title')}: {exc}")

        if match:
            matches.append(match)
        else:
            missing.append({"code": entry.get("code"), "title": entry.get("title")})

        await send_progress(server, idx, total, f"Verifica {idx}/{total}")

    await send_progress(server, total, total, "Verifica completata")

    summary = {
        "entries": len(entries),
        "matches": len([m for m in matches if m["status"] == "matched"]),
        "partial": len([m for m in matches if m["status"] != "matched"]),
        "missing": len(missing),
        "collection_id": collection_id,
        "query_limit": params.query_limit or 5,
        "search_mode": params.search_mode or "standard",
        "mode": "rag_query",
        "errors": len(query_errors),
    }

    result = {
        "summary": summary,
        "matches": matches[:100],
        "missing": missing[:100],
        "query_errors": query_errors[:50],
    }

    return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]


async def handle_check_documents(arguments: dict, server: Server | None = None) -> list[TextContent]:
    """Verifica una cartella di PDF usando entries già estratte."""
    params = CheckDocumentsParams(**arguments)
    mode = (params.mode or "rag_query").lower().strip()
    if mode == "rag_query":
        if not server:
            raise McpError(ErrorData(code=INTERNAL_ERROR, message="Server non disponibile per progress notifications"))
        return await check_documents_rag_mode(params, server)

    entries = load_entries(params.entries)
    return await run_text_check(entries, params.documents_folder, params.max_pages_to_scan, params.columns_to_check, params.exclude_files, params.recursive)


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
                description="Pipeline completa VLM/RAG: parte da un PDF di elenco, recupera i PDF, estrae codice e confronta con il master.",
                inputSchema=VerificaCodiciParams.model_json_schema(),
            ),
            Tool(
                name="extract_table",
                description="Estrae la tabella (codice + titolo) dal PDF elenco documenti e salva opzionalmente un CSV *_entries.csv.",
                inputSchema=ExtractTableParams.model_json_schema(),
            ),
            Tool(
                name="check_documents",
                description="Controlla i documenti usando entries già estratte. mode='rag_query' (default) interroga il servizio di query sul collection_id; mode='text_search' legge i PDF localmente. columns_to_check per limitare a code/title; exclude_files per saltare PDF come l'elenco documenti; recursive=True per includere sottocartelle.",
                inputSchema=CheckDocumentsParams.model_json_schema(),
            ),
            Tool(
                name="content_scan",
                description="Scansione ricorsiva dei PDF: verifica che i codici (e/o titoli) di un CSV compaiano nel testo o nel nome file, con columns_to_check e log su stderr.",
                inputSchema=ContentScanParams.model_json_schema(),
            ),
            Tool(
                name="validate_folders",
                description="End-to-end: estrae tabella dal PDF elenco e verifica i PDF in cartella. mode='rag_query' (default) interroga il servizio indicizzato; mode='text_search' legge i PDF localmente; mode='vlm' usa OCR/VLM precedente.",
                inputSchema=ValidateFoldersParams.model_json_schema(),
            )
        ]

    # --- GESTIONE DELLA CHIAMATA AL TOOL ---
    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        if name == "validate_folders":
            return await handle_validate_folders(arguments, server)
        if name == "extract_table":
            return await handle_extract_table(arguments)
        if name == "check_documents":
            return await handle_check_documents(arguments, server)
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

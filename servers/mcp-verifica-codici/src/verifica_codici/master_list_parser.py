"""
Modulo per estrarre l'elenco dei codici documentali attesi dal PDF "Elenco Documenti".
"""

import re
import os
from typing import List, Dict
import fitz  # PyMuPDF
import pdfplumber

from .code_extractor_folders import FolderCodeExtractor


class MasterListParser:
    """Parser per estrarre l'elenco completo dei codici documentali dal PDF master"""

    # Pattern per riga della tabella: ADRPMV 02 PE DG GEN - - E ED 00 1
    TABLE_ROW_PATTERN = r'ADRPMV\s+(\d{2})\s+PE\s+([A-Z]{2})\s+([A-Z]{1,8})\s+[-–]\s+[-–]\s+([A-Z])\s+([A-Z]{1,4})\s+(\d{2})\s+(\d)'

    def __init__(self):
        """Inizializza il parser"""
        self._code_extractor = FolderCodeExtractor()

    def _pick_title_cell(self, cells: List[str], code: str) -> str:
        """Sceglie un campo descrittivo dal resto della riga."""
        if not cells:
            return ""
        normalized_code = code.upper()
        # Preferisce la cella più lunga che non contenga già il codice
        candidate = ""
        for cell in cells:
            if not cell:
                continue
            upper_cell = cell.upper()
            if normalized_code in upper_cell:
                continue
            if len(cell) > len(candidate):
                candidate = cell
        return candidate.strip()

    def _normalize_header(self, header: str, idx: int, existing: set[str]) -> str:
        base = re.sub(r"\s+", " ", (header or "").strip())
        base = base if base else f"col_{idx}"
        candidate = base
        counter = 1
        while candidate in existing:
            candidate = f"{base}_{counter}"
            counter += 1
        existing.add(candidate)
        return candidate

    def _pick_header_row_index(self, rows: List[List[str]]) -> int | None:
        """
        Seleziona la riga da usare come intestazione:
        - preferisce la riga con più celle descrittive (len>=3 o con spazi)
        - ignora righe composte solo da singole lettere/indici (A, B, C...)
        """
        best_idx = None
        best_score = 0
        single_letter = re.compile(r"^[A-Z]$")

        for idx, row in enumerate(rows):
            cleaned = [str(cell).strip() if cell else "" for cell in row]
            if not any(cleaned):
                continue

            descriptive = sum(1 for c in cleaned if len(c) >= 3 or " " in c)
            only_single_letters = all((not c) or single_letter.match(c) for c in cleaned if c)

            if descriptive == 0 and only_single_letters:
                continue

            if descriptive > best_score:
                best_score = descriptive
                best_idx = idx

        return best_idx

    def _process_table_rows(self, rows: List[List[str]], page_index: int | None, source: str | None, entries: List[Dict[str, str]], seen_codes: set[str]):
        """Trasforma una tabella grezza in entries con headers e row_dict."""
        if not rows:
            return
        header_idx = self._pick_header_row_index(rows)
        if header_idx is None:
            return

        def clean_token(token: str) -> str:
            return re.sub(r"[^a-z]", "", token.lower())

        fallback_schema = [
            "commessa",
            "lotto_subprogetto",
            "fase",
            "capitolo",
            "paragrafo",
            "wbs_tipologia",
            "parte_opera",
            "tipologia",
            "disciplina",
            "progressivo",
            "revisione",
            "titolo_elaborato",
            "formato",
            "scala",
            "data",
        ]
        fallback_clean = [clean_token(x) for x in fallback_schema]

        def maybe_flip_header(token: str) -> str:
            orig = token or ""
            rev = orig[::-1]
            lower_orig = orig.lower()
            c_orig = clean_token(orig)
            c_rev = clean_token(rev)
            if "ettegorp" in lower_orig or "otlapp" in lower_orig:
                return rev
            if "arepo" in lower_orig and "trap" in lower_orig:
                return rev
            if any(fc in c_rev for fc in fallback_clean) and not any(fc in c_orig for fc in fallback_clean):
                return rev
            if len(c_rev) >= len(c_orig) and sum(ch in "aeiou" for ch in c_rev) > sum(ch in "aeiou" for ch in c_orig):
                return rev
            return orig

        header_row = [maybe_flip_header(str(cell).strip() if cell else "") for cell in rows[header_idx]]
        data_rows = [[str(cell).strip() if cell else "" for cell in row] for row in rows[header_idx + 1 :]]

        def is_generic_header(token: str) -> bool:
            token = token.strip()
            if not token:
                return True
            if re.fullmatch(r"[A-Z]", token):
                return True
            if token.lower().startswith("col_"):
                return True
            return False

        use_fallback = False
        if header_row:
            generic_count = sum(1 for h in header_row if is_generic_header(h))
            if generic_count >= max(len(header_row) // 2, 6) and len(header_row) >= 12:
                use_fallback = True

        normalized_headers = []
        seen_headers = set()
        if use_fallback and len(header_row) <= len(fallback_schema):
            for idx, name in enumerate(fallback_schema[: len(header_row)]):
                normalized_headers.append(self._normalize_header(name, idx, seen_headers))
        else:
            for idx, h in enumerate(header_row):
                normalized_headers.append(self._normalize_header(h, idx, seen_headers))

        for data in data_rows:
            # Allinea lunghezza
            if len(data) < len(normalized_headers):
                data = data + [""] * (len(normalized_headers) - len(data))
            elif len(data) > len(normalized_headers):
                data = data[:len(normalized_headers)]

            row_dict = {normalized_headers[i]: (data[i] or "").strip() for i in range(len(normalized_headers))}
            row_text = " ".join([cell for cell in data if cell])
            if not row_text:
                continue

            code = self._code_extractor.parse_code_from_text(row_text)
            if not code:
                for cell in data:
                    code = self._code_extractor.parse_code_from_text(cell)
                    if code:
                        break
            if not code or code in seen_codes:
                continue
            seen_codes.add(code)

            title = self._pick_title_cell(data, code)
            entries.append({
                "code": code,
                "title": title,
                "row": data,
                "row_dict": row_dict,
                "headers": normalized_headers,
                "page": page_index,
                "source": source,
            })

    def parse_table_entries(self, pdf_path: str) -> List[Dict[str, str]]:
        """
        Estrae righe (codice + descrizione) da un PDF generico con tabelle.

        Usa pdfplumber per leggere tutte le tabelle senza affidarsi a posizioni fisse.
        Ritorna una lista di dict: {'code', 'title', 'row', 'page'}.
        """
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF master list non trovato: {pdf_path}")

        entries: List[Dict[str, str]] = []
        seen_codes: set[str] = set()
        with pdfplumber.open(pdf_path) as pdf:
            for page_index, page in enumerate(pdf.pages, start=1):
                tables = page.extract_tables() or []
                for table in tables:
                    if not table:
                        continue
                    self._process_table_rows(table, page_index, "pdfplumber", entries, seen_codes)

        # Fallback con Camelot per tabelle che pdfplumber non rileva
        if entries:
            return entries

        try:
            import camelot
        except ImportError:
            return entries

        def process_tables(tables, flavor_name: str):
            nonlocal entries, seen_codes
            for tbl in tables:
                try:
                    df = tbl.df
                except Exception:
                    continue
                self._process_table_rows(df.values.tolist(), None, f"camelot-{flavor_name}", entries, seen_codes)

        try:
            tables_lattice = camelot.read_pdf(pdf_path, pages="all", flavor="lattice")
        except Exception:
            tables_lattice = []
        process_tables(tables_lattice, "lattice")

        try:
            tables_stream = camelot.read_pdf(pdf_path, pages="all", flavor="stream")
        except Exception:
            tables_stream = []
        process_tables(tables_stream, "stream")

        return entries

    def parse_master_list(self, pdf_path: str) -> List[str]:
        """
        Estrae tutti i codici documentali dal PDF "Elenco Documenti"

        Args:
            pdf_path: Percorso al file PDF dell'elenco documenti

        Returns:
            Lista di codici documentali normalizzati
        """
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF master list non trovato: {pdf_path}")

        try:
            codes = set()

            doc = fitz.open(pdf_path)

            # Scansiona tutto il documento
            for page_num in range(len(doc)):
                page = doc[page_num]
                text = page.get_text()

                # Trova tutte le righe che corrispondono al pattern
                matches = re.finditer(self.TABLE_ROW_PATTERN, text)

                for match in matches:
                    lotto = match.group(1)
                    capitolo = match.group(2)
                    paragrafo = match.group(3)
                    tipologia = match.group(4)
                    disciplina = match.group(5)
                    progressivo = match.group(6)
                    revisione = match.group(7)

                    # Costruisci il codice normalizzato
                    code = f"ADRPMV{lotto}-PE{capitolo}{paragrafo}-{tipologia}{disciplina}{progressivo}-{revisione}"
                    codes.add(code)

            doc.close()

            return sorted(list(codes))

        except Exception as e:
            print(f"Errore durante il parsing del PDF master list: {str(e)}")
            raise

    def validate_master_list(self, pdf_path: str) -> dict:
        """
        Valida il PDF master list e restituisce statistiche

        Args:
            pdf_path: Percorso al file PDF

        Returns:
            Dizionario con statistiche sulla lista master
        """
        try:
            codes = self.parse_master_list(pdf_path)

            return {
                'total_documents': len(codes),
                'codes': codes
            }

        except Exception as e:
            return {
                'error': str(e),
                'total_documents': 0
            }

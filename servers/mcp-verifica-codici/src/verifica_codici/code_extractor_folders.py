"""
Modulo per estrarre codici identificativi da PDF usando un modello VLM (Ollama).
Questo modulo lavora direttamente con cartelle di PDF.
"""

import os
import sys
import time
import base64
import json
from io import BytesIO
from typing import Optional, Dict
from pdf2image import convert_from_path
from PIL import Image, ImageOps, ImageEnhance
import re
import requests

USE_OLLAMA_VLM = os.getenv("USE_OLLAMA_VLM", "true").lower() == "true"
OLLAMA_BASE_URL = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434").rstrip("/")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "60"))
OLLAMA_VLM_MODEL = os.getenv("OLLAMA_VLM_MODEL", "qwen3-vl:4b")


class FolderCodeExtractor:
    """Estrattore di codici documentali da cartelle di PDF usando un modello VLM"""

    # Pattern per il codice: es. ADRPMV02--PEDSIIE--RRC00-1
    CODE_REGEX = re.compile(r'^[A-Z]{6}\d{2}-[A-Z]{4,12}-[A-Z]{2,5}\d{2}-\d$')
    CODE_IN_TEXT_REGEX = re.compile(r'([A-Z]{6}\d{2})-([A-Z]{4,12})-([A-Z]{3,5}\d{2})-(\d)')
    SEGMENT_PATTERNS = (
        re.compile(r"^[A-Z]{6}\d{2}$"),
        re.compile(r"^[A-Z]{4,12}$"),
        re.compile(r"^[A-Z]{3,5}\d{2}$"),
        re.compile(r"^\d$"),
    )

    def __init__(self):
        """Inizializza l'estrattore"""
        pass

    def extract_from_pdf(self, pdf_path: str) -> Optional[str]:
        """
        Estrae il codice identificativo dalla prima pagina del PDF usando Ollama VLM

        Args:
            pdf_path: Percorso al file PDF

        Returns:
            Codice identificativo normalizzato o None se non trovato
        """
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF non trovato: {pdf_path}")

        try:
            crop_box_env = os.getenv("CODE_CROP_BOX")
            if crop_box_env:
                try:
                    crop_box = tuple(float(v.strip()) for v in crop_box_env.split(","))
                    if len(crop_box) != 4:
                        raise ValueError
                except ValueError:
                    print(f"[WARN] Invalid CODE_CROP_BOX value '{crop_box_env}', falling back to default.", file=sys.stderr, flush=True)
                    crop_box = (28.32, 591.36, 516.96, 625.44)
            else:
                crop_box = (28.32, 591.36, 516.96, 625.44)

            cropped_image = None
            try:
                import pdfplumber
                with pdfplumber.open(pdf_path) as pdf:
                    page = pdf.pages[0]
                    table = page.crop(crop_box)
                    crop_resolution = int(os.getenv("CODE_CROP_RESOLUTION", "500"))
                    pil_crop = table.to_image(resolution=crop_resolution).original
                    cropped_image = pil_crop
                    print(f"[DEBUG] Cropped region size: {cropped_image.size}", file=sys.stderr, flush=True)
            except Exception as crop_err:
                print(f"[WARN] Failed to crop code region: {crop_err}", file=sys.stderr, flush=True)

            convert_start = time.perf_counter()
            print(f"[DEBUG] convert_from_path start -> {pdf_path}", file=sys.stderr, flush=True)
            pdf_render_dpi = int(os.getenv("PDF_RENDER_DPI", "200"))
            images = convert_from_path(
                pdf_path,
                first_page=1,
                last_page=1,
                dpi=pdf_render_dpi
            )
            print(f"[DEBUG] convert_from_path done in {time.perf_counter() - convert_start:.2f}s", file=sys.stderr, flush=True)

            full_page_image = images[0] if images else None
            if full_page_image is None and cropped_image is None:
                return None

            if USE_OLLAMA_VLM:
                cropped = cropped_image
                full = full_page_image
                images_to_try = []
                if cropped is not None:
                    images_to_try.append(("crop", cropped))
                if full is not None:
                    images_to_try.append(("full", full))
                for variant_name, image_candidate in images_to_try:
                    if image_candidate is None:
                        continue
                    print(f"[DEBUG] Ollama VLM extraction start ({variant_name})", file=sys.stderr, flush=True)
                    vlm_start = time.perf_counter()
                    code_vlm = self.extract_code_with_vlm(image_candidate)
                    duration = time.perf_counter() - vlm_start
                    print(f"[DEBUG] Ollama VLM extraction end in {duration:.2f}s (variant={variant_name}, code={code_vlm})", file=sys.stderr, flush=True)
                    if code_vlm:
                        return code_vlm

            return None

        except Exception as e:
            print(f"Errore durante l'estrazione da {pdf_path}: {str(e)}", file=sys.stderr, flush=True)
            return None

    def normalize_code(self, code: str) -> str:
        """
        Normalizza il formato del codice

        Args:
            code: Codice grezzo estratto

        Returns:
            Codice normalizzato nel formato: ADRPMV02-PEDSIIE-RRC00-1
        """
        # Rimuovi tutti gli spazi
        code = re.sub(r'\s+', '', code)

        # Sostituisci tutti i tipi di dash con un singolo trattino
        code = re.sub(r'[-–—]+', '-', code)

        # Converti in maiuscolo
        code = code.upper()

        return code

    @staticmethod
    def _fix_digits(text: str) -> str:
        digit_map = {"O": "0", "I": "1", "L": "1"}
        return "".join(digit_map.get(ch, ch) for ch in text)

    def _normalize_segment(self, part: str, idx: int) -> Optional[str]:
        token = (part or "").strip().upper()
        token = token.replace(" ", "")
        token = re.sub(r"[-–—]+", "", token)
        token = re.sub(r"[^A-Z0-9]", "", token)
        if idx == 0 and len(token) >= 2:
            token = token[:-2] + self._fix_digits(token[-2:])
        elif idx == 1:
            token = token.replace("0", "O").replace("1", "I")
        elif idx == 2 and len(token) >= 2:
            token = token[:-2] + self._fix_digits(token[-2:])
        elif idx == 3:
            token = self._fix_digits(token)
        pattern = self.SEGMENT_PATTERNS[idx]
        return token if pattern.match(token) else None

    def parse_code_from_text(self, raw_text: Optional[str]) -> Optional[str]:
        """Estrae e normalizza un codice completo da una stringa arbitraria."""
        if not raw_text:
            return None

        normalized = self.normalize_code(raw_text)
        normalized = re.sub(r"[^A-Z0-9-]", "", normalized)

        parts = [p for p in normalized.split("-") if p]
        if len(parts) >= 4:
            cleaned_parts = []
            for idx in range(4):
                normalized_part = self._normalize_segment(parts[idx], idx)
                if not normalized_part:
                    break
                cleaned_parts.append(normalized_part)
            if len(cleaned_parts) == 4:
                candidate = "-".join(cleaned_parts)
                if self.validate_code_format(candidate):
                    return candidate

        normalized = normalized.replace("--", "-")
        match = self.CODE_IN_TEXT_REGEX.search(normalized)
        if match:
            candidate = "-".join(match.groups())
            if self.validate_code_format(candidate):
                return candidate

        return None

    def extract_from_folder(self, folder_path: str, recursive: bool = False) -> Dict[str, Optional[str]]:
        """
        Estrae codici da tutti i PDF in una cartella

        Args:
            folder_path: Percorso alla cartella
            recursive: Se True, cerca anche nelle sottocartelle

        Returns:
            Dizionario {nome_file: codice} dove codice può essere None se l'estrazione fallisce
        """
        if not os.path.exists(folder_path):
            raise FileNotFoundError(f"Cartella non trovata: {folder_path}")

        results = {}

        if recursive:
            # Scansione ricorsiva
            for root, _, files in os.walk(folder_path):
                for filename in files:
                    if filename.lower().endswith('.pdf'):
                        pdf_path = os.path.join(root, filename)
                        relative_path = os.path.relpath(pdf_path, folder_path)
                        try:
                            code = self.extract_from_pdf(pdf_path)
                            results[relative_path] = code
                        except Exception as e:
                            print(f"Errore nell'elaborazione di {relative_path}: {str(e)}", file=sys.stderr, flush=True)
                            results[relative_path] = None
        else:
            # Scansione solo nella cartella corrente
            pdf_files = [f for f in os.listdir(folder_path) if f.lower().endswith('.pdf')]
            total_files = len(pdf_files)
            print(f"[INFO] Trovati {total_files} file PDF da processare", file=sys.stderr, flush=True)

            for idx, filename in enumerate(pdf_files, 1):
                pdf_path = os.path.join(folder_path, filename)

                # Salta sottocartelle
                if os.path.isdir(pdf_path):
                    continue

                try:
                    print(f"[INFO] Processando {idx}/{total_files}: {filename}...", file=sys.stderr, flush=True)
                    code = self.extract_from_pdf(pdf_path)
                    results[filename] = code
                    print(f"[INFO] ✓ {filename}: {code if code else 'NESSUN_CODICE'}", file=sys.stderr, flush=True)
                except Exception as e:
                    print(f"[ERROR] Errore nell'elaborazione di {filename}: {str(e)}", file=sys.stderr, flush=True)
                    results[filename] = None

        return results

    def validate_code_format(self, code: str) -> bool:
        """
        Valida il formato di un codice

        Args:
            code: Codice da validare

        Returns:
            True se il codice ha un formato valido
        """
        return bool(self.CODE_REGEX.fullmatch(code))

    def extract_code_with_vlm(self, image) -> Optional[str]:
        """
        Usa un modello VLM servito da Ollama per estrarre il codice dall'immagine.
        Restituisce il codice normalizzato oppure None in caso di fallimento.
        """
        try:
            pil_image = image.convert("RGB") if isinstance(image, Image.Image) else Image.fromarray(image)
            pil_image = ImageOps.autocontrast(pil_image.convert("L"))
            pil_image = ImageEnhance.Contrast(pil_image).enhance(1.6)
            pil_image = ImageEnhance.Sharpness(pil_image).enhance(1.2).convert("RGB")

            resample_filter = getattr(getattr(Image, "Resampling", Image), "LANCZOS", Image.BICUBIC)

            min_height_to_magnify = int(os.getenv("OLLAMA_MIN_HEIGHT_TO_MAGNIFY", "220"))
            target_magnify_height = int(os.getenv("OLLAMA_TARGET_HEIGHT", "520"))
            if pil_image.height < min_height_to_magnify:
                scale = target_magnify_height / max(pil_image.height, 1)
                new_width = max(int(pil_image.width * scale), 1)
                pil_image = pil_image.resize((new_width, target_magnify_height), resample_filter)
                print(f"[DEBUG] Magnified image for VLM to {pil_image.size}", file=sys.stderr, flush=True)

            max_dim = int(os.getenv("OLLAMA_IMAGE_MAX_DIM", "1600"))
            min_height_to_resize = int(os.getenv("OLLAMA_MIN_HEIGHT_TO_RESIZE", "260"))
            if max_dim > 0:
                if pil_image.height > max_dim:
                    if pil_image.height >= min_height_to_resize:
                        pil_image.thumbnail((max_dim, max_dim), resample_filter)
                        print(f"[DEBUG] Resized image for VLM to {pil_image.size}", file=sys.stderr, flush=True)
                    else:
                        print(f"[DEBUG] Skipping downscale (height {pil_image.height} < {min_height_to_resize})", file=sys.stderr, flush=True)
                elif pil_image.width > max_dim:
                    print(
                        f"[DEBUG] Keeping wide aspect ({pil_image.width}x{pil_image.height}) despite max_dim={max_dim}",
                        file=sys.stderr,
                        flush=True,
                    )
            buffer = BytesIO()
            pil_image.save(buffer, format="PNG")
            encoded_image = base64.b64encode(buffer.getvalue()).decode("utf-8")

            prompts = [
                (
                    "/no_think\n"
                    "Individua l'intera riga della tabella etichettata 'CODICE IDENTIFICATIVO'. "
                    "Copia tutti i caratteri, cella per cella, nell'ordine da sinistra a destra. "
                    "Restituisci: \n"
                    "- 'code_line': stringa completa con trattini singoli tra le sezioni.\n"
                    "- 'code': stessa stringa ma con le 4 sezioni unite da un solo '-'.\n"
                    "- 'segments': [commessa, parte_opera, progressivo, revisione] rispettando i formati (commessa=6 lettere+2 cifre, parte_opera=solo lettere, progressivo=2-5 lettere + 2 cifre, revisione=singola cifra).\n"
                    "- 'characters': array dove ogni elemento è UN solo carattere (lettera, numero o trattino) copiato esattamente dalla riga (nessun carattere deve mancare, includi anche la prima lettera)."
                ),
                (
                    "/no_think\n"
                    "Ricontrolla la stessa riga: non saltare lettere iniziali (es. deve comparire anche la prima 'A'), mantieni tutte le sequenze 'EEP', e rappresenta serie di trattini consecutivi come singoli '-' nella chiave 'code'. "
                    "Verifica che il contatore totale dei caratteri in 'characters' corrisponda alla riga originale. "
                    "Restituisci nuovamente JSON con 'code_line', 'code', 'segments' e 'characters'."
                )
            ]

            format_schema = {
                "type": "object",
                "properties": {
                    "code_line": {"type": "string"},
                    "code": {"type": "string"},
                    "segments": {
                        "type": "array",
                        "items": {"type": "string"}
                    },
                    "characters": {
                        "type": "array",
                        "items": {"type": "string"}
                    }
                },
                "required": ["code_line"]
            }

            def call_vlm(prompt_text: str) -> Optional[list[str]]:
                payload = {
                    "model": OLLAMA_VLM_MODEL,
                    "prompt": prompt_text,
                    "images": [encoded_image],
                    "format": format_schema,
                    "stream": False,
                    "options": {
                        "temperature": 0.0,
                    }
                }
                response = requests.post(
                    f"{OLLAMA_BASE_URL}/api/generate",
                    json=payload,
                    timeout=OLLAMA_TIMEOUT,
                )
                if not response.ok:
                    error_text = response.text
                    raise RuntimeError(f"Ollama error {response.status_code}: {error_text}")
                data = response.json()
                structured = None
                if isinstance(data, dict):
                    structured = data.get("response") or data.get("thinking") or ""
                print(f"[DEBUG] VLM raw structured data -> {structured}", file=sys.stderr, flush=True)

                parsed: Dict[str, object] = {}
                if isinstance(structured, dict):
                    parsed = structured
                elif isinstance(structured, str):
                    try:
                        parsed = json.loads(structured)
                    except json.JSONDecodeError:
                        parsed = {}

                segments = parsed.get("segments") if isinstance(parsed, dict) else None
                cleaned_parts: Optional[list[str]] = None
                if isinstance(segments, list) and len(segments) == 4:
                    temp_parts = []
                    valid = True
                    for idx, part in enumerate(segments):
                        if not isinstance(part, str):
                            valid = False
                            break
                        token = self._normalize_segment(part, idx)
                        if not token:
                            valid = False
                            break
                        temp_parts.append(token)
                    if valid:
                        cleaned_parts = temp_parts

                candidates = []
                if cleaned_parts:
                    candidates.append("-".join(cleaned_parts))

                code_field = parsed.get("code") if isinstance(parsed, dict) else None
                if isinstance(code_field, str):
                    candidates.append(code_field)

                characters_field = parsed.get("characters") if isinstance(parsed, dict) else None
                if isinstance(characters_field, list):
                    char_sequence = "".join(ch for ch in characters_field if isinstance(ch, str))
                    if char_sequence:
                        candidates.append(char_sequence)

                code_line = parsed.get("code_line") if isinstance(parsed, dict) else None
                if isinstance(code_line, str):
                    candidates.append(code_line)

                if isinstance(structured, str):
                    candidates.append(structured)

                for candidate in candidates:
                    parsed_code = self.parse_code_from_text(candidate)
                    if parsed_code:
                        return parsed_code.split("-")

                return None

            for attempt, prompt_text in enumerate(prompts, start=1):
                segments = call_vlm(prompt_text)
                if not segments:
                    continue
                cleaned = "-".join(segments)
                print(f"[DEBUG] Structured code candidate -> {cleaned}", file=sys.stderr, flush=True)
                normalized = self.parse_code_from_text(cleaned)
                if normalized:
                    return normalized

            return None

        except Exception as exc:
            print(f"[WARN] Ollama VLM extraction failed: {exc}", file=sys.stderr, flush=True)
            return None

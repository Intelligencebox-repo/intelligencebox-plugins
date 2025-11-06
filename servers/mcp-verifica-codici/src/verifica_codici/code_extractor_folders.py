"""
Modulo per estrarre codici identificativi da PDF usando un modello VLM (Ollama).
Questo modulo lavora direttamente con cartelle di PDF.
"""

import os
import sys
import time
import base64
from io import BytesIO
from typing import Optional, Dict
from pdf2image import convert_from_path
import re
import requests

USE_OLLAMA_VLM = os.getenv("USE_OLLAMA_VLM", "true").lower() == "true"
OLLAMA_BASE_URL = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434").rstrip("/")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "60"))
OLLAMA_VLM_MODEL = os.getenv("OLLAMA_VLM_MODEL", "qwen3-vl:4b")


class FolderCodeExtractor:
    """Estrattore di codici documentali da cartelle di PDF usando un modello VLM"""

    # Pattern per il codice: es. ADRPMV02--PEDSIIE--RRC00-1
    CODE_PATTERN = r'[A-Z]{6}\d{2}\s*[-–—]+\s*[A-Z]{2}[A-Z]{2}[A-Z]{2,4}\s*[-–—]+\s*[A-Z]{1,3}\d{2}\s*[-–—]+\s*\d'

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
            # Converti la prima pagina in immagine
            convert_start = time.perf_counter()
            print(f"[DEBUG] convert_from_path start -> {pdf_path}", file=sys.stderr, flush=True)
            # Using 150 DPI for faster processing while maintaining OCR accuracy
            images = convert_from_path(
                pdf_path,
                first_page=1,
                last_page=1,
                dpi=150
            )
            print(f"[DEBUG] convert_from_path done in {time.perf_counter() - convert_start:.2f}s", file=sys.stderr, flush=True)

            if not images:
                return None

            # Usa direttamente il modello VLM
            if USE_OLLAMA_VLM:
                print("[DEBUG] Ollama VLM extraction start", file=sys.stderr, flush=True)
                vlm_start = time.perf_counter()
                code_vlm = self.extract_code_with_vlm(images[0])
                print(f"[DEBUG] Ollama VLM extraction end in {time.perf_counter() - vlm_start:.2f}s (code={code_vlm})", file=sys.stderr, flush=True)
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
        pattern = r'^[A-Z]{6}\d{2}-[A-Z]{2}[A-Z]{2}[A-Z]{2,4}-[A-Z]{1,3}\d{2}-\d$'
        return bool(re.match(pattern, code))

    def extract_code_with_vlm(self, image) -> Optional[str]:
        """
        Usa un modello VLM servito da Ollama per estrarre il codice dall'immagine.
        Restituisce il codice normalizzato oppure None in caso di fallimento.
        """
        try:
            from PIL import Image
            pil_image = image.convert("RGB") if isinstance(image, Image.Image) else Image.fromarray(image)
            buffer = BytesIO()
            pil_image.save(buffer, format="PNG")
            encoded_image = base64.b64encode(buffer.getvalue()).decode("utf-8")

            prompt = (
                "Extract the document identification code shown in this image. "
                "The code typically looks like ADRPMV02-PEDSIIE-RRC00-1. "
                "Reply with the code only. If no code is visible, reply with NONE."
            )

            payload = {
                "model": OLLAMA_VLM_MODEL,
                "prompt": prompt,
                "images": [encoded_image],
                "stream": False,
                "options": {
                    "temperature": 0.0
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
            content = data.get("response", "") if isinstance(data, dict) else ""

            match = re.search(self.CODE_PATTERN, content, re.IGNORECASE)
            if match:
                return self.normalize_code(match.group(0))

            if content.strip().upper() == "NONE":
                return None

            # As fallback try to normalize entire response
            cleaned = content.strip()
            if cleaned:
                normalized = self.normalize_code(cleaned)
                if self.validate_code_format(normalized):
                    return normalized

            return None

        except Exception as exc:
            print(f"[WARN] Ollama VLM extraction failed: {exc}", file=sys.stderr, flush=True)
            return None

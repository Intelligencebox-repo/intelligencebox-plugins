"""
Modulo per estrarre codici identificativi da PDF usando PaddleOCR.
Questo modulo lavora direttamente con cartelle di PDF.
"""

import os
from typing import Optional, Dict
from pdf2image import convert_from_path
import re
from paddleocr import PaddleOCR

# OCR instance will be lazy-loaded on first use
_ocr_instance = None


def get_ocr():
    """Get or create the global PaddleOCR instance (lazy loading)"""
    global _ocr_instance
    if _ocr_instance is None:
        print("🔧 Initializing PaddleOCR (this may take a moment)...")
        _ocr_instance = PaddleOCR(lang='en', use_angle_cls=True)
        print("✓ PaddleOCR initialized successfully")
    return _ocr_instance


class FolderCodeExtractor:
    """Estrattore di codici document

ali da cartelle di PDF usando PaddleOCR"""

    # Pattern per il codice: es. ADRPMV02--PEDSIIE--RRC00-1
    CODE_PATTERN = r'[A-Z]{6}\d{2}\s*[-–—]+\s*[A-Z]{2}[A-Z]{2}[A-Z]{2,4}\s*[-–—]+\s*[A-Z]{1,3}\d{2}\s*[-–—]+\s*\d'

    def __init__(self):
        """Inizializza l'estrattore"""
        self.ocr = None  # Will be lazy-loaded on first use

    @property
    def _ocr(self):
        """Lazy load OCR instance when first accessed"""
        if self.ocr is None:
            self.ocr = get_ocr()
        return self.ocr

    def extract_from_pdf(self, pdf_path: str) -> Optional[str]:
        """
        Estrae il codice identificativo dalla prima pagina del PDF usando PaddleOCR

        Args:
            pdf_path: Percorso al file PDF

        Returns:
            Codice identificativo normalizzato o None se non trovato
        """
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF non trovato: {pdf_path}")

        try:
            # Converti la prima pagina in immagine
            images = convert_from_path(
                pdf_path,
                first_page=1,
                last_page=1,
                dpi=300
            )

            if not images:
                return None

            # Converti in numpy array per PaddleOCR
            import numpy as np
            import cv2
            from PIL import Image

            # Converti PIL image to numpy array
            img_array = np.array(images[0])

            # Se è RGB, convertilo in BGR per OpenCV
            if len(img_array.shape) == 3 and img_array.shape[2] == 3:
                img_bgr = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
            else:
                img_bgr = img_array

            # Esegui OCR
            result = self._ocr.ocr(img_bgr)

            if not result or not result[0]:
                return None

            # Estrai tutto il testo
            all_text = []
            for line in result[0]:
                text, conf = line[1]
                if text.strip() and conf > 0.5:  # Confidence threshold
                    all_text.append(text.strip())

            # Unisci tutto il testo
            full_text = " ".join(all_text)

            # Cerca il pattern del codice
            matches = re.findall(self.CODE_PATTERN, full_text, re.IGNORECASE)

            if matches:
                return self.normalize_code(matches[0])

            return None

        except Exception as e:
            print(f"Errore durante l'estrazione da {pdf_path}: {str(e)}")
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
                            print(f"Errore nell'elaborazione di {relative_path}: {str(e)}")
                            results[relative_path] = None
        else:
            # Scansione solo nella cartella corrente
            for filename in os.listdir(folder_path):
                if not filename.lower().endswith('.pdf'):
                    continue

                pdf_path = os.path.join(folder_path, filename)

                # Salta sottocartelle
                if os.path.isdir(pdf_path):
                    continue

                try:
                    code = self.extract_from_pdf(pdf_path)
                    results[filename] = code
                except Exception as e:
                    print(f"Errore nell'elaborazione di {filename}: {str(e)}")
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

"""
Modulo per estrarre l'elenco dei codici documentali attesi dal PDF "Elenco Documenti".
"""

import re
import os
from typing import List
import fitz  # PyMuPDF
from .code_extractor_folders import translate_docker_path


class MasterListParser:
    """Parser per estrarre l'elenco completo dei codici documentali dal PDF master"""

    # Pattern per riga della tabella: ADRPMV 02 PE DG GEN - - E ED 00 1
    TABLE_ROW_PATTERN = r'ADRPMV\s+(\d{2})\s+PE\s+([A-Z]{2})\s+([A-Z]{2,4})\s+[-–]\s+[-–]\s+([A-Z])\s+([A-Z]{2,3})\s+(\d{2})\s+(\d)'

    def __init__(self):
        """Inizializza il parser"""
        pass

    def parse_master_list(self, pdf_path: str) -> List[str]:
        """
        Estrae tutti i codici documentali dal PDF "Elenco Documenti"

        Args:
            pdf_path: Percorso al file PDF dell'elenco documenti

        Returns:
            Lista di codici documentali normalizzati
        """
        # Traduci il path Docker in path host reale
        pdf_path = translate_docker_path(pdf_path)
        print(f"[parse_master_list] Translated path: {pdf_path}")

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

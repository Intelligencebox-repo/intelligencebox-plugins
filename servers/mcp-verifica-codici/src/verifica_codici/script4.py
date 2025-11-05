from paddleocr import PaddleOCR
import logging
import re

# Configura il logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- INIZIALIZZAZIONE DEL MODELLO PADDLEOCR ---
logger.info("Caricamento del modello PaddleOCR in memoria...")
try:
    # Usiamo 'en' (inglese) per codici alfanumerici.
    # Disabilitiamo il classificatore di angoli e i log di Paddle.
    ocr_engine = PaddleOCR(lang='en', use_angle_cls=False, show_log=False)
    logger.info("Modulo script4.py caricato. Motore PaddleOCR inizializzato.")
except Exception as e:
    logger.critical(f"ERRORE CRITICO: Impossibile inizializzare PaddleOCR: {e}")
    ocr_engine = None


def estrai_codice_immagine(immagine_opencv):
    """
    Esegue l'OCR con PaddleOCR su un'immagine fornita in formato OpenCV.

    Args:
        immagine_opencv (numpy.ndarray): I dati dell'immagine pulita.

    Returns:
        str: La stringa di testo estratta dall'immagine.
    """
    logger.info("--- Avvio Step 4: Estrazione Codice con PaddleOCR ---")
    
    if ocr_engine is None:
        logger.error("ERRORE: Motore PaddleOCR non inizializzato.")
        return "ERRORE_OCR_INIT"

    try:
        # 1. Esegui l'OCR
        result = ocr_engine.ocr(immagine_opencv, cls=False)
        
        # 2. Estrai e formatta il testo
        # PaddleOCR restituisce: [ [[box], ('testo', conf)], ... ]
        if result and result[0]:
            # Estrai solo il testo da ogni rilevamento e uniscilo
            text_parts = [line[1][0] for line in result[0]]
            testo_estratto_raw = " ".join(text_parts)
        else:
            testo_estratto_raw = ""

        logger.info(f"Testo grezzo estratto da PaddleOCR: '{testo_estratto_raw}'")
        
        # 3. Pulizia finale (rimuove spazi, normalizza trattini)
        testo_pulito = re.sub(r'[\s\n\r]+', '', testo_estratto_raw)
        testo_normalizzato = re.sub(r'-+', '-', testo_pulito).strip('-').strip()
        
        logger.info(f"Testo pulito restituito: '{testo_normalizzato}'")
        return testo_normalizzato

    except Exception as e:
        logger.error(f"ERRORE durante l'esecuzione di PaddleOCR: {e}")
        return "ERRORE_OCR"
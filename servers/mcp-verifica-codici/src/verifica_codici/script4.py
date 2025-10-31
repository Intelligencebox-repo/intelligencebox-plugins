import pytesseract
from PIL import Image
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    # Prova a ottenere e loggare la versione di Tesseract installata
    tesseract_version = pytesseract.get_tesseract_version()
    logger.info(f"Modulo script4.py caricato. Versione Tesseract trovata: {tesseract_version}")
except pytesseract.TesseractNotFoundError:
    # Se Tesseract non è installato nel Dockerfile
    logger.error("="*50)
    logger.error("ERRORE CRITICO: Tesseract non è stato trovato nel PATH del container.")
    logger.error("Controllare che 'tesseract-ocr' sia installato nel Dockerfile.")
    logger.error("="*50)
except Exception as e:
    logger.error(f"Errore sconosciuto durante l'inizializzazione di Tesseract: {e}")


def estrai_codice_immagine(immagine_opencv):
    """
    Esegue l'OCR con Tesseract su un'immagine fornita in formato OpenCV.

    Args:
        immagine_opencv (numpy.ndarray): I dati dell'immagine pulita.

    Returns:
        str: La stringa di testo estratta dall'immagine.
    """
    # Configurazioni per Tesseract
    TESSERACT_CONFIG = '--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-'

    logger.info(f"Configurazione Tesseract utilizzata: {TESSERACT_CONFIG}")

    try:
        # Esegui l'OCR direttamente sull'oggetto immagine OpenCV
        testo_estratto = pytesseract.image_to_string(immagine_opencv, config=TESSERACT_CONFIG)
        logger.info(f"Testo estratto da Tesseract: {testo_estratto}")

        # Restituisce il testo estratto, pulito da eventuali spazi bianchi iniziali/finali
        return testo_estratto.strip()

    except Exception as e:
        print(f"\n[!] ERRORE durante l'esecuzione di Tesseract: {e}")
        return "ERRORE_OCR"
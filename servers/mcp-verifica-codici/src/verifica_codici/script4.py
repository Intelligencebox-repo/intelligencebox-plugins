import pytesseract
from PIL import Image

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

    try:
        # Esegui l'OCR direttamente sull'oggetto immagine OpenCV
        testo_estratto = pytesseract.image_to_string(immagine_opencv, config=TESSERACT_CONFIG)
        
        # Restituisce il testo estratto, pulito da eventuali spazi bianchi iniziali/finali
        return testo_estratto.strip()

    except Exception as e:
        print(f"\n[!] ERRORE durante l'esecuzione di Tesseract: {e}")
        return "ERRORE_OCR"
import cv2
from .code_extractor_folders import FolderCodeExtractor

_folder_extractor = FolderCodeExtractor()

def estrai_codice_immagine(img):
    """
    Versione aggiornata: utilizza il modello VLM di Ollama invece di PaddleOCR.
    """
    try:
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        codice = _folder_extractor.extract_code_with_vlm(img_rgb)

        if codice:
            print(f"   [DEBUG] Codice estratto via VLM: '{codice}'")
            return codice

        print("   [!] Nessun codice riconosciuto dal modello VLM.")
        return "ERRORE_OCR"

    except Exception as e:
        print(f"[!] Errore in estrai_codice_immagine con VLM: {e}")
        return "ERRORE_OCR"

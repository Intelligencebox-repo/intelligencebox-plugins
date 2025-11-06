from paddleocr import PaddleOCR
import cv2

ocr = PaddleOCR(lang='en', use_angle_cls=True)

def estrai_codice_immagine(img):
    """
    Versione con debug: stampa tutto ciò che PaddleOCR trova.
    """
    try:
        # PaddleOCR si aspetta immagini RGB (non BGR come OpenCV)
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

        result = ocr.ocr(img_rgb)
        if not result or not result[0]:
            print("   [!] Nessun testo riconosciuto.")
            return "ERRORE_OCR"

        print("   [DEBUG] Testi trovati:")
        testi = []
        for line in result[0]:
            text, conf = line[1]
            print(f"      -> '{text}'  (conf={conf:.2f})")
            if text.strip():
                testi.append(text.strip())

        if not testi:
            return "ERRORE_OCR"

        # Prende il testo più lungo
        codice = max(testi, key=len)
        codice = codice.replace(" ", "").replace("\n", "")

        print(f"   [DEBUG] Codice scelto: '{codice}'")
        return codice if codice else "ERRORE_OCR"

    except Exception as e:
        print(f"[!] Errore in estrai_codice_immagine: {e}")
        return "ERRORE_OCR"
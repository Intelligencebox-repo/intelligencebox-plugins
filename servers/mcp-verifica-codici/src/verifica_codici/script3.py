import pdfplumber
import cv2
import numpy as np

def genera_immagine_pulita(percorso_file):
    """
    Apre un file PDF, ritaglia un'area specifica, la pulisce dalle linee
    e restituisce i dati dell'immagine pulita e migliorata.

    Args:
        percorso_file (str): Il percorso del file PDF da analizzare.

    Returns:
        numpy.ndarray: I dati dell'immagine pulita in formato OpenCV, pronti per l'OCR.
                       Restituisce None in caso di errore.
    """
    # Definisce la zona del pdf che verrà ritagliata
    crop_box = (28.32, 591.36, 516.96, 625.44)

    try:
        with pdfplumber.open(percorso_file) as pdf:
            pagina_uno = pdf.pages[0]
            tabella_ritagliata = pagina_uno.crop(crop_box)
            immagine_tabella = tabella_ritagliata.to_image(resolution=300)
            
            # --- Pre-processing con OpenCV ---
            # 1. Converte l'immagine da formato PIL (usato da pdfplumber) a formato OpenCV
            img_cv = cv2.cvtColor(np.array(immagine_tabella.original), cv2.COLOR_RGB2BGR)
            # 2. Converte in scala di grigi e poi in bianco e nero puro
            gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
            thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]

            # 3. Rileva e rimuove le linee verticali
            vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1,40))
            remove_vertical = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, vertical_kernel, iterations=2)
            cnts = cv2.findContours(remove_vertical, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cnts = cnts[0] if len(cnts) == 2 else cnts[1]
            for c in cnts:
                cv2.drawContours(img_cv, [c], -1, (255,255,255), 15) # Disegna linee bianche spesse sopra le linee verticali

            # 4. Rileva e rimuove le linee orizzontali
            horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (40,1))
            remove_horizontal = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, horizontal_kernel, iterations=2)
            cnts = cv2.findContours(remove_horizontal, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cnts = cnts[0] if len(cnts) == 2 else cnts[1]
            for c in cnts:
                cv2.drawContours(img_cv, [c], -1, (255,255,255), 5)
            
            # 5. Migliora il testo tramite dilatazione lettere
            # 5.1 Riconverte l'immagine pulita in B/N, ma stavolta invertita (testo bianco, sfondo nero)
            gray_clean = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
            thresh_inverted = cv2.threshold(gray_clean, 200, 255, cv2.THRESH_BINARY_INV)[1]
            # 5.2 Applica la dilatazione per inspessire il testo (che ora è bianco)
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2,2))
            dilated_image = cv2.dilate(thresh_inverted, kernel, iterations=1)
            # 5.3 Inverte di nuovo l'immagine per tornare a testo nero su sfondo bianco
            final_image = cv2.bitwise_not(dilated_image)

            # --- PASSAGGIO 6: SMOOTHING DEI BORDI ---
            # Applica una leggera sfocatura Gaussiana per ammorbidire i bordi.
            # (2,2) è la dimensione del kernel di sfocatura: più è grande, più l'effetto è forte.
            smoothed_image = cv2.GaussianBlur(final_image, (3,3), 0)

            return smoothed_image
            
    except Exception:
        return None
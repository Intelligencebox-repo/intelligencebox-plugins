import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def verifica_codici(codice_da_elenco, codice_immagine):
    """
    Confronta i dati attesi di un documento con una stringa di codice estratta.

    Args:
        codice_da_elenco (dict): Il dizionario con i dati originali del documento d'elenco.
        codice_immagine (str): La stringa estratta dalla box partendo dalla foto (es. "ADRPMV02-PEDSIE-RRT00-1").

    Returns:
        dict: Un dizionario con lo stato della verifica ('OK' o 'FAILED') e i dettagli.
    """

    # ---STEP 1: Pulisce il codice estratto dal file d'elenco ---
    # Questi sono i campi che devono essere uniti
    campi_da_unire = [
        'commessa', 'lotto', 'fase', 'capitolo', 'paragrafo', 'WBS',
        'parte d-opera', 'tipologia', 'disciplina', 'progressivo', 'revisione', 'scala'
    ]

    # Pulisce il codice estratto
    codice_completo_elenco = []
    for campo in campi_da_unire:
        valore = str(codice_da_elenco.get(campo, ''))
        # Aggiunge il valore solo se non è un segnaposto vuoto
        if valore not in ['-', '/']:
            codice_completo_elenco.append(valore)

    stringa_codice_completo_elenco = "".join(codice_completo_elenco)


    # --- STEP 2: Pulisce il codice estratto dalla foto ---
    stringa_codice_immagine = codice_immagine.replace('-', '').replace(' ', '')


    # --- STEP 3: Confronta e restituisce il risultato ---
    status = 'OK' # Default
    lunghezza_elenco = len(stringa_codice_completo_elenco)
    lunghezza_immagine = len(stringa_codice_immagine)

    # Controllo preliminare sulla lunghezza
    if lunghezza_elenco != lunghezza_immagine:
        status = 'FAILED'
    else:
        # Confronto carattere per carattere
        for i in range(lunghezza_immagine):
            char_elenco = stringa_codice_completo_elenco[i]
            char_immagine = stringa_codice_immagine[i]

            if char_elenco == char_immagine:
                continue

            # Se sono diversi, controlla se è l'ambiguità O/0
            elif (char_elenco == 'O' and char_immagine == '0') or \
                 (char_elenco == '0' and char_immagine == 'O'):
                continue # Considera O e 0 come uguali

            else:
                status = 'FAILED'
                break

    # Prepara il risultato
    risultato = {
        'titolo_documento': codice_da_elenco.get('titolo'),
        'codice_atteso': stringa_codice_completo_elenco,
        'codice_estratto': stringa_codice_immagine,
        'status': status
    }

    return risultato
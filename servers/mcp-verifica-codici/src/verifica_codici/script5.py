def verifica_codici(codici_da_elenco, codice_immagine):
    """
    Confronta i dati attesi di un documento con una stringa di codice estratta.

    Args:
        codici_da_elenco (dict): Il dizionario con i dati originali del documento d'elenco.
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
        valore = str(codici_da_elenco.get(campo, ''))
        # Aggiunge il valore solo se non è un segnaposto vuoto
        if valore not in ['-', '/']:
            codice_completo_elenco.append(valore)

    stringa_codice_completo_elenco = "".join(codice_completo_elenco)


    # --- STEP 2: Pulisce il codice estratto dalla foto ---
    stringa_codice_immagine = codice_immagine.replace('-', '').replace(' ', '')


    # --- STEP 3: Confronta e restituisce il risultato ---
    # Prepara il dizionario del risultato con una struttura fissa
    risultato = {
        'titolo_documento': codici_da_elenco.get('titolo'),
        'codice_atteso': stringa_codice_completo_elenco,
        'codice_estratto': stringa_codice_immagine,
        'status': 'OK' # Impostato di default su OK
    }

    # Confronta e aggiorna lo status se necessario
    if stringa_codice_completo_elenco != stringa_codice_immagine:
        risultato['status'] = 'FAILED'

    return risultato
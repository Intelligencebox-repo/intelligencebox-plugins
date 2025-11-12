import asyncio

from .recupero_atto import atto_esempio
from .step1 import run_step1
from .step1_3 import run_step1_3
from .step1_4 import run_step1_4
from .step3 import run_step3


# --- FUNZIONE PRINCIPALE DI ORCHESTRAZIONE ---
async def drafting_pipeline(chat_id: str, tipo_atto: str) -> str:
    """
    Orchestra le fasi di analisi e creazione del template per la generazione di una bozza di atto notarile.

    Args:
        chat_id: L'ID della chat in cui avviene la conversazione.
        tipo_atto: Il tipo di atto notarile da generare (es. 'quietanza', 'contratto di compravendita').

    Returns:
        draft_act: Il testo completo della bozza dell'atto generato.
    """
    # --- STEP 0: Recupero Atto d'Esempio ---
    # Contatta la Box cercando di ottenere come risposta un atto d'esempio della tipologia richiesta
    try:
        example_act_text = await atto_esempio(chat_id, tipo_atto)
        if not example_act_text:
            return "Errore: Nessun atto d'esempio trovato nello Step 0."
    except Exception as e:
        return f"Errore durante lo Step 0: {e}"

    # --- STEP 1: Suddivisione Atto d'Esempio ---
    # Prende in input l'intero atto d'esempio e lo suddivide in clausole.
    # Restituisce una lista di dizionari, dove ogni dizionario è composta dalla chiave = il titolo della clausola e dal valore = il testo della clausola
    try:
        clausole, clausole_ruolo = await run_step1(chat_id, example_act_text)
        if not clausole or not clausole_ruolo:
            return "Errore: Nessuna clausola estratta nello Step 1."
    except Exception as e:
        return f"Errore durante lo Step 1: {e}"
    # TODO Quando carico il tool sulla Box per i test, al primo giro mi fermo qua e mi faccio restituire solo clausole_ruolo chiedendo di stamparmele.

    # --- STEP 1.3: Descrizione e scopo ---
    # Analizza ogni clausola e ci genera una descrizione e uno scopo
    # Restituisce una lista di dizionari, dove ogni dizionario è composto dalla chiave = titolo della clausola e dai valori = descrizione e scopo
    try:
        clausole_scopo = await run_step1_3(chat_id, clausole)
        if not clausole_scopo:
            return "Errore: Nessuna clausola elaborata nello Step 1.3."
    except Exception as e:
        return f"Errore durante lo step 1.3: {e}"
    
    # --- STEP 1.4: Creazione template ---
    # Analizza ogni clausola e ne estrae i dati variabili creando una sorta di testo bucato
    # Esempio di output:
    #    {
    #    "titolo": "Dati anagrafici del procuratore (LIGARI SIMONE)",
    #    "testo_template": "[NOME_COMPLETO], nato a [LUOGO_NASCITA] il giorno [DATA_NASCITA], residente a [CITTA_RESIDENZA], [INDIRIZZO_RESIDENZA],",
    #    "dettaglio_variabili": {
    #        "NOME_COMPLETO": "Il nome e cognome completo delprocuratore.",
    #        "LUOGO_NASCITA": "La città o il comune di nascita del procuratore.",
    #        "DATA_NASCITA": "La data di nascita completa, scritta per esteso (es. '6 gennaio 1992') del procuratore.",
    #        "CITTA_RESIDENZA": "La città o il comune di residenza del procuratore.",
    #        "INDIRIZZO_RESIDENZA": "L'indirizzo completo di residenza (inclusi via e numero civico) del procuratore."
    #       }
    #    }
    try:
        templates = await run_step1_4(chat_id, clausole)
        if not templates:
            return "Errore: Nessun template generato nello step 1.4."
    except Exception as e:
        return f"Errore durante lo step 1.4: {e}"


    # --- STEP 3: Confronto delle sezioni con il Caso in Esame ---
    # Prende in input le varie clausole e le analizza singolarmente, cercando di capire se vanno bene cos', sono da modificare o sono da scartare.
    # Restituisce 
    # Prima unisce tutti i dati per comodità
    clausole_complete = []
    for i in range(len(clausole_ruolo)):
        
        dati_base = clausole_ruolo[i]
        dati_scopo = clausole_scopo[i]
        dati_template = templates[i]
        
        clausola_completa = dati_base.copy()
        clausola_completa['descrizione'] = dati_scopo.get('descrizione')
        clausola_completa['scopo'] = dati_scopo.get('scopo')
        clausola_completa['testo_template'] = dati_template.get('testo_template')
        clausola_completa['dettaglio_variabili'] = dati_template.get('dettaglio_variabili')
        
        clausole_complete.append(clausola_completa)

    try:
        step3 = await run_step3(chat_id, clausole_complete)
        if not step3:
            return "Errore: Nessun risultato nello Step 3."
    except Exception as e:
        return f"Errore durante lo Step 3: {e}"
    

    # Restituzione dell'atto
    return "complete_draft"
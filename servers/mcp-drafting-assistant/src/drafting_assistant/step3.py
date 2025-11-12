import asyncio
import json
from typing import List, Dict, Any, Optional

# Importa la funzione per chattare con l'AI
from .chatbox import chat_box


PROMPT_3_1 = """
Sei un assistente di ricerca legale. Il tuo compito è fornirmi informazioni utili alla stesura di un atto notarile.

**CONTESTO**
Devo scrivere un atto notarile. Per farlo ho due fonti dìinformazione: 
1) I dati del caso in esame per cui devo scrivere l'atto;
2) Un atto dello stesso tipo che uso come atto d'esempio.

Sto analizzando l'atto d'esempio clausola per clausola, per decidere se una clausola simile è necessaria anche nel nuovo atto e, in caso affermativo, per capire come popolarla o modificarla in base ai dati specifici del caso in esame.

Ti fornirò la clausola che sto analizzando in questo momento, arricchitta di importanti informazioni.
Tu devi interrogare la tua base di conoscenza tramite RAG e Knowledge Graph per trovare TUTTI i fatti, dati, importi, o passaggi di testo che sono correlati a questa clausola.

**CLAUSOLA D'ESEMPIO E INFORMAZIONI AGGIUNTIVE**
- Nome Clausola: {nome_clausola}
- Testo della clausola: {testo_clausola}
- Descrizione aggiuntiva della clausola: {descrizione}
- Scopo della clausola: {scopo}
- Soggetto Principale (a chi fanno riferimento le informazioni nella clausola): {suggerimento_ruolo}

**ISTRUZIONI AGGIUNTIVE**
- Analizza il caso in esame e trova tutte le informazioni pertinenti a questo concetto.
- Concentrati sulla clausola specifica che ti ho fornito, non preoccuparti del resto. Ti passerò le altre clausole in altre richieste.
- Restituisci **solo ed esclusivamente** un oggetto JSON con questa struttura:
{
  "fatti_recuperati": [
    "testo o fatto 1 recuperato dal caso in esame...",
    "testo o fatto 2 recuperato...",
    "..."
  ]
}
- Se non trovi nulla di rilevante, restituisci una lista vuota così:
{
  "fatti_recuperati": []
}
"""

PROMPT_3_2 = """
Sei un notaio esperto. Il tuo compito è analizzare una clausola di un atto d'esempio e i fatti di un nuovo caso, per poi decidere come procedere.

**CONTESTO**
Sto analizzando una clausola specifica (Contesto 1) presa da un atto d'esempio. Ho recuperato dalla mia base di conoscenza tutti i fatti e i testi ricollegabili dal nuovo caso in esame (Contesto 2).
Ti scrivo queste informazioni qua di seguito:

--- 1. CLAUSOLA D'ESEMPIO (Contesto 1) ---
Analizza questa clausola presa dall'atto d'esempio:
- Nome Clausola: {nome_clausola}
- Testo Clausola Originale: {testo_clausola}
- Descrizione aggiuntiva: {descrizione}
- Scopo (Perché esiste): {scopo}
- Soggetto Principale (A chi si riferisce): {suggerimento_ruolo}

--- 2. FATTI DEL NUOVO CASO RECUPERATI (Contesto 2) ---
{dati_caso_json}

**ISTRUZIONI**
Il tuo compito è confrontare i "Fatti del Nuovo Caso" (Contesto 2) con le informazioni della clausola d'esempio (Contesto 1).
Questa analisi serve per capire se nel nuovo caso sia necessario oppure no includere la clausola dell'atto d'esempo.
Dovrai scegliere una sola delle tre azioni seguenti:

1.  **"scarta"**: Scegli questa azione se i Fatti Recuperati sono vuoti o se, in base alle informaizoni disponibili, deduci che nel nuovo caso non sia necessaria una clausola come quella dell'atto d'esempio.
2.  **"popola"**: Scegli questa azione se la clausola d'esempio è perftta per i fatti recuperati. Se scegli questa strada utilizzerò la clausola d'esempio all'interno del nuovo atto, sostituendo le informazioni variabili (nomi, importi, ecc.) con quelle estratte del nuovo caso.
3.  **"modifica"**: Scegli questa azione se la clausola è parzialmente in linea coni dati del nuovo caso. Se scegli questa opzione utilizzerò questa clausola per scrivere l'atto del nuovo caso, ma modificherò la struttura e i dettagli per adattarla meglio ai fatti recuperati (ad esempio il caso in esempio ha 3 rate di pagamento, mentre il nuovo caso ne ha solo 1).

**OUTPUT**
Restituisci solo ed esclusivamente un oggetto JSON con la tua decisione:
{{
  "decisione": "scarta"
}}
{{
  "decisione": "popola"
}}
{{
  "decisione": "modifica"
}}
"""

PROMPT_3_3A = """
Sei un assistente di compilazione legale. Il tuo compito è riempire con precisione un template di testo ("testo bucato"), derivante da un atto notarile, usando un set di dati forniti.

**CONTESTO**
Ti fornirò tre blocchi di informazioni.
- Un blocco <TEMPLATE> che contiene un testo bucato. È una clausola di un atto notarile, dove sono stati rimossi i dati variabili e sono stati sostituiti con dei segnaposto.
- Un blocco <VARIABILI> che descrive ogni segnaposto nel template, spiegando cosa rappresenta e che tipo di dato ci va inserito.
- Un blocco <NUOVI_DATI> che contiene i dati specifici del nuovo caso, che devono essere usati per popolare i segnaposto nel template.

**ISTRUZIONI**
Il tuo compito è quello di utilizzare i dati del nuovo caso e popolare il template. Limita ad inserire i dati negli spazi indicati. Eventualmente, se necessario, allinea i generi e le persone in modo che la frase sia gramaticalmente corretta.

<TEMPLATE>
{testo_template}
</TEMPLATE>

<VARIABILI>
{dettaglio_variabili_json}
</VARIABILI>

<NUOVI_DATI>
{dati_caso_json}
</NUOVI_DATI>

**OUTPUT**
Restituisci solo ed esclusivamente un oggetto JSON con il testo finale pulito:
{{
  "testo_generato": "Il testo finale della clausola, compilato con i dati del nuovo caso e senza segnaposti"
}}
"""

PROMPT_3_3B = """
Sei un notaio esperto. Il tuo compito è scrivere una clausola di un atto notarile, basandoti su fatti specifici e utilizzando uno stile formale.

**CONTESTO**
Devi scrivere una clausola di un atto notarile partendo da una clausola di un atto di esempio.
La clausola d'esempio ti serve come riferimento per stile, scopo e significato.
Tuttavia, la clausola che devi scrivere deve essere adattata ai dati specifici del caso su cui stiamo lavorando. Questo significa che dovrai modificare il testo della clausola d'esempio per riflettere accuratamente i fatti del nuovo caso (per esempio nella clausola d'esempio potrebbero esserci delle informazioni sul pagamento in tre rate, mentre nel caso per il nuovo atto il pagamento potrebbe essere in una sola rata tra 15 giorni).

Di seguito troverai queste informazioni:
- Un blocco <TITOLO> che contiene il titolo della clausola d'esempio assegnato da me.
- Un blocco <TESTO_ESEMPIO> che contiene il testo della clausola d'esempio.
- Un blocco <DESCRIZIONE> che contiene una descrizione aggiuntiva per darti più informazioni sulla clausola d'esempio.
- Un blocco <SCOPO> in cui c'è scritto qual è lo scopo di questa clausola.
- Un blocco <RUOLO> in cui c'è scritto a chi si riferisce questa clausola (chi è o cos'è il soggetto principale della clausola?)
- Un blocco <NUOVI_DATI> che contiene i dati specifici del nuovo caso, che devono essere usati per popolare i segnaposto nel template.

<TITOLO>
{nome_clausola}
</TITOLO>

<TESTO_ESEMPIO>
{testo_clausola}
</TESTO_ESEMPIO>

<DESCRIZIONE>
{descrizione}
</DESCRIZIONE>

<SCOPO>
{scopo}
</SCOPO>

<RUOLO>
{suggerimento_ruolo}
</RUOLO>

<NUOVI_DATI>
{dati_caso_json}
</NUOVI_DATI>

**ISTRUZIONI**
1- Leggi attentamente le informazioni della clausola d'esempio per capire cosa contiene, qual è il suo scopo e a chi si riferisce.
2- Leggi attentamente i dati del nuovo caso in modo da capire quali caratteristiche ha.
3- Scrivi la nuova clausola mantenendo lo scopo in linea con quella d'esempio, ma adattandola ai dati del nuovo caso.
4- Limitati a scrivere una clausola che sia in linea con quella d'esempio. Non aggiungere informazioni non rilevanti o di contorno, ti passerò altre clausole per quelle.

**OUTPUT**
Restituisci solo ed esclusivamente un oggetto JSON:
{{
  "testo_generato": "La nuova clausola, riscritta basandosi sui fatti del nuovo caso"
}}
"""

async def process_single_clause(chat_id, clausola: Dict[str, Any]) -> Optional[str]:
    """
    Esegue la catena di 3 chiamate AI (Recupera, Decidi, Esegui)
    per una singola clausola e restituisce il testo finale, o None.
    """
    nome_clausola = clausola.get("nome_clausola", "Sconosciuta")

    try:
        # --- CHIAMATA 1: RECUPERO CONTESSO ---
        prompt_3_1 = PROMPT_3_1.format(
            nome_clausola=nome_clausola,
            testo_clausola=clausola.get("testo_clausola"),
            descrizione=clausola.get("descrizione"),
            scopo=clausola.get("scopo"),
            suggerimento_ruolo=clausola.get("suggerimento_ruolo")
        )
        dati_caso = await chat_box(chat_id, prompt_3_1)

        if not isinstance(dati_caso, dict) or "fatti_recuperati" not in dati_caso:
            return {"decisione": "errore", "testo_generato": None, "dettaglio_errore": "3.1 Recupero fallito: risposta non valida"}

        # Cambio formato per il prossimo prompt
        dati_caso_json = json.dumps(dati_caso)

        # --- CHIAMATA 2: DECISIONE STRATEGICA ---
        prompt_3_2 = PROMPT_3_2.format(
            nome_clausola=clausola.get("nome_clausola", "N/A"),
            testo_clausola=clausola.get("testo_clausola", "N/A"),
            descrizione=clausola.get("descrizione", "N/A"),
            scopo=clausola.get("scopo", "N/A"),
            suggerimento_ruolo=clausola.get("suggerimento_ruolo", "N/A"),
            dati_caso_json=dati_caso_json
        )
        decision_response = await chat_box(chat_id, prompt_3_2)

        if not isinstance(decision_response, dict) or "decisione" not in decision_response:
            return {"decisione": "errore", "testo_generato": None, "dettaglio_errore": "3.2 Decisione fallita: risposta non valida"}
        
        # --- CHIAMATA 3: AZIONE ESECUTIVA ---
        decisione = decision_response["decisione"]
        if decisione == "scarta":
            return {"decisione": "scarta", "testo_generato": None, "dettaglio_errore": None}

        elif decisione == "popola":   # TODO: Questo posso modificarlo e fargli recuperare le informazioni invece che passargli i dati estratti prima.
            prompt_3_3a = PROMPT_3_3A.format(
                testo_template=clausola.get("testo_template"),
                dettaglio_variabili_json=json.dumps(clausola.get("dettaglio_variabili", {})),
                dati_caso_json=dati_caso_json
            )
            popola_response = await chat_box(chat_id, prompt_3_3a)
            
            if isinstance(popola_response, dict) and "testo_generato" in popola_response:
                return {"decisione": "popola", "testo_generato": popola_response["testo_generato"], "dettaglio_errore": None}
            else:
                return {"decisione": "popola", "testo_generato": None, "dettaglio_errore": "3.3A Popolamento fallito: risposta non valida"}
            
        elif decisione == "modifica":   # TODO: Uguale a sopra 3.3.A
            prompt_3_3b = PROMPT_3_3B.format(
                nome_clausola=clausola.get("nome_clausola"),
                testo_clausola=clausola.get("testo_clausola"),
                descrizione=clausola.get("descrizione"),
                scopo=clausola.get("scopo"),
                suggerimento_ruolo=clausola.get("suggerimento_ruolo"),
                dati_caso_json=dati_caso_json
            )
            modifica_response = await chat_box(chat_id, prompt_3_3b)
            
            if isinstance(modifica_response, dict) and "testo_generato" in modifica_response:
                return {"decisione": "modifica", "testo_generato": modifica_response["testo_generato"], "dettaglio_errore": None}
            else:
                return {"decisione": "modifica", "testo_generato": None, "dettaglio_errore": "3.3B Modifica fallita: risposta non valida"}
        
        else:
            return {"decisione": "errore", "testo_generato": None, "dettaglio_errore": f"3.4 Decisione non riconosciuta: {decisione}"}

    except Exception as e:
        print(f"[Step 3] ERRORE CRITICO durante l'elaborazione della clausola '{nome_clausola}': {e}")
        return None 


# --- Funzione Principale dello Step 3 ---
async def run_step3(chat_id, clausole_complete) -> str:
    """
    Esegue la Fase 3: Elaborazione e Adattamento Clausole.
    Itera su tutte le clausole del template, esegue la catena di chiamate AI
    (Recupera, Decidi, Esegui) in parallelo, e assembla il risultato.

    Args:
        chat_id (str): L'ID della chat per la sessione.
        clausole_scopo: .

    Returns:
        str: La bozza del documento assemblato (ancora da pulire).
    """    
    tasks = []
    # Prepara un task parallelo per ogni clausola
    for clausola in clausole_complete:
        tasks.append(process_single_clause(chat_id, clausola))

    # Esegue l'elaborazione di tutte le clausole in parallelo
    risultati_clausole = await asyncio.gather(*tasks)

    if risultati_clausole == None:
        return None
    
    for i, outcome in enumerate(risultati_clausole):
        # 'outcome' è il dizionario restituito da _process_single_clause
        # Aggiungi le nuove chiavi al dizionario *originale* in clausole_scopo
        clausole_complete[i]["decisione"] = outcome.get("decisione", "errore_imprevisto")
        clausole_complete[i]["testo_generato"] = outcome.get("testo_generato") # Sarà None se scartato/errore
        clausole_complete[i]["dettaglio_errore"] = outcome.get("dettaglio_errore") # Sarà None se successo
    
    return clausole_complete
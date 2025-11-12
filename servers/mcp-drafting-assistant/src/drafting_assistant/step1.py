import asyncio
import json
from typing import List, Dict, Any, Optional

# Importa la funzione per chattare con l'AI
from .chatbox import chat_box


PROMPT_1_1 = """
Sei un software di analisi documentale specializzato in atti notarili italiani. Il tuo unico scopo è analizzare un documento e restituirne la struttura logica. Non sei un assistente conversazionale.

**COMPITO:**
Analizza il seguente atto notarile fornito all'interno del tag `<ATTO_DI_ESEMPIO>` e decomponilo nella sua struttura logica fondamentale.

**ISTRUZIONI:**
1.  Leggi attentamente l'intero atto.
2.  Identifica le sezioni logiche principali. Identifica le sezioni come 'Intestazione', 'Comparendo', 'Premesse', 'Chiusura', ecc. .
3.  Restituisci **solo ed esclusivamente** un array JSON contenente i titoli delle sezioni logiche principali in ordine di apparizione (es. ["Intestazione", "Comparendo", "Premesse", ...]).

<ATTO_DI_ESEMPIO>
{atto_esempio}
</ATTO_DI_ESEMPIO>
"""

PROMPT_1_2 = """
Sei un software di segmentazione documentale ultra-preciso, specializzato in atti notarili.

**COMPITO:**
Il tuo compito è dividere un documento legale in sezioni, basandoti su una lista di titoli concettuali. Devi associare ogni titolo al suo blocco di testo corrispondente, senza creare sovrapposizioni o duplicazioni di testo.

**INPUT:**
1.  Una LISTA_SEZIONI ordinata di titoli concettuali. Te la fornirò all'interno del tag <LISTA_SEZIONI>
2.  Un TESTO_COMPLETO di un atto notarile. Te lo fornirò all'interno del tag <TESTO_COMPLETO>

**ISTRUZIONI:**
1.  Leggi l'intera LISTA_SEZIONI per capire la struttura che devi cercare.
2.  Leggi il TESTO_COMPLETO dall'inizio alla fine.
3.  Per ogni titolo nella LISTA_SEZIONI, identifica il blocco di testo che corrisponde a quel concetto.
4.  REGOLA ANTI-SOVRAPPOSIZIONE: Un pezzo di testo può appartenere solo a una sezione. L'inizio di una nuova sezione concettuale segna la fine di quella precedente.

**OUTPUT:**
Restituisci solo ed esclusivamente un oggetto JSON dove ogni chiave è un titolo dalla LISTA_SEZIONI e il suo valore è il testo che hai estratto per quella specifica sezione.

<LISTA_SEZIONI>
{titoli_sezioni}
</LISTA_SEZIONI>

<TESTO_COMPLETO>
{atto_esempio}
</TESTO_COMPLETO>
"""

PROMPT_1_2_1 = """
Sei un notaio esperto specializzato in analisi di documenti. Il tuo compito è analizzare delle sezioni di atti e scomporle in unità logiche più piccole.

**COMPITO:**
Ti viene fornito un blocco di testo che rappresenta una sezione di un atto notarile (es. le "Premesse" o i "Patti e Condizioni").
Il tuo compito è scomporre il testo in "clausole" o "paragrafi" che trattano un unico tema o soggetto principale. L'obiettivo NON è creare quante più clausole possibili, ma creare le sotto sezioni più logiche.

**ISTRUZIONI:**
1.  Leggi la sezione di atto che ti viene fornita all'interno del tag <BLOCCO_DI_TESTO>.
2.  Il tuo compito è segmentare il testo in blocchi consecutivi. Ogni blocco deve trattare un singolo tema o soggetto principale (es. tutti i dati di una persona, la descrizione di un immobile, una specifica condizione di pagamento).
Regola importante: Procedi in modo sequenziale. Non saltare parti del testo e non raggruppare informazioni che si trovano in punti diversi del documento. L'inizio di un nuovo tema segna la fine del blocco precedente.
3.  Per ogni "sotto-sezione" che trovi, assegnale un titolo concettuale descrittivo.

**OUTPUT:**
Restituisci solo ed esclusivamente un array di oggetti JSON. Ogni oggetto deve rappresentare una clausola e contenere **assolutamente e unicamente** queste due chiavi:
* `"nome_clausola"`: il titolo concettuale che hai assegnato.
* `"testo_clausola"`: il testo esatto del paragrafo o della clausola.

**NOTA:**
Se un blocco di testo è già breve e tratta un solo argomento (es. una singola dichiarazione), restituiscilo come un'unica clausola senza suddividerlo.

<BLOCCO_DI_TESTO>
{macrosezioni}
</BLOCCO_DI_TESTO>
"""

PROMPT_1_2_2 = """
Sei un software di analisi legale specializzato nell'interpretazione del contesto. Il tuo scopo è identificare il ruolo dei soggetti all'interno di una clausola legale per generare un'etichetta di contesto.

### COMPITO
Il tuo compito è analizzare una clausola specifica (`CLAUSOLA`) all'interno del suo contesto più ampio (`SEZIONE_ATTO`) e generare una singola etichetta testuale, o "suggerimento", che descriva il ruolo del soggetto principale a cui la clausola si riferisce.

Questo "suggerimento" è FONDAMENTALE perché verrà usato da un altro modello per capire come mappare correttamente i dati di un nuovo caso.

### ISTRUZIONI
1.  Leggi attentamente la `CLAUSOLA` e la `SEZIONE_ATTO` per comprendere il contesto.
2.  Identifica il soggetto principale (persona, azienda, bene, ecc.) a cui la `CLAUSOLA` fa riferimento.
3.  Genera un'etichetta testuale che descriva il ruolo astratto di quel soggetto. Segui queste regole FONDAMENTALI:

    * REGOLA D'ORO: Il suggerimento deve essere un RUOLO, non un NOME PROPRIO. Se il testo parla di "UBALDI MASSIMO UBALDO, acquirente", il suggerimento corretto è `"Parte Acquirente"` o `"L'acquirente dell'immobile"`, MAI `"UBALDI MASSIMO UBALDO"`.

    * Sii Descrittivo ma Conciso: L'etichetta può essere una o più parole. Ad esempio, `"Parte Venditrice"` e `"Il soggetto che vende l'immobile"` sono entrambi validi. Scegli la forma più chiara e utile.

    * Gestisci i Casi Generici: Se la clausola non si riferisce a un soggetto specifico (es. è una formula di rito, una data, un riferimento di legge generico), genera un'etichetta come `"Generale"`, `"Formula di Rito"` o `"Informazione sull'Atto"`.

### OUTPUT
Restituisci un oggetto JSON strutturato come segue:
* `"nome_clausola"`: riporta esattamente il nome della clausola come l'hai ricevuta in input.
* `"suggerimento_ruolo"`: con l'etichetta testuale che hai generato.

<CLAUSOLA>
- "nome_clausola":
{nome_clausola}

- "testo_clausola":
{testo_clausola}
</CLAUSOLA>

<SEZIONE_ATTO>
{macrosezione}
</SEZIONE_ATTO>
"""


# --- Funzione Ausiliaria per Trovare il Contesto ---
def trova_contesto(testo_clausola: str, macrosezioni: Dict[str, str]) -> Optional[str]:
    for macrosezione in macrosezioni.values():
        if testo_clausola.strip() in macrosezione.strip():
            return macrosezione
    print(f"ATTENZIONE: Contesto non trovato per la clausola: {testo_clausola[:50]}...")   # Debug
    return "ERRORE: Contesto della sezione non disponibile per questa clausola."

async def run_step1(chat_id, example_act_text: str):
    """
    Esegue lo Step 1 della pipeline di drafting:
    1. Suddivide l'atto d'esempio in sezioni logiche.
    2. Suddivide ogni sezione in clausole/paragrafi.

    Args:
        example_act_text: Il testo completo dell'atto notarile d'esempio.
    """

    # --- STEP 1.1 ---
    prompt1_1 = PROMPT_1_1.format(atto_esempio=example_act_text)
    titoli_sezioni = await chat_box(chat_id, prompt1_1)
    if not titoli_sezioni:
        print("Errore nello Step 1.1.")
        return None
    
    print("Response Step 1.1:", titoli_sezioni)   # Debug
    #titoli_sezioni = ['Intestazione', 'Comparendo', 'Premesse', 'Dichiarazioni', 'Chiusura']


    # --- STEP 1.2 ---
    prompt1_2 = PROMPT_1_2.format(titoli_sezioni=json.dumps(titoli_sezioni), atto_esempio=example_act_text)
    macrosezioni = await chat_box(chat_id, prompt1_2)
    if not macrosezioni or not isinstance(macrosezioni, dict):
        print(f"Errore nello Step 1.2.\nMacrosezioni ottenute: {macrosezioni}")
        return None

    print("Response Step 1.2:", macrosezioni)   # Debug
    #macrosezioni = {
        #"Intestazione": "REPERTORIO N. 13189 RACCOLTA N. 7378\nATTO DI QUIETANZA\nREPUBBLICA ITALIANA\n\nL'anno duemilaventiquattro, il giorno quattro, del mese di ottobre,\nin Sondrio, nel mio Studio in Via Stelvio n. 12.",
        #"Comparizione": "Avanti a me Dott. Demetrio Rando Notaio in Sondrio, iscritto nel Ruolo del Collegio Notarile del Distretto di Sondrio,\nsono personalmente comparsi i signori:\nLIGARI SIMONE, nato a Sondrio il giorno 6 gennaio 1992, residente a Sondrio, Via Nazario Sauro n. 44,\nil quale interviene al presente atto nella sua qualità di procuratore speciale della signora:\nMATTABONI KATIA, nata a Sondrio il giorno 13 marzo 1972, residente a Sondrio, Via Nazario Sauro n. 44,\ncodice fiscale MTT KTA 72C53 I829F,\nla quale, a mezzo del procuratore, dichiara di essere di stato civile libero,\ngiusta procura speciale a mio rogito in data 25 settembre 2024 repertorio n. 13160, che in originale si allega al presente atto sotto la lettera \"A\", quale parte integrante e sostanziale;\nUBALDI MASSIMO UBALDO, nato a Milano il giorno 5 settembre 1959, residente a Basiglio, Piazza Marco Polo n. 1/A,\ncodice fiscale BLD MSM 59P05 F205L,\nil quale dichiara di essere coniugato in regime di separazione dei beni in quanto legalmente separato.\nDetti comparenti, della cui identità personale io Notaio sono certo, convengono e stipulano quanto segue:",
        #"Premesse": "PREMESSO:\nche con atto di compravendita a mio rogito in data 26 maggio 2022 repertorio n. 10281/5529, registrato a Sondrio il 16 giugno 2022 al n. 5747 serie 1T e trascritto a Sondrio il 21 giugno 2022 al n. 6413 Reg. Part., la signora MATTABONI KATIA in seguito, per brevità, denominata anche \"Parte Venditrice\", ha venduto, con patto di riservato dominio ai sensi degli artt. 1523 e seguenti del C.C. al signor UBALDI MASSIMO UBALDO, in seguito, per brevità, denominato anche \"Parte Acquirente\" la piena proprietà degli immobili siti in Comune di Montagna in Valtellina, posti in Via Benedetti e censiti in Catasto Fabbricati a:\nFoglio 22 (ventidue) mappale numero 298 (duecentonovantotto) subalterno 5 (cinque) Via Benedetti snc piano 1-2 categoria A/3 cl. U consistenza vani 3,5 (superficie catastale Totale mq. 84 Totale escluse aree scoperte mq. 81) RC. Euro 169,91\ngraffato con\nFoglio 22 (ventidue) mappale numero 299 (duecentonovantanove) subalterno 4 (quattro);\nFoglio 22 (ventidue) mappale numero 298 (duecentonovantotto) subalterno 3 (tre) Via Benedetti snc piano T categoria C/2 cl. 2 consistenza mq. 13 (superficie catastale Totale mq. 16) RC. Euro 17,46;\nper il prezzo di Euro 50.000,00 (cinquantamila virgola zero zero) che veniva regolato come segue:\n= quanto ad Euro 5.000,00 (cinquemila virgola zero zero) sono stati versati alla Parte Venditrice dalla Parte Acquirente con mezzi di pagamento già indicati nell'atto di compravendita e per detta somma la Parte Venditrice ha già rilasciato quietanza alla Parte Acquirente;\n= quanto a Euro 15.000,00 (quindicimila virgola zero zero) la Parte Acquirente si obbligava a versarli alla Parte Venditrice, senza interessi, entro 7 (sette) giorni dalla data del 26 maggio 2022 (duemilaventidue);\n= quanto a Euro 30.000,00 (trentamila virgola zero zero) la Parte Acquirente si obbligava a versarli alla Parte Venditrice, senza interessi, in una o più soluzioni entro il 31 (trentuno) gennaio 2025 (duemilaventicinque);\nche con il citato atto a mio rogito in data 26 maggio 2022 repertorio n. 10281/5529 le parti pattuivano, come detto, ai sensi dell'art. 1523 e seguenti del codice civile, che il trasferimento della proprietà dei beni oggetto di compravendita si producesse solo a seguito dell'avvenuto pagamento integrale del prezzo;\nche il patto di riservato dominio è stato fatto constare dalla nota di trascrizione dell'atto di compravendita, ai sensi dell'art. 2659 del C.C.;\nche il signor UBALDI MASSIMO UBALDO ha già provveduto in data 27 maggio 2022 al pagamento della somma di Euro 15.000,00 (quindicimila virgola zero zero) mediante un bonifico bancario eseguito per il tramite della Banca Monte dei Paschi di Siena S.p.A., CRO A102072973501030483421134210IT, ed intende ora procedere al pagamento del residuo importo di Euro 30.000,00 (trentamila virgola zero zero);\nche si rende ora necessario sottoscrivere atto di quietanza al fine di consentirne l'annotamento a margine della trascrizione della compravendita ai fini della cancellazione del patto di riservato dominio per gli effetti di cui all'art. 2668.\nPREMESSO QUANTO SOPRA\nche costituisce parte integrante e sostanziale del presente atto,",
        #"Dichiarazioni": "la signora\nMATTABONI KATIA, come sopra rappresentata,\ndichiara\ndi aver ricevuto dal signor UBALDI MASSIMO UBALDO la somma complessiva di Euro 45.000,00 (quarantacinquemila virgola zero zero), con le modalità di cui infra e in dipendenza di quanto sopra la signora MATTABONI KATIA rilascia al signor UBALDI MASSIMO UBALDO, piena e definitiva quietanza a saldo dell'importo di Euro 45.000,00 (quarantacinquemila virgola zero zero), e pertanto dà atto che risulta pagato l'intero prezzo della vendita con patto di riservato dominio di cui all'atto a mio rogito in data 26 maggio 2022 repertorio n. 10281/5529 citato in premessa.\nConseguentemente, il diritto di proprietà degli immobili compravenduti si trasferisce alla Parte Acquirente con decorrenza dalla data odierna.\nLa Parte Venditrice consente pertanto che a margine della trascrizione della compravendita citata in premessa venga eseguito l'annotamento del presente atto ai fini della cancellazione del patto di riservato dominio per gli effetti di cui all'art. 2668.\nAi sensi e per gli effetti dell'art. 35, comma 22 del D.L. 4 luglio 2006 n. 223, convertito in legge 4 agosto 2006 n. 248, nonchè dell'art. 1, comma 48 della Legge 27 dicembre 2006 n. 296, le Parti da me Notaio ammonite sulle conseguenze delle dichiarazioni mendaci previste dall'art. 76 del D.P.R. 28 dicembre 2000 n. 445, ai sensi e per gli effetti dell'art. 47 del D.P.R. sopracitato e a conoscenza dei poteri di accertamento dell'amministrazione finanziaria e delle conseguenze di una incompleta o mendace indicazione dei dati, dichiarano che il saldo prezzo di cui sopra è stato corrisposto come segue:\nquanto ad Euro 15.000,00 (quindicimila virgola zero zero) mediante il bonifico di cui in premessa;\nquanto ai residui Euro 30.000,00 (trentamila virgola zero zero) mediante un assegno circolare \"non trasferibile\" n. 6081668787-12 di corrispondente importo emesso dalla Banca Monte Dei Paschi di Siena S.p.A., in data 2 ottobre 2024 all'ordine di MATTABONI KATIA.\nTutte le spese inerenti e conseguenti a questo atto sono a carico della Parte Acquirente.\nI comparenti dichiarano di essere a conoscenza di quanto allegato e perciò dispensano me Notaio dal darne lettura.",
        #"Chiusura": "Richiesto io Notaio ho ricevuto quest'atto da me letto ai comparenti che lo approvano dichiarandolo conforme alla loro volontà.\nQuest'atto è scritto in parte da persona di mia fiducia ed in parte da me Notaio su sei pagine di due fogli fin qui.\nViene sottoscritto alle ore nove e trenta.\nF.ti: LIGARI SIMONE\nMASSIMO UBALDO UBALDI\nDEMETRIO RANDO Notaio"
    #}


    # --- STEP 1.2.1 ---
    tasks = []   # Lista per raccogliere le chiamate asincrone
    clausole: List[Dict[str, str]] = [] # L'hint del tipo è solo per me. Non viene utilizzato da python

    # Prepara le chiamate AI, una per ogni macrosezione. Sarebbe un po' come lo SPLIT
    for section_title, section_text in macrosezioni.items():
        if section_text and section_text.strip(): # Salta sezioni vuote
            prompt1_2_1 = PROMPT_1_2_1.format(macrosezioni=section_text.strip())
            tasks.append(chat_box(chat_id, prompt1_2_1)) # Aggiunge la "promessa" di chiamata

    try:
        # Esegue tutte le chiamate a chatbox in parallelo
        responses1_2_1 = await asyncio.gather(*tasks) 
        # Per come ho scritto il prompt, ogni risposta che ottengo da chatbox è una lista di dizionari. Queste risposte vengono messe in una lista in automatico dalla funzione asincrona

        # Solito controllo come step sopra ma più complesso. Controlla che le risposte siano liste e che ogni elemento della lista sia un diz con le chiavi richieste
        numero_clausole_valide = 0
        totale_clausole = 0
        for response in responses1_2_1:
            if not response or not isinstance(response, list):
                print("Errore nello Step 1.2.1: risposta vuota o non lista.")
                continue
            
            totale_clausole += len(response)
            valid_clauses = [clause for clause in response if isinstance(clause, dict) and 'nome_clausola' in clause and 'testo_clausola' in clause]
            clausole.extend(valid_clauses)
            numero_clausole_valide += len(valid_clauses)

        print(f"Totale clausole estratte: {totale_clausole}\nTotale clausole valide: {numero_clausole_valide}")   # Debug

    except Exception as e:
        print(f"ERRORE nello step 1.2.1 (asyncio.gather o processing): {e}")
        return None
    
    print("Response Step 1.2.1: ", clausole)   # Debug
    #clausole = [
        #{'nome_clausola': "Intestazione dell'atto", 'testo_clausola': 'REPERTORIO N. 13189 RACCOLTA N. 7378\nATTO DI QUIETANZA\nREPUBBLICA ITALIANA'},
        #{'nome_clausola': "Data e luogo dell'atto", 'testo_clausola': "L'anno duemilaventiquattro, il giorno quattro, del mese di ottobre,\nin Sondrio, nel mio Studio in Via Stelvio n. 12."},
        #{'nome_clausola': 'Identificazione del Notaio', 'testo_clausola': 'Avanti a me Dott. Demetrio Rando Notaio in Sondrio, iscritto nel Ruolo del Collegio Notarile del Distretto di Sondrio,'},
        #{'nome_clausola': 'Identificazione del Comparente 1', 'testo_clausola': 'sono personalmente comparsi i signori: LIGARI SIMONE, nato a Sondrio il giorno 6 gennaio 1992, residente a Sondrio, Via Nazario Sauro n. 44, il quale interviene al presente atto nella sua qualità di procuratore speciale della signora:'},
        #{'nome_clausola': 'Identificazione del Rappresentato', 'testo_clausola': 'MATTABONI KATIA, nata a Sondrio il giorno 13 marzo 1972, residente a Sondrio, Via Nazario Sauro n. 44, codice fiscale MTT KTA 72C53 I829F, la quale, a mezzo del procuratore, dichiara di essere di stato civile libero, giusta procura speciale a mio rogito in data 25 settembre 2024 repertorio n. 13160, che in originale si allega al presente atto sotto la lettera "A", quale parte integrante e sostanziale;'},
        #{'nome_clausola': 'Identificazione del Comparente 2', 'testo_clausola': 'UBALDI MASSIMO UBALDO, nato a Milano il giorno 5 settembre 1959, residente a Basiglio, Piazza Marco Polo n. 1/A, codice fiscale BLD MSM 59P05 F205L, il quale dichiara di essere coniugato in regime di separazione dei beni in quanto legalmente separato.'},
        #{'nome_clausola': 'Dichiarazione di Identità', 'testo_clausola': 'Detti comparenti, della cui identità personale io Notaio sono certo, convengono e stipulano quanto segue:'},
        #{'nome_clausola': "Dettagli dell'atto di compravendita", 'testo_clausola': 'che con atto di compravendita a mio rogito in data 26 maggio 2022 repertorio n. 10281/5529, registrato a Sondrio il 16 giugno 2022 al n. 5747 serie 1T e trascritto a Sondrio il 21 giugno 2022 al n. 6413 Reg. Part., la signora MATTABONI KATIA in seguito, per brevità, denominata anche "Parte Venditrice", ha venduto, con patto di riservato dominio ai sensi degli artt. 1523 e seguenti del C.C. al signor UBALDI MASSIMO UBALDO, in seguito, per brevità, denominato anche "Parte Acquirente" la piena proprietà degli immobili siti in Comune di Montagna in Valtellina, posti in Via Benedetti e censiti in Catasto Fabbricati a:'},
        #{'nome_clausola': 'Descrizione degli immobili', 'testo_clausola': 'Foglio 22 (ventidue) mappale numero 298 (duecentonovantotto) subalterno 5 (cinque) Via Benedetti snc piano 1-2 categoria A/3 cl. U consistenza vani 3,5 (superficie catastale Totale mq. 84 Totale escluse aree scoperte mq. 81) RC. Euro 169,91\ngraffato con\nFoglio 22 (ventidue) mappale numero 299 (duecentonovantanove) subalterno 4 (quattro);\nFoglio 22 (ventidue) mappale numero 298 (duecentonovantotto) subalterno 3 (tre) Via Benedetti snc piano T categoria C/2 cl. 2 consistenza mq. 13 (superficie catastale Totale mq. 16) RC. Euro 17,46;'},
        #{'nome_clausola': 'Condizioni di pagamento', 'testo_clausola': "per il prezzo di Euro 50.000,00 (cinquantamila virgola zero zero) che veniva regolato come segue:\n= quanto ad Euro 5.000,00 (cinquemila virgola zero zero) sono stati versati alla Parte Venditrice dalla Parte Acquirente con mezzi di pagamento già indicati nell'atto di compravendita e per detta somma la Parte Venditrice ha già rilasciato quietanza alla Parte Acquirente;\n= quanto a Euro 15.000,00 (quindicimila virgola zero zero) la Parte Acquirente si obbligava a versarli alla Parte Venditrice, senza interessi, entro 7 (sette) giorni dalla data del 26 maggio 2022 (duemilaventidue);\n= quanto a Euro 30.000,00 (trentamila virgola zero zero) la Parte Acquirente si obbligava a versarli alla Parte Venditrice, senza interessi, in una o più soluzioni entro il 31 (trentuno) gennaio 2025 (duemilaventicinque);"},
        #{'nome_clausola': 'Patto di riservato dominio', 'testo_clausola': "che con il citato atto a mio rogito in data 26 maggio 2022 repertorio n. 10281/5529 le parti pattuivano, come detto, ai sensi dell'art. 1523 e seguenti del codice civile, che il trasferimento della proprietà dei beni oggetto di compravendita si producesse solo a seguito dell'avvenuto pagamento integrale del prezzo;\nche il patto di riservato dominio è stato fatto constare dalla nota di trascrizione dell'atto di compravendita, ai sensi dell'art. 2659 del C.C.;"},
        #{'nome_clausola': 'Pagamento effettuato e intenzione di saldo', 'testo_clausola': 'che il signor UBALDI MASSIMO UBALDO ha già provveduto in data 27 maggio 2022 al pagamento della somma di Euro 15.000,00 (quindicimila virgola zero zero) mediante un bonifico bancario eseguito per il tramite della Banca Monte dei Paschi di Siena S.p.A., CRO A102072973501030483421134210IT, ed intende ora procedere al pagamento del residuo importo di Euro 30.000,00 (trentamila virgola zero zero);'},
        #{'nome_clausola': "Necessità di sottoscrizione dell'atto di quietanza", 'testo_clausola': "che si rende ora necessario sottoscrivere atto di quietanza al fine di consentirne l'annotamento a margine della trascrizione della compravendita ai fini della cancellazione del patto di riservato dominio per gli effetti di cui all'art. 2668."},
        #{'nome_clausola': "Integrazione dell'atto", 'testo_clausola': 'PREMESSO QUANTO SOPRA\nche costituisce parte integrante e sostanziale del presente atto,'},
        #{'nome_clausola': 'Dichiarazione di ricezione del pagamento', 'testo_clausola': "la signora MATTABONI KATIA, come sopra rappresentata, dichiara di aver ricevuto dal signor UBALDI MASSIMO UBALDO la somma complessiva di Euro 45.000,00 (quarantacinquemila virgola zero zero), con le modalità di cui infra e in dipendenza di quanto sopra la signora MATTABONI KATIA rilascia al signor UBALDI MASSIMO UBALDO, piena e definitiva quietanza a saldo dell'importo di Euro 45.000,00 (quarantacinquemila virgola zero zero), e pertanto dà atto che risulta pagato l'intero prezzo della vendita con patto di riservato dominio di cui all'atto a mio rogito in data 26 maggio 2022 repertorio n. 10281/5529 citato in premessa."},
        #{'nome_clausola': 'Trasferimento del diritto di proprietà', 'testo_clausola': 'Conseguentemente, il diritto di proprietà degli immobili compravenduti si trasferisce alla Parte Acquirente con decorrenza dalla data odierna.'},
        #{'nome_clausola': 'Annotamento e cancellazione del patto di riservato dominio', 'testo_clausola': "La Parte Venditrice consente pertanto che a margine della trascrizione della compravendita citata in premessa venga eseguito l'annotamento del presente atto ai fini della cancellazione del patto di riservato dominio per gli effetti di cui all'art. 2668."},
        #{'nome_clausola': 'Dichiarazione di pagamento e modalità', 'testo_clausola': 'Ai sensi e per gli effetti dell\'art. 35, comma 22 del D.L. 4 luglio 2006 n. 223, convertito in legge 4 agosto 2006 n. 248, nonchè dell\'art. 1, comma 48 della Legge 27 dicembre 2006 n. 296, le Parti da me Notaio ammonite sulle conseguenze delle dichiarazioni mendaci previste dall\'art. 76 del D.P.R. 28 dicembre 2000 n. 445, ai sensi e per gli effetti dell\'art. 47 del D.P.R. sopracitato e a conoscenza dei poteri di accertamento dell\'amministrazione finanziaria e delle conseguenze di una incompleta o mendace indicazione dei dati, dichiarano che il saldo prezzo di cui sopra è stato corrisposto come segue: quanto ad Euro 15.000,00 (quindicimila virgola zero zero) mediante il bonifico di cui in premessa; quanto ai residui Euro 30.000,00 (trentamila virgola zero zero) mediante un assegno circolare "non trasferibile" n. 6081668787-12 di corrispondente importo emesso dalla Banca Monte Dei Paschi di Siena S.p.A., in data 2 ottobre 2024 all\'ordine di MATTABONI KATIA.'},
        #{'nome_clausola': 'Spese a carico della Parte Acquirente', 'testo_clausola': 'Tutte le spese inerenti e conseguenti a questo atto sono a carico della Parte Acquirente.'},
        #{'nome_clausola': 'Dispensa dalla lettura degli allegati', 'testo_clausola': 'I comparenti dichiarano di essere a conoscenza di quanto allegato e perciò dispensano me Notaio dal darne lettura.'},
        #{'nome_clausola': "Approvazione dell'atto", 'testo_clausola': "Richiesto io Notaio ho ricevuto quest'atto da me letto ai comparenti che lo approvano dichiarandolo conforme alla loro volontà."},
        #{'nome_clausola': "Redazione dell'atto", 'testo_clausola': "Quest'atto è scritto in parte da persona di mia fiducia ed in parte da me Notaio su sei pagine di due fogli fin qui."},
        #{'nome_clausola': "Sottoscrizione dell'atto", 'testo_clausola': 'Viene sottoscritto alle ore nove e trenta.\nF.ti: LIGARI SIMONE\nMASSIMO UBALDO UBALDI\nDEMETRIO RANDO Notaio'}
    #]

    
    # --- STEP 1.2.2 ---
    tasks_1_2_2 = []
    clausole_e_ruolo: List[Dict[str, Any]] = []

    # Prepara le chiamate
    for clausola in clausole:
        nome_clausola = clausola.get('nome_clausola')
        testo_clausola = clausola.get('testo_clausola')

        # Trova il contesto per questa clausola
        sezione_atto = trova_contesto(testo_clausola, macrosezioni)
        # In questo prompt mi faccio dare solo nome e suggerimento e poi il tetso della clausolam lo aggiungo manualmente per limitare gli errori.
        prompt1_2_2 = PROMPT_1_2_2.format(nome_clausola=nome_clausola, testo_clausola=testo_clausola, macrosezione=sezione_atto)
        tasks_1_2_2.append((clausola, chat_box(chat_id, prompt1_2_2)))
        
    try:
        # Crea una nuova lista di task tenendo solo chat_box(prompt) e poi esegue tutte le chiamate in parallelo
        coroutines = [task[1] for task in tasks_1_2_2]
        responses_1_2_2 = await asyncio.gather(*coroutines)

        # Processa i risultati associandoli alle clausole originali
        for i, response in enumerate(responses_1_2_2):
            clausola_originale = tasks_1_2_2[i][0]   # Recupera la clausola originale associata per controllare che sia tutto ok

            if not response or not isinstance(response, dict) or 'suggerimento_ruolo' not in response or 'nome_clausola' not in response:
                print("Errore nello Step 1.2.2: risposta vuota o non dizionario o con chiavi sbagliate.")
                # Salvo comunque la clausola senza suggerimento
                clausole_e_ruolo.append({
                    "nome_clausola": clausola_originale['nome_clausola'],
                    "testo_clausola": clausola_originale['testo_clausola'],
                    "suggerimento_ruolo": "ERRORE: nessun suggerimento disponibile"
                })
                continue
            
            suggerimento_ruolo = response['suggerimento_ruolo']    
            # Aggiungi la clausola arricchita alla lista dei risultati
            clausole_e_ruolo.append({
                "nome_clausola": clausola_originale['nome_clausola'],
                "testo_clausola": clausola_originale['testo_clausola'],
                "suggerimento_ruolo": suggerimento_ruolo
            })

    except Exception as e:
        print(f"ERRORE nello step 1.2.2 (asyncio.gather o processing): {e}")
        return None
    
    print("Response Step 1.2.2:", clausole_e_ruolo)   # Debug
    #clausole_e_ruolo = [
        #{'nome_clausola': "Intestazione dell'atto", 'testo_clausola': 'REPERTORIO N. 13189 RACCOLTA N. 7378\nATTO DI QUIETANZA\nREPUBBLICA ITALIANA', 'suggerimento_ruolo': 'Generale'},
        #{'nome_clausola': "Data e luogo dell'atto", 'testo_clausola': "L'anno duemilaventiquattro, il giorno quattro, del mese di ottobre,\nin Sondrio, nel mio Studio in Via Stelvio n. 12.", 'suggerimento_ruolo': 'Generale'},
        #{'nome_clausola': 'Identificazione del Notaio', 'testo_clausola': 'Avanti a me Dott. Demetrio Rando Notaio in Sondrio, iscritto nel Ruolo del Collegio Notarile del Distretto di Sondrio,', 'suggerimento_ruolo': 'Il Notaio'},
        #{'nome_clausola': 'Identificazione del Comparente 1', 'testo_clausola': 'sono personalmente comparsi i signori: LIGARI SIMONE, nato a Sondrio il giorno 6 gennaio 1992, residente a Sondrio, Via Nazario Sauro n. 44, il quale interviene al presente atto nella sua qualità di procuratore speciale della signora:', 'suggerimento_ruolo': 'Il soggetto rappresentato come Procuratore Speciale'},
        #{'nome_clausola': 'Identificazione del Rappresentato', 'testo_clausola': 'MATTABONI KATIA, nata a Sondrio il giorno 13 marzo 1972, residente a Sondrio, Via Nazario Sauro n. 44, codice fiscale MTT KTA 72C53 I829F, la quale, a mezzo del procuratore, dichiara di essere di stato civile libero, giusta procura speciale a mio rogito in data 25 settembre 2024 repertorio n. 13160, che in originale si allega al presente atto sotto la lettera "A", quale parte integrante e sostanziale;', 'suggerimento_ruolo': 'Persona Rappresentata'},
        #{'nome_clausola': 'Identificazione del Comparente 2', 'testo_clausola': 'UBALDI MASSIMO UBALDO, nato a Milano il giorno 5 settembre 1959, residente a Basiglio, Piazza Marco Polo n. 1/A, codice fiscale BLD MSM 59P05 F205L, il quale dichiara di essere coniugato in regime di separazione dei beni in quanto legalmente separato.', 'suggerimento_ruolo': 'Parte Dichiarante'},
        #{'nome_clausola': 'Dichiarazione di Identità', 'testo_clausola': 'Detti comparenti, della cui identità personale io Notaio sono certo, convengono e stipulano quanto segue:', 'suggerimento_ruolo': 'Parte Comparenti'},
        #{'nome_clausola': "Dettagli dell'atto di compravendita", 'testo_clausola': 'che con atto di compravendita a mio rogito in data 26 maggio 2022 repertorio n. 10281/5529, registrato a Sondrio il 16 giugno 2022 al n. 5747 serie 1T e trascritto a Sondrio il 21 giugno 2022 al n. 6413 Reg. Part., la signora MATTABONI KATIA in seguito, per brevità, denominata anche "Parte Venditrice", ha venduto, con patto di riservato dominio ai sensi degli artt. 1523 e seguenti del C.C. al signor UBALDI MASSIMO UBALDO, in seguito, per brevità, denominato anche "Parte Acquirente" la piena proprietà degli immobili siti in Comune di Montagna in Valtellina, posti in Via Benedetti e censiti in Catasto Fabbricati a:', 'suggerimento_ruolo': 'Parte Venditrice e Parte Acquirente'},
        #{'nome_clausola': 'Descrizione degli immobili', 'testo_clausola': 'Foglio 22 (ventidue) mappale numero 298 (duecentonovantotto) subalterno 5 (cinque) Via Benedetti snc piano 1-2 categoria A/3 cl. U consistenza vani 3,5 (superficie catastale Totale mq. 84 Totale escluse aree scoperte mq. 81) RC. Euro 169,91\ngraffato con\nFoglio 22 (ventidue) mappale numero 299 (duecentonovantanove) subalterno 4 (quattro);\nFoglio 22 (ventidue) mappale numero 298 (duecentonovantotto) subalterno 3 (tre) Via Benedetti snc piano T categoria C/2 cl. 2 consistenza mq. 13 (superficie catastale Totale mq. 16) RC. Euro 17,46;', 'suggerimento_ruolo': 'Oggetto della compravendita'},
        #{'nome_clausola': 'Condizioni di pagamento', 'testo_clausola': "per il prezzo di Euro 50.000,00 (cinquantamila virgola zero zero) che veniva regolato come segue:\n= quanto ad Euro 5.000,00 (cinquemila virgola zero zero) sono stati versati alla Parte Venditrice dalla Parte Acquirente con mezzi di pagamento già indicati nell'atto di compravendita e per detta somma la Parte Venditrice ha già rilasciato quietanza alla Parte Acquirente;\n= quanto a Euro 15.000,00 (quindicimila virgola zero zero) la Parte Acquirente si obbligava a versarli alla Parte Venditrice, senza interessi, entro 7 (sette) giorni dalla data del 26 maggio 2022 (duemilaventidue);\n= quanto a Euro 30.000,00 (trentamila virgola zero zero) la Parte Acquirente si obbligava a versarli alla Parte Venditrice, senza interessi, in una o più soluzioni entro il 31 (trentuno) gennaio 2025 (duemilaventicinque);", 'suggerimento_ruolo': 'Parte Acquirente'},
        #{'nome_clausola': 'Patto di riservato dominio', 'testo_clausola': "che con il citato atto a mio rogito in data 26 maggio 2022 repertorio n. 10281/5529 le parti pattuivano, come detto, ai sensi dell'art. 1523 e seguenti del codice civile, che il trasferimento della proprietà dei beni oggetto di compravendita si producesse solo a seguito dell'avvenuto pagamento integrale del prezzo;\nche il patto di riservato dominio è stato fatto constare dalla nota di trascrizione dell'atto di compravendita, ai sensi dell'art. 2659 del C.C.;", 'suggerimento_ruolo': 'Parte Acquirente'},
        #{'nome_clausola': 'Pagamento effettuato e intenzione di saldo', 'testo_clausola': 'che il signor UBALDI MASSIMO UBALDO ha già provveduto in data 27 maggio 2022 al pagamento della somma di Euro 15.000,00 (quindicimila virgola zero zero) mediante un bonifico bancario eseguito per il tramite della Banca Monte dei Paschi di Siena S.p.A., CRO A102072973501030483421134210IT, ed intende ora procedere al pagamento del residuo importo di Euro 30.000,00 (trentamila virgola zero zero);', 'suggerimento_ruolo': 'Parte Acquirente'},
        #{'nome_clausola': "Necessità di sottoscrizione dell'atto di quietanza", 'testo_clausola': "che si rende ora necessario sottoscrivere atto di quietanza al fine di consentirne l'annotamento a margine della trascrizione della compravendita ai fini della cancellazione del patto di riservato dominio per gli effetti di cui all'art. 2668.", 'suggerimento_ruolo': 'Soggetto che rilascia la quietanza'},
        #{'nome_clausola': "Integrazione dell'atto", 'testo_clausola': 'PREMESSO QUANTO SOPRA\nche costituisce parte integrante e sostanziale del presente atto,', 'suggerimento_ruolo': "Parti dell'atto"},
        #{'nome_clausola': 'Dichiarazione di ricezione del pagamento', 'testo_clausola': "la signora MATTABONI KATIA, come sopra rappresentata, dichiara di aver ricevuto dal signor UBALDI MASSIMO UBALDO la somma complessiva di Euro 45.000,00 (quarantacinquemila virgola zero zero), con le modalità di cui infra e in dipendenza di quanto sopra la signora MATTABONI KATIA rilascia al signor UBALDI MASSIMO UBALDO, piena e definitiva quietanza a saldo dell'importo di Euro 45.000,00 (quarantacinquemila virgola zero zero), e pertanto dà atto che risulta pagato l'intero prezzo della vendita con patto di riservato dominio di cui all'atto a mio rogito in data 26 maggio 2022 repertorio n. 10281/5529 citato in premessa.", 'suggerimento_ruolo': 'Parte Ricevente'},
        #{'nome_clausola': 'Trasferimento del diritto di proprietà', 'testo_clausola': 'Conseguentemente, il diritto di proprietà degli immobili compravenduti si trasferisce alla Parte Acquirente con decorrenza dalla data odierna.', 'suggerimento_ruolo': 'Parte Acquirente'},
        #{'nome_clausola': 'Annotamento e cancellazione del patto di riservato dominio', 'testo_clausola': "La Parte Venditrice consente pertanto che a margine della trascrizione della compravendita citata in premessa venga eseguito l'annotamento del presente atto ai fini della cancellazione del patto di riservato dominio per gli effetti di cui all'art. 2668.", 'suggerimento_ruolo': 'Parte Venditrice'},
        #{'nome_clausola': 'Dichiarazione di pagamento e modalità', 'testo_clausola': 'Ai sensi e per gli effetti dell\'art. 35, comma 22 del D.L. 4 luglio 2006 n. 223, convertito in legge 4 agosto 2006 n. 248, nonchè dell\'art. 1, comma 48 della Legge 27 dicembre 2006 n. 296, le Parti da me Notaio ammonite sulle conseguenze delle dichiarazioni mendaci previste dall\'art. 76 del D.P.R. 28 dicembre 2000 n. 445, ai sensi e per gli effetti dell\'art. 47 del D.P.R. sopracitato e a conoscenza dei poteri di accertamento dell\'amministrazione finanziaria e delle conseguenze di una incompleta o mendace indicazione dei dati, dichiarano che il saldo prezzo di cui sopra è stato corrisposto come segue: quanto ad Euro 15.000,00 (quindicimila virgola zero zero) mediante il bonifico di cui in premessa; quanto ai residui Euro 30.000,00 (trentamila virgola zero zero) mediante un assegno circolare "non trasferibile" n. 6081668787-12 di corrispondente importo emesso dalla Banca Monte Dei Paschi di Siena S.p.A., in data 2 ottobre 2024 all\'ordine di MATTABONI KATIA.', 'suggerimento_ruolo': 'Parte Debitrice'},
        #{'nome_clausola': 'Spese a carico della Parte Acquirente', 'testo_clausola': 'Tutte le spese inerenti e conseguenti a questo atto sono a carico della Parte Acquirente.', 'suggerimento_ruolo': 'Parte Acquirente'},
        #{'nome_clausola': 'Dispensa dalla lettura degli allegati', 'testo_clausola': 'I comparenti dichiarano di essere a conoscenza di quanto allegato e perciò dispensano me Notaio dal darne lettura.', 'suggerimento_ruolo': 'Parte Interessata'},
        #{'nome_clausola': "Approvazione dell'atto", 'testo_clausola': "Richiesto io Notaio ho ricevuto quest'atto da me letto ai comparenti che lo approvano dichiarandolo conforme alla loro volontà.", 'suggerimento_ruolo': "Il soggetto che approva l'atto"},
        #{'nome_clausola': "Redazione dell'atto", 'testo_clausola': "Quest'atto è scritto in parte da persona di mia fiducia ed in parte da me Notaio su sei pagine di due fogli fin qui.", 'suggerimento_ruolo': "Il soggetto che redige l'atto"},
        #{'nome_clausola': "Sottoscrizione dell'atto", 'testo_clausola': 'Viene sottoscritto alle ore nove e trenta.\nF.ti: LIGARI SIMONE\nMASSIMO UBALDO UBALDI\nDEMETRIO RANDO Notaio', 'suggerimento_ruolo': "Il soggetto che sottoscrive l'atto"}
    #]

    return clausole, clausole_e_ruolo
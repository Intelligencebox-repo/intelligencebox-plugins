import asyncio
import json
from typing import List, Dict, Any, Optional

# Importa la funzione per chattare con l'AI
from .chatbox import chat_box


PROMPT_1_3 = """
Sei un analista legale. Il tuo compito è analizzare un blocco di testo estratto da una sezione di un atto notarile e descriverne i contenuti e lo scopo.

All'interno del tag `<SEZIONE>` troverai una coppia di informazioni:
- Il "nome_clausola" che contiene un titolo che ho dato io alla sezione;
- Il "testo_clausola" che contiene il testo della clausola che dovrai analizzare.

**ISTRUZIONI:**
1.  Leggi attentamente il "testo_clausola".
2.  Descrivi in una singola frase cosa contiene il testo.
3.  Descrivi lo scopo di questa sezione (perché in un atto notarile viene inserita questa sezione?).

**OUTPUT:**
Restituisci solo ed esclusivamente un oggetto JSON con tre chiavi:
* `"nome_clausola"`: riporta esattamente il "nome_clausola";
* `"descrizione"`: la stringa con la descrizione del contenuto di "testo_clausola";
* `"scopo"`: la stringa con lo scopo della sezione.

<SEZIONE>
- "nome_clausola":
{nome_clausola}


- "testo_clausola":
{testo_clausola}
</SEZIONE>
"""


async def run_step1_3(clausole: str):
    """
    Arricchisce ogni clausola con 'descrizione' e 'scopo'.

    Args:
        clausole: La lista di clausole (dizionari con 'nome_clausola' e 'testo_clausola').

    Returns:
        Una NUOVA lista di dizionari, dove ogni dizionario contiene 'nome_clausola', 'descrizione', e 'scopo'.
        Restituisce None in caso di errore grave.
    """
    clausole_scopo: List[Dict[str, Any]] = []
    tasks = []

    for clause in clausole:
        nome_clausola = clause.get('nome_clausola')
        testo_clausola = clause.get('testo_clausola')

        prompt1_3 = PROMPT_1_3.format(nome_clausola=nome_clausola, testo_clausola=testo_clausola)
        tasks.append((nome_clausola, chat_box(prompt1_3)))

    try:
        coroutines = [task[1] for task in tasks]
        responses = await asyncio.gather(*coroutines)

        for i, response in enumerate(responses):
            clausola_elaborata = tasks[i][0]

            if not response or not isinstance(response, dict) or 'descrizione' not in response or 'scopo' not in response:
                print("Errore nello Step 1.3: risposta vuota o non dizionario o con chiavi sbagliate.")
                # Salvo comunque la clausola senza descrizione e scopo
                clausole_scopo.append({
                    "nome_clausola": clausola_elaborata,
                    "descrizione": "ERRORE: nessuna descrizione disponibile",
                    "scopo": "ERRORE: nessuno scopo disponibile"
                })
                continue

            descrizione = response['descrizione']
            scopo = response['scopo']
            # Aggiungi il dizionario con i dati corretti alla lista
            clausole_scopo.append({
                "nome_clausola": clausola_elaborata, 
                "descrizione": descrizione,
                "scopo": scopo
            })

    except Exception as e:
        print(f"ERRORE nello step 1.3 (asyncio.gather o processing): {e}")
        return None
    
    print("Response Step 1.3:", clausole_scopo)   # Debug
    #clausole_scopo = [
        #{'nome_clausola': "Intestazione dell'atto", 'descrizione': "Il testo contiene i dati di repertorio, raccolta e la denominazione dell'atto notarile, identificandolo ufficialmente come un atto di quietanza della Repubblica Italiana.", 'scopo': "Fornire un'identificazione ufficiale e formale dell'atto notarile, attestandone la validità e la provenienza, e indicare che si tratta di una quietanza riconosciuta dallo Stato italiano."},
        #{'nome_clausola': "Data e luogo dell'atto", 'descrizione': "Indica la data e il luogo in cui si svolge l'atto notarile, specificando l'anno, il giorno, il mese e la località.", 'scopo': "Fornire le informazioni temporali e geografiche essenziali per identificare e contestualizzare l'atto notarile."},
        #{'nome_clausola': 'Identificazione del Notaio', 'descrizione': "Il testo indica l'identificazione del notaio che redige l'atto, specificando nome, ruolo e iscrizione professionale.", 'scopo': "Lo scopo di questa sezione è di identificare ufficialmente il notaio che redige e autentica l'atto, conferendo validità legale al documento."},
        #{'nome_clausola': 'Identificazione del Comparente 1', 'descrizione': "Il testo identifica e descrive i dati personali e la qualità del comparente, in questo caso un procuratore speciale, che partecipa all'atto notarile.", 'scopo': "Questa sezione serve a identificare ufficialmente il comparente, fornendo le sue generalità e la sua qualità, per garantire la validità e la trasparenza dell'atto notarile."},
        #{'nome_clausola': 'Identificazione del Rappresentato', 'descrizione': "Il testo contiene i dati anagrafici, di residenza, fiscale e lo stato civile di una persona, nonché la dichiarazione di rappresentanza tramite procura speciale allegata all'atto.", 'scopo': 'Questa sezione ha lo scopo di identificare ufficialmente il soggetto rappresentato, fornendo tutte le informazioni necessarie per la sua corretta individuazione e attestando la validità della procura allegata.'},
        #{'nome_clausola': 'Identificazione del Comparente 2', 'descrizione': 'Il testo identifica e fornisce i dati anagrafici, di residenza, fiscale e lo stato civile del comparente UBALDI MASSIMO UBALDO, specificando anche il regime patrimoniale coniugale.', 'scopo': "Questa sezione ha lo scopo di identificare ufficialmente il comparente, fornendo tutte le informazioni necessarie per la sua corretta individuazione e per attestare la sua condizione civile e patrimoniale nel contesto dell'atto notarile."},
        #{'nome_clausola': 'Dichiarazione di Identità', 'descrizione': "Il testo afferma che i comparenti, di cui il notaio è certo dell'identità, convengono e stipulano quanto segue.", 'scopo': "Questa sezione serve a attestare e confermare l'identità delle parti coinvolte nel atto notarile, garantendo la validità e la certezza dell'identità dei soggetti che stipulano l'accordo."},
        #{'nome_clausola': "Dettagli dell'atto di compravendita", 'descrizione': "Il testo descrive i dettagli formali e le parti coinvolte in un atto di compravendita immobiliare, specificando data, repertorio, registrazione e trascrizione dell'atto, nonché le parti e l'oggetto della vendita.", 'scopo': "Questa sezione ha lo scopo di attestare ufficialmente i dettagli dell'atto di compravendita, garantendo la validità legale e la pubblicità dell'operazione immobiliare."},
        #{'nome_clausola': 'Descrizione degli immobili', 'descrizione': 'Il testo fornisce dettagli specifici riguardanti la descrizione catastale di alcuni immobili, inclusi fogli, mappali, subalterni, ubicazione, categoria, consistenza, superficie e rendita catastale.', 'scopo': 'Questa sezione ha lo scopo di identificare e descrivere dettagliatamente gli immobili oggetto di trasferimento o di altri atti, garantendo chiarezza e precisione nella loro individuazione legale e catastale.'},
        #{'nome_clausola': 'Condizioni di pagamento', 'descrizione': 'Il testo dettaglia le modalità e le scadenze di pagamento di un prezzo di Euro 50.000,00, suddiviso in una somma già versata, una da versare entro sette giorni e una da versare entro gennaio 2025, senza interessi.', 'scopo': "Questa sezione ha lo scopo di definire le modalità, le scadenze e le condizioni di pagamento tra le parti coinvolte nell'atto notarile, garantendo chiarezza sugli importi e sui tempi di versamento."},
        #{'nome_clausola': 'Patto di riservato dominio', 'descrizione': 'Il testo descrive un accordo tra le parti secondo cui il trasferimento della proprietà dei beni oggetto di compravendita avviene solo dopo il pagamento completo del prezzo, e ne attesta la registrazione mediante nota di trascrizione.', 'scopo': 'Lo scopo di questa sezione è di stabilire e formalizzare il patto di riservato dominio, tutelando il venditore fino al pagamento integrale del prezzo e rendendo ufficiale tale accordo attraverso la trascrizione nei registri immobiliari o catastali.'},
        #{'nome_clausola': 'Pagamento effettuato e intenzione di saldo', 'descrizione': 'Il testo indica che il signor UBALDI MASSIMO UBALDO ha già effettuato un pagamento di 15.000 euro e intende ora pagare il residuo di 30.000 euro, specificando i dettagli del pagamento precedente.', 'scopo': "Questa sezione serve a attestare lo stato dei pagamenti già effettuati e a chiarire l'importo residuo ancora da saldare, per documentare formalmente l'adempimento delle obbligazioni finanziarie tra le parti."},
        #{'nome_clausola': "Necessità di sottoscrizione dell'atto di quietanza", 'descrizione': 'ERRORE: nessuna descrizione disponibile', 'scopo': 'ERRORE: nessuno scopo disponibile'}, # Errore
        #{'nome_clausola': "Integrazione dell'atto", 'descrizione': 'Il testo afferma che quanto precedentemente esposto costituisce parte integrante e sostanziale del presente atto notarile.', 'scopo': "Lo scopo di questa sezione è di integrare e confermare che le dichiarazioni o contenuti precedenti sono parte integrante dell'atto, garantendo la loro validità e riconoscimento nel documento notarile."},
        #{'nome_clausola': 'Dichiarazione di ricezione del pagamento', 'descrizione': "Il testo contiene la dichiarazione della ricezione di una somma di denaro da parte di una persona, con la relativa quietanza e conferma del pagamento dell'intero prezzo di una vendita.", 'scopo': "Questa sezione ha lo scopo di attestare formalmente il pagamento effettuato, garantendo la prova dell'avvenuto saldo e liberando le parti da ulteriori obblighi relativi alla somma pagata."},
        #{'nome_clausola': 'Trasferimento del diritto di proprietà', 'descrizione': 'Il testo stabilisce che il diritto di proprietà sugli immobili venduti viene trasferito alla parte acquirente a partire dalla data odierna.', 'scopo': "Questa sezione ha lo scopo di formalizzare e rendere efficace il trasferimento della proprietà immobiliare dal venditore all'acquirente, specificando il momento in cui avviene il passaggio di diritti."},
        #{'nome_clausola': 'Annotamento e cancellazione del patto di riservato dominio', 'descrizione': "Il testo autorizza l'annotamento dell'atto di compravendita ai fini della cancellazione del patto di riservato dominio, ai sensi dell'art. 2668.", 'scopo': "Questa sezione ha lo scopo di autorizzare formalmente l'annotamento e la cancellazione del patto di riservato dominio, garantendo la regolarità e la trasparenza delle formalità pubblicitarie relative alla proprietà."},
        #{'nome_clausola': 'Dichiarazione di pagamento e modalità', 'descrizione': 'Il testo contiene una dichiarazione delle parti, resa davanti al notaio, riguardante il pagamento del saldo prezzo di una transazione, specificando le modalità di pagamento e richiamando norme di legge e responsabilità in caso di dichiarazioni mendaci.', 'scopo': "Lo scopo di questa sezione è attestare formalmente, davanti al notaio, che le parti hanno dichiarato di aver effettuato il pagamento del prezzo secondo le modalità concordate, garantendo la validità e la trasparenza dell'operazione e tutelando le parti e il notaio da eventuali contestazioni future."},
        #{'nome_clausola': 'Spese a carico della Parte Acquirente', 'descrizione': "Il testo stabilisce che tutte le spese relative e derivanti dall'atto sono a carico della Parte Acquirente.", 'scopo': "Questa sezione serve a definire e chiarire quale parte si farà carico delle spese connesse all'atto notarile, per evitare future contestazioni o ambiguità."},
        #{'nome_clausola': 'Dispensa dalla lettura degli allegati', 'descrizione': 'I comparenti dichiarano di essere a conoscenza di quanto allegato e dispensano il Notaio dal leggerlo ad alta voce.', 'scopo': 'Questo sezione serve a attestare che le parti sono informate e consenzienti riguardo agli allegati, evitando la necessità di una loro lettura pubblica da parte del Notaio.'},
        #{'nome_clausola': "Approvazione dell'atto", 'descrizione': "Il testo indica che il notaio ha letto l'atto ai comparenti e questi lo approvano dichiarandolo conforme alla loro volontà.", 'scopo': "Questa sezione serve a attestare che i soggetti coinvolti hanno letto, compreso e approvato l'atto, confermando la volontà delle parti e la conformità del documento."},
        #{'nome_clausola': "Redazione dell'atto", 'descrizione': "Il testo indica che l'atto è stato redatto in parte da una persona di fiducia e in parte dal Notaio, e specifica la lunghezza e la quantità di pagine dell'atto.", 'scopo': "Questa sezione ha lo scopo di attestare la modalità e le persone coinvolte nella redazione dell'atto notarile, garantendo la sua autenticità e correttezza formale."},
        #{'nome_clausola': "Sottoscrizione dell'atto", 'descrizione': "Il testo indica l'orario di sottoscrizione dell'atto e le firme dei soggetti coinvolti, inclusa quella del notaio.", 'scopo': "Questa sezione serve a attestare la data, l'ora e la validità della sottoscrizione dell'atto da parte delle parti e del notaio, confermando la sua autenticità."}
    #]

    return clausole_scopo
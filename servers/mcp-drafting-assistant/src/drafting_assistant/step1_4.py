import asyncio
import json
from typing import List, Dict, Any, Optional

# Importa la funzione per chattare con l'AI
from .chatbox import chat_box


PROMPT_1_4 = """
Sei un software di analisi di documenti legali. Il tuo compito è analizzare un blocco di testo estratto da una sezione di un atto notarile, identificare le parti variabili, sostituirle con segnaposto e descrivere cosa rappresentano.

All'interno del tag `<SEZIONE>` troverai una coppia di informazioni:
- Il "nome_clausola" che contiene un titolo che ho dato io alla sezione;
- Il "testo_clausola" che contiene il testo della sezione che dovrai analizzare.

**ISTRUZIONI:**
1.  Leggi attentamente il "testo_clausola".
2.  Identifica tutte le informazioni che sono specifiche di questo caso (nomi, date, importi, indirizzi, dati catastali, riferimenti ad altri atti, ecc.). ATTENZIONE: i riferimenti a leggi, decreti, articoli e commi NON sono informazioni specifiche del caso, ma fanno parte del testo standard. Non devi trasformarli in segnaposto.
3.  Riscrivi l'intero testo della clausola, ma sostituisci ogni dato variabile che hai trovato con un segnaposto descrittivo tra parentesi quadre (es. `[NOME_COMPLETO_VENDITORE]`, `[DATA_ATTO]`). Se in una clausola non ci sono dati variabili, restituisci il testo originale.
4.  Crea un oggetto JSON che descriva ogni segnaposto che hai creato. La chiave deve essere il nome del segnaposto (senza parentesi) e il valore deve essere una breve descrizione di cosa rappresenta quel dato. Se non hai creato segnaposto, restituisci un oggetto JSON vuoto `{{}}`.

**OUTPUT:**
Restituisci **solo ed esclusivamente** un oggetto JSON con tre chiavi:
* `"nome_clausola"`: riporta esattamente il "nome_clausola" che hai ricevuto in input.
* `"testo_template"`: la stringa di testo con i segnaposto (o il testo originale se non ci sono dati variabili).
* `"dettaglio_variabili"`: l'oggetto JSON con la descrizione di ogni segnaposto (può essere vuoto se non ci sono variabili `{{}}`).

**ESEMPIO DI OUTPUT:**
{{
  "nome_clausola": "Dati anagrafici del procuratore (LIGARI SIMONE)",
  "testo_template": "[NOME_COMPLETO], nato a [LUOGO_NASCITA] il giorno [DATA_NASCITA], residente a [CITTA_RESIDENZA], [INDIRIZZO_RESIDENZA],",
  "dettaglio_variabili": {{
    "NOME_COMPLETO": "Il nome e cognome completo del procuratore.",
    "LUOGO_NASCITA": "La città o il comune di nascita del procuratore.",
    "DATA_NASCITA": "La data di nascita completa, scritta per esteso (es. '6 gennaio 1992') del procuratore.",
    "CITTA_RESIDENZA": "La città o il comune di residenza del procuratore.",
    "INDIRIZZO_RESIDENZA": "L'indirizzo completo di residenza (inclusi via e numero civico) del procuratore."
  }}
}}

<SEZIONE>
- "nome_clausola":
{nome_clausola}


- "testo_clausola":
{testo_clausola}
</SEZIONE>
"""


async def run_step1_4(clausole: List[Dict[str, str]]) -> Optional[List[Dict[str, Any]]]:
    """
    Trasforma ogni clausola in un template (come nu testo bucato) con spiegazioni sulle informazioni da inserire negli spazi.
    
    Args:
    clausole: La lista di clausole (dizionari con 'nome_clausola' e 'testo_clausola').

    Returns:
        Una NUOVA lista di dizionari, dove ogni dizionario contiene 'nome_clausola', 'testo_template', e 'dettaglio_variabili'.
        Restituisce None in caso di errore grave.
    """
    clausole_template: List[Dict[str, Any]] = []
    tasks = []

    for clause in clausole:
        nome_clausola = clause.get('nome_clausola')
        testo_clausola = clause.get('testo_clausola')

        prompt1_4 = PROMPT_1_4.format(nome_clausola=nome_clausola, testo_clausola=testo_clausola)
        tasks.append((nome_clausola, chat_box(prompt1_4)))
    
    # --- Esecuzione Parallela e Processamento Risultati ---
    try:
        coroutines = [task[1] for task in tasks]
        responses = await asyncio.gather(*coroutines)

        for i, response in enumerate(responses):
            clausola_elaborata = tasks[i][0] # Recupera il nome 
            
            if not response or not isinstance(response, dict) or 'testo_template' not in response or 'dettaglio_variabili' not in response:
                print("Errore nello Step 1.4: risposta vuota o non dizionario o con chiavi sbagliate.")
                # Salvo comunque la clausola senza descrizione e scopo
                clausole_template.append({
                    "nome_clausola": clausola_elaborata,
                    "testo_template": "ERRORE: nessun template disponibile",
                    "dettaglio_variabili": {"ERRORE": "nessuna variabile disponibile"}
                })
                continue

            testo_template = response['testo_template']
            dettaglio_variabili = response['dettaglio_variabili']
            # Aggiungi il risultato alla lista finale
            clausole_template.append({
                "nome_clausola": clausola_elaborata,
                "testo_template": testo_template,
                "dettaglio_variabili": dettaglio_variabili
            })

    except Exception as e:
        print(f"ERRORE nello step 1.4 (asyncio.gather o processing): {e}")
        return None
    
    print("Response Step 1.4:", clausole_template)   # Debug
    #clausole_template = [
        #{'nome_clausola': "Intestazione dell'atto", 'testo_template': 'REPERTORIO N. [NUMERO_REPERTORIO]\nRACCOLTA N. [NUMERO_RACCOLTA]\nATTO DI QUIETANZA\nREPUBBLICA ITALIANA', 'dettaglio_variabili': {'NUMERO_REPERTORIO': "Il numero di repertorio assegnato all'atto.", 'NUMERO_RACCOLTA': "Il numero di raccolta dell'atto."}},
        #{'nome_clausola': "Data e luogo dell'atto", 'testo_template': "L'anno [ANNO_ATTO], il giorno [GIORNO_ATTO], del mese di [MESE_ATTO], in [CITTA_ATTO], nel mio Studio in [INDIRIZZO_STUDIO].", 'dettaglio_variabili': {'ANNO_ATTO': "L'anno in cui è stato redatto l'atto (ad esempio '2024').", 'GIORNO_ATTO': "Il giorno del mese in cui è stato redatto l'atto (ad esempio '4').", 'MESE_ATTO': "Il mese in cui è stato redatto l'atto (ad esempio 'ottobre').", 'CITTA_ATTO': "La città o il luogo in cui è stato redatto l'atto (ad esempio 'Sondrio').", 'INDIRIZZO_STUDIO': "L'indirizzo completo dello studio notarile o del professionista che redige l'atto (ad esempio 'Via Stelvio n. 12')."}},
        #{'nome_clausola': 'Identificazione del Notaio', 'testo_template': 'Avanti a me [NOME_NOTAIO], Notaio in [CITTA_NOTAIO], iscritto nel Ruolo del Collegio Notarile del Distretto di [DISTRETTO_NOTARILE],', 'dettaglio_variabili': {'NOME_NOTAIO': 'Il nome completo del notaio.', 'CITTA_NOTAIO': 'La città o il luogo in cui esercita il notaio.', 'DISTRETTO_NOTARILE': 'Il distretto del collegio notarile di appartenenza del notaio.'}},
        #{'nome_clausola': 'Identificazione del Comparente 1', 'testo_template': 'sono personalmente comparsi i signori: [NOME_COMPLETO], nato a [LUOGO_NASCITA] il giorno [DATA_NASCITA], residente a [CITTA_RESIDENZA], [INDIRIZZO_RESIDENZA], il quale interviene al presente atto nella sua qualità di procuratore speciale della signora:', 'dettaglio_variabili': {'NOME_COMPLETO': 'Il nome e cognome completo del comparente.', 'LUOGO_NASCITA': 'La città o il comune di nascita del comparente.', 'DATA_NASCITA': "La data di nascita completa, scritta per esteso (es. '6 gennaio 1992') del comparente.", 'CITTA_RESIDENZA': 'La città o il comune di residenza del comparente.', 'INDIRIZZO_RESIDENZA': "L'indirizzo completo di residenza (inclusi via e numero civico) del comparente."}},
        #{'nome_clausola': 'Identificazione del Rappresentato', 'testo_template': '([NOME_COMPLETO]), nata a ([LUOGO_NASCITA]) il giorno ([DATA_NASCITA]), residente a ([CITTA_RESIDENZA]), ([INDIRIZZO_RESIDENZA]), codice fiscale ([CODICE_FISCALE]), la quale, a mezzo del procuratore, dichiara di essere di stato civile ([STATO_CIVILE]), giusta procura speciale a mio rogito in data ([DATA_PROCURATORIA]) repertorio n. ([NUMERO_REPERTORIO]), che in originale si allega al presente atto sotto la lettera "A", quale parte integrante e sostanziale;', 'dettaglio_variabili': {'NOME_COMPLETO': 'Il nome e cognome completo del rappresentato.', 'LUOGO_NASCITA': 'La città o il comune di nascita del rappresentato.', 'DATA_NASCITA': "La data di nascita completa, scritta per esteso (es. '13 marzo 1972') del rappresentato.", 'CITTA_RESIDENZA': 'La città o il comune di residenza del rappresentato.', 'INDIRIZZO_RESIDENZA': "L'indirizzo completo di residenza (inclusi via e numero civico) del rappresentato.", 'CODICE_FISCALE': 'Il codice fiscale del rappresentato.', 'STATO_CIVILE': 'Lo stato civile del rappresentato (es. libero, coniugato, divorziato, ecc.).', 'DATA_PROCURATORIA': 'La data del rogito in cui è stata rilasciata la procura.', 'NUMERO_REPERTORIO': 'Il numero di repertorio del rogito notarile.'}},
        #{'nome_clausola': 'Identificazione del Comparente 2', 'testo_template': '[NOME_COMPLETO], nato a [LUOGO_NASCITA] il giorno [DATA_NASCITA], residente a [CITTA_RESIDENZA], [INDIRIZZO_RESIDENZA], codice fiscale [CODICE_FISCALE], il quale dichiara di essere coniugato in regime di [REGIME_CONIUGALE] in quanto [STATO_CIVILE].', 'dettaglio_variabili': {'NOME_COMPLETO': 'Il nome e cognome completo del comparente.', 'LUOGO_NASCITA': 'La città o il comune di nascita del comparente.', 'DATA_NASCITA': "La data di nascita completa, scritta per esteso (es. '5 settembre 1959') del comparente.", 'CITTA_RESIDENZA': 'La città o il comune di residenza del comparente.', 'INDIRIZZO_RESIDENZA': "L'indirizzo completo di residenza (inclusi via e numero civico) del comparente.", 'CODICE_FISCALE': 'Il codice fiscale del comparente.', 'REGIME_CONIUGALE': "Il regime patrimoniale tra coniugi (es. 'separazione dei beni').", 'STATO_CIVILE': "Lo stato civile del comparente (es. 'coniugato', 'celibe', etc.)."}},
        #{'nome_clausola': 'Dichiarazione di Identità', 'testo_template': 'Detti comparenti, della cui identità personale io Notaio sono certo, convengono e stipulano quanto segue:', 'dettaglio_variabili': {}},
        #{'nome_clausola': "Dettagli dell'atto di compravendita", 'testo_template': 'che con atto di compravendita a mio rogito in data [DATA_ATTO], repertorio n. [NUMERO_REPERTORIO], registrato a [COMUNE_REGISTRAZIONE] il [DATA_REGISTRAZIONE] al n. [NUMERO_REGISTRAZIONE], serie [SERIE_REGISTRAZIONE] e trascritto a [COMUNE_TRASCRIZIONE] il [DATA_TRASCRIZIONE] al n. [NUMERO_TRASCRIZIONE] Reg. Part., la signora [NOME_VENDITORE] [COGNOME_VENDITORE] in seguito, per brevità, denominata anche "Parte Venditrice", ha venduto, con patto di riservato dominio ai sensi degli artt. 1523 e seguenti del C.C. al signor [NOME_ACQUIRENTE] [COGNOME_ACQUIRENTE], in seguito, per brevità, denominato anche "Parte Acquirente" la piena proprietà degli immobili siti in [COMUNE_IMMOBILE], posti in [INDIRIZZO_IMMOBILE] e censiti in Catasto Fabbricati a:', 'dettaglio_variabili': {'DATA_ATTO': "La data dell'atto di compravendita (giorno, mese, anno).", 'NUMERO_REPERTORIO': "Il numero di repertorio dell'atto presso l'ufficio notarile.", 'COMUNE_REGISTRAZIONE': "Il comune dove è stato registrato l'atto.", 'DATA_REGISTRAZIONE': "La data di registrazione dell'atto (giorno, mese, anno).", 'NUMERO_REGISTRAZIONE': "Il numero di registrazione dell'atto.", 'SERIE_REGISTRAZIONE': "La serie di registrazione dell'atto.", 'COMUNE_TRASCRIZIONE': "Il comune dove è stata trascritta l'annotazione.", 'DATA_TRASCRIZIONE': 'La data di trascrizione (giorno, mese, anno).', 'NUMERO_TRASCRIZIONE': 'Il numero di trascrizione.', 'NOME_VENDITORE': 'Il nome del venditore.', 'COGNOME_VENDITORE': 'Il cognome del venditore.', 'NOME_ACQUIRENTE': "Il nome dell'acquirente.", 'COGNOME_ACQUIRENTE': "Il cognome dell'acquirente.", 'COMUNE_IMMOBILE': 'Il comune in cui si trovano gli immobili.', 'INDIRIZZO_IMMOBILE': "L'indirizzo completo degli immobili (via, numero civico, ecc.)."}},
        #{'nome_clausola': 'Descrizione degli immobili', 'testo_template': 'Foglio [FOGLIO_1] ([FOGLIO_1_LETTERE]) mappale numero [MAPPALE_1] ([MAPPALE_1_LETTERE]) subalterno [SUBALTERNO_1] ([SUBALTERNO_1_LETTERE]) [INDIRIZZO_1] piano [PIANO_1] categoria [CATEGORIA_1] cl. [CLASSE_1] consistenza vani [VANI_1] (superficie catastale Totale mq. [SUPERFICIE_TOTALE_1] Totale escluse aree scoperte mq. [SUPERFICIE_ESCLUSE_1]) RC. Euro [RENDITA_CATASTALE_1]\ngraffato con\nFoglio [FOGLIO_2] ([FOGLIO_2_LETTERE]) mappale numero [MAPPALE_2] ([MAPPALE_2_LETTERE]) subalterno [SUBALTERNO_2] ([SUBALTERNO_2_LETTERE]);\nFoglio [FOGLIO_3] ([FOGLIO_3_LETTERE]) mappale numero [MAPPALE_3] ([MAPPALE_3_LETTERE]) subalterno [SUBALTERNO_3] ([SUBALTERNO_3_LETTERE]) [INDIRIZZO_3] piano [PIANO_3] categoria [CATEGORIA_3] cl. [CLASSE_3] consistenza mq. [CONSISTENZA_3] (superficie catastale Totale mq. [SUPERFICIE_TOTALE_3]) RC. Euro [RENDITA_CATASTALE_3];', 'dettaglio_variabili': {'FOGLIO_1': 'Il numero del foglio catastale del primo immobile.', 'FOGLIO_1_LETTERE': 'Il numero del foglio catastale del primo immobile in lettere.', 'MAPPALE_1': 'Il numero del mappale del primo immobile.', 'MAPPALE_1_LETTERE': 'Il numero del mappale del primo immobile in lettere.', 'SUBALTERNO_1': 'Il numero del subalterno del primo immobile.', 'SUBALTERNO_1_LETTERE': 'Il numero del subalterno del primo immobile in lettere.', 'INDIRIZZO_1': "L'indirizzo del primo immobile.", 'PIANO_1': 'Il piano del primo immobile.', 'CATEGORIA_1': 'La categoria catastale del primo immobile.', 'CLASSE_1': 'La classe catastale del primo immobile.', 'VANI_1': 'La consistenza in vani del primo immobile.', 'SUPERFICIE_TOTALE_1': 'La superficie catastale totale del primo immobile.', 'SUPERFICIE_ESCLUSE_1': 'La superficie escluse aree scoperte del primo immobile.', 'RENDITA_CATASTALE_1': 'La rendita catastale del primo immobile.', 'FOGLIO_2': 'Il numero del foglio catastale del secondo immobile (graffato).', 'FOGLIO_2_LETTERE': 'Il numero del foglio catastale del secondo immobile in lettere.', 'MAPPALE_2': 'Il numero del mappale del secondo immobile (graffato).', 'MAPPALE_2_LETTERE': 'Il numero del mappale del secondo immobile in lettere.', 'SUBALTERNO_2': 'Il numero del subalterno del secondo immobile (graffato).', 'SUBALTERNO_2_LETTERE': 'Il numero del subalterno del secondo immobile in lettere.', 'FOGLIO_3': 'Il numero del foglio catastale del terzo immobile.', 'FOGLIO_3_LETTERE': 'Il numero del foglio catastale del terzo immobile in lettere.', 'MAPPALE_3': 'Il numero del mappale del terzo immobile.', 'MAPPALE_3_LETTERE': 'Il numero del mappale del terzo immobile in lettere.', 'SUBALTERNO_3': 'Il numero del subalterno del terzo immobile.', 'SUBALTERNO_3_LETTERE': 'Il numero del subalterno del terzo immobile in lettere.', 'INDIRIZZO_3': "L'indirizzo del terzo immobile.", 'PIANO_3': 'Il piano del terzo immobile.', 'CATEGORIA_3': 'La categoria catastale del terzo immobile.', 'CLASSE_3': 'La classe catastale del terzo immobile.', 'CONSISTENZA_3': 'La consistenza in mq del terzo immobile.', 'SUPERFICIE_TOTALE_3': 'La superficie catastale totale del terzo immobile.', 'RENDITA_CATASTALE_3': 'La rendita catastale del terzo immobile.'}},
        #{'nome_clausola': 'Condizioni di pagamento', 'testo_template': "per il prezzo di Euro [PREZZO_CIFRE] ([PREZZO_LETTERE]) che veniva regolato come segue:\n= quanto ad Euro [IMPORTO_1_CIFRE] ([IMPORTO_1_LETTERE]) sono stati versati alla Parte Venditrice dalla Parte Acquirente con mezzi di pagamento già indicati nell'atto di compravendita e per detta somma la Parte Venditrice ha già rilasciato quietanza alla Parte Acquirente;\n= quanto a Euro [IMPORTO_2_CIFRE] ([IMPORTO_2_LETTERE]) la Parte Acquirente si obbligava a versarli alla Parte Venditrice, senza interessi, entro [GIORNI_2] ([GIORNI_2_LETTERE]) giorni dalla data del [DATA_RIF_2] ([DATA_RIF_2_LETTERE]);\n= quanto a Euro [IMPORTO_3_CIFRE] ([IMPORTO_3_LETTERE]) la Parte Acquirente si obbligava a versarli alla Parte Venditrice, senza interessi, in una o più soluzioni entro il [GIORNO_3] ([GIORNO_3_LETTERE]) [MESE_3] [ANNO_3] ([ANNO_3_LETTERE]);", 'dettaglio_variabili': {'PREZZO_CIFRE': 'Il prezzo totale in cifre.', 'PREZZO_LETTERE': 'Il prezzo totale in lettere.', 'IMPORTO_1_CIFRE': 'Importo della prima tranche (già versata) in cifre.', 'IMPORTO_1_LETTERE': 'Importo della prima tranche in lettere.', 'IMPORTO_2_CIFRE': 'Importo della seconda tranche in cifre.', 'IMPORTO_2_LETTERE': 'Importo della seconda tranche in lettere.', 'GIORNI_2': 'Numero di giorni per il pagamento della seconda tranche.', 'GIORNI_2_LETTERE': 'Numero di giorni in lettere.', 'DATA_RIF_2': 'Data di riferimento per la scadenza della seconda tranche.', 'DATA_RIF_2_LETTERE': 'Data di riferimento in lettere.', 'IMPORTO_3_CIFRE': 'Importo della terza tranche in cifre.', 'IMPORTO_3_LETTERE': 'Importo della terza tranche in lettere.', 'GIORNO_3': 'Giorno di scadenza della terza tranche.', 'GIORNO_3_LETTERE': 'Giorno di scadenza in lettere.', 'MESE_3': 'Mese di scadenza della terza tranche.', 'ANNO_3': 'Anno di scadenza della terza tranche.', 'ANNO_3_LETTERE': 'Anno di scadenza in lettere.'}},
        #{'nome_clausola': 'Patto di riservato dominio', 'testo_template': "che con il citato atto a mio rogito in data [DATA_ATTO_RIF] repertorio n. [REPERTORIO_RIF] le parti pattuivano, come detto, ai sensi dell'art. 1523 e seguenti del codice civile, che il trasferimento della proprietà dei beni oggetto di compravendita si producesse solo a seguito dell'avvenuto pagamento integrale del prezzo;\nche il patto di riservato dominio è stato fatto constare dalla nota di trascrizione dell'atto di compravendita, ai sensi dell'art. 2659 del C.C.;", 'dettaglio_variabili': {'DATA_ATTO_RIF': "Data dell'atto di compravendita originale.", 'REPERTORIO_RIF': "Numero di repertorio dell'atto di compravendita originale."}},
        #{'nome_clausola': 'Pagamento effettuato e intenzione di saldo', 'testo_template': 'che il signor [NOME_ACQUIRENTE_COMPLETO] ha già provveduto in data [DATA_PAGAMENTO_PARZIALE] al pagamento della somma di Euro [IMPORTO_PAGAMENTO_PARZIALE_CIFRE] ([IMPORTO_PAGAMENTO_PARZIALE_LETTERE]) mediante un bonifico bancario eseguito per il tramite della [NOME_BANCA], CRO [CODICE_CRO], ed intende ora procedere al pagamento del residuo importo di Euro [IMPORTO_RESIDUO_CIFRE] ([IMPORTO_RESIDUO_LETTERE]);', 'dettaglio_variabili': {'NOME_ACQUIRENTE_COMPLETO': "Nome completo dell'acquirente.", 'DATA_PAGAMENTO_PARZIALE': 'Data del pagamento parziale già effettuato.', 'IMPORTO_PAGAMENTO_PARZIALE_CIFRE': 'Importo del pagamento parziale in cifre.', 'IMPORTO_PAGAMENTO_PARZIALE_LETTERE': 'Importo del pagamento parziale in lettere.', 'NOME_BANCA': 'Nome della banca che ha eseguito il bonifico.', 'CODICE_CRO': 'Codice CRO del bonifico.', 'IMPORTO_RESIDUO_CIFRE': 'Importo residuo da pagare in cifre.', 'IMPORTO_RESIDUO_LETTERE': 'Importo residuo da pagare in lettere.'}},
        #{'nome_clausola': "Necessità di sottoscrizione dell'atto di quietanza", 'testo_template': "che si rende ora necessario sottoscrivere atto di quietanza al fine di consentirne l'annotamento a margine della trascrizione della compravendita ai fini della cancellazione del patto di riservato dominio per gli effetti di cui all'art. 2668.", 'dettaglio_variabili': {}},
        #{'nome_clausola': "Integrazione dell'atto", 'testo_template': 'PREMESSO QUANTO SOPRA\nche costituisce parte integrante e sostanziale del presente atto,', 'dettaglio_variabili': {}},
        #{'nome_clausola': 'Dichiarazione di ricezione del pagamento', 'testo_template': "la signora [NOME_VENDITRICE_COMPLETO], come sopra rappresentata, dichiara di aver ricevuto dal signor [NOME_ACQUIRENTE_COMPLETO] la somma complessiva di Euro [IMPORTO_SALDO_CIFRE] ([IMPORTO_SALDO_LETTERE]), con le modalità di cui infra e in dipendenza di quanto sopra la signora [NOME_VENDITRICE_COMPLETO] rilascia al signor [NOME_ACQUIRENTE_COMPLETO], piena e definitiva quietanza a saldo dell'importo di Euro [IMPORTO_SALDO_CIFRE] ([IMPORTO_SALDO_LETTERE]), e pertanto dà atto che risulta pagato l'intero prezzo della vendita con patto di riservato dominio di cui all'atto a mio rogito in data [DATA_ATTO_RIF] repertorio n. [REPERTORIO_RIF] citato in premessa.", 'dettaglio_variabili': {'NOME_VENDITRICE_COMPLETO': 'Nome completo della venditrice.', 'NOME_ACQUIRENTE_COMPLETO': "Nome completo dell'acquirente.", 'IMPORTO_SALDO_CIFRE': 'Importo del saldo pagato in cifre.', 'IMPORTO_SALDO_LETTERE': 'Importo del saldo pagato in lettere.', 'DATA_ATTO_RIF': "Data dell'atto di compravendita originale.", 'REPERTORIO_RIF': "Numero di repertorio dell'atto di compravendita originale."}},
        #{'nome_clausola': 'Trasferimento del diritto di proprietà', 'testo_template': 'Conseguentemente, il diritto di proprietà degli immobili compravenduti si trasferisce alla Parte Acquirente con decorrenza dalla data odierna.', 'dettaglio_variabili': {}},
        #{'nome_clausola': 'Annotamento e cancellazione del patto di riservato dominio', 'testo_template': "La Parte Venditrice consente pertanto che a margine della trascrizione della compravendita citata in premessa venga eseguito l'annotamento del presente atto ai fini della cancellazione del patto di riservato dominio per gli effetti di cui all'art. 2668.", 'dettaglio_variabili': {}},
        #{'nome_clausola': 'Dichiarazione di pagamento e modalità', 'testo_template': 'Ai sensi e per gli effetti dell\'art. 35, comma 22 del D.L. 4 luglio 2006 n. 223, convertito in legge 4 agosto 2006 n. 248, nonchè dell\'art. 1, comma 48 della Legge 27 dicembre 2006 n. 296, le Parti da me Notaio ammonite sulle conseguenze delle dichiarazioni mendaci previste dall\'art. 76 del D.P.R. 28 dicembre 2000 n. 445, ai sensi e per gli effetti dell\'art. 47 del D.P.R. sopracitato e a conoscenza dei poteri di accertamento dell\'amministrazione finanziaria e delle conseguenze di una incompleta o mendace indicazione dei dati, dichiarano che il saldo prezzo di cui sopra è stato corrisposto come segue: quanto ad Euro [IMPORTO_BONIFICO_CIFRE] ([IMPORTO_BONIFICO_LETTERE]) mediante il bonifico di cui in premessa; quanto ai residui Euro [IMPORTO_ASSEGNO_CIFRE] ([IMPORTO_ASSEGNO_LETTERE]) mediante un assegno circolare "non trasferibile" n. [NUMERO_ASSEGNO] di corrispondente importo emesso dalla [NOME_BANCA] S.p.A., in data [DATA_EMISSIONE_ASSEGNO] all\'ordine di [BENEFICIARIO_ASSEGNO].', 'dettaglio_variabili': {'IMPORTO_BONIFICO_CIFRE': 'Importo pagato tramite bonifico in cifre.', 'IMPORTO_BONIFICO_LETTERE': 'Importo pagato tramite bonifico in lettere.', 'IMPORTO_ASSEGNO_CIFRE': "Importo pagato tramite assegno in cifre.", 'IMPORTO_ASSEGNO_LETTERE': "Importo pagato tramite assegno in lettere.", 'NUMERO_ASSEGNO': "Numero dell'assegno circolare.", 'NOME_BANCA': "Nome della banca emittente l'assegno.", 'DATA_EMISSIONE_ASSEGNO': "Data di emissione dell'assegno.", 'BENEFICIARIO_ASSEGNO': "Beneficiario dell'assegno."}},
        #{'nome_clausola': 'Spese a carico della Parte Acquirente', 'testo_template': 'Tutte le spese inerenti e conseguenti a questo atto sono a carico della Parte Acquirente.', 'dettaglio_variabili': {}},
        #{'nome_clausola': 'Dispensa dalla lettura degli allegati', 'testo_template': 'I comparenti dichiarano di essere a conoscenza di quanto allegato e perciò dispensano me Notaio dal darne lettura.', 'dettaglio_variabili': {}},
        #{'nome_clausola': "Approvazione dell'atto", 'testo_template': "Richiesto io Notaio ho ricevuto quest'atto da me letto ai comparenti che lo approvano dichiarandolo conforme alla loro volontà.", 'dettaglio_variabili': {}},
        #{'nome_clausola': "Redazione dell'atto", 'testo_template': "Quest'atto è scritto in parte da persona di mia fiducia ed in parte da me Notaio su [NUMERO_PAGINE] pagine di [NUMERO_FOGLI] fogli fin qui.", 'dettaglio_variabili': {'NUMERO_PAGINE': 'Numero di pagine totali.', 'NUMERO_FOGLI': 'Numero di fogli totali.'}},
        #{'nome_clausola': "Sottoscrizione dell'atto", 'testo_template': 'Viene sottoscritto alle ore [ORA_SOTTOSCRIZIONE].\nF.ti: [FIRMATARIO_1]\n[FIRMATARIO_2]\n[FIRMATARIO_NOTAIO] Notaio', 'dettaglio_variabili': {'ORA_SOTTOSCRIZIONE': 'Ora della sottoscrizione.', 'FIRMATARIO_1': 'Nome del primo firmatario.', 'FIRMATARIO_2': 'Nome del secondo firmatario.', 'FIRMATARIO_NOTAIO': 'Nome del notaio firmatario.'}}
    #]

    return clausole_template
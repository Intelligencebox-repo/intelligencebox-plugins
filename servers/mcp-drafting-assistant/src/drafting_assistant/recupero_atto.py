# Importa la funzione per chattare con l'AI
from .chatbox import chat_box


PROMPT = """
Devo scrivere la bozza di un atto notarile basandomi su un atto d'esempio.
Ho bisogno che tu cerchi nei documenti a tua diposizione e mi fornisci il testo completo di un atto da utilizzare come esempio.

L'atto che recuperi deve assolutamente essere della seguente tipologia: "{tipo_atto}".

È estremamente importante che tu mi fornisca il testo completo dell'atto d'esempio, senza tralasciare alcuna parte.

Restituisci un oggetto JSON con questa struttura: {"risposta": stringa contenente SOLAMENTE il tetso dell'atto d'esempio.}
"""

async def atto_esempio(chat_id: str, tipo_atto: str):
    """
    Recupera un atto d'esempio della tipologia richiesta dalla Box.

    Args:
        chat_id: L'ID della chat in cui avviene la conversazione.
        tipo_atto: Il tipo di atto notarile da recperare (es. 'quietanza', 'contratto di compravendita').

    Returns:
        example_act_text: Il testo completo dell'atto d'esempio recuperato.
    """
    prompt = PROMPT.format(tipo_atto=tipo_atto)
    data = await chat_box(chat_id, prompt)

    if not data or not isinstance(data, dict):
        print(f"Errore nel recuper dell'atto d'esempio")
        return None
    risposta = next((v for v in data.values() if isinstance(v, str)), None)
    if not risposta: # Se è un dict ma è vuoto o non contine una stringa
        print("Nessun testo trovato nell'oggetto JSON.")
        return None

    print("Atto d'esempio estratto:", risposta)   # Debug
    return risposta
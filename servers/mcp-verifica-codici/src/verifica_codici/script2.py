import aiohttp
import os
from dotenv import load_dotenv

load_dotenv

CHAT_URL = os.getenv("CHAT_URL")

async def recupera_percorso_file(nome_documento: str) -> str:
    """
    Contatta la Box per ottenre il percorso del file da elaborare.

    Args:
        nome_documento (str): Il nome (o titolo) del documento da recuperare.

    Returns:
        str: La risposta testuale del modello AI.
    """
    prompt = f"""
    Devi recuperare il percorso di un file nella cartella che ti ho collegato partendo dal nome di questo file.
    Guarda nel tuo database e cerca il file "{nome_documento}".

    Mi serve che mi fornisci il percorso di questo file.

    Restituisci ESCLUSIVAMENTE il percorso completo per questo file.
    Non aggiungere coommenti o informazioni non richieste.
    """

    api_url = CHAT_URL.rstrip('/')

    headers = {
        "Content-Type": "application/json"
    }

    payload = {
        "model": "local-model", 
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 150
    }

    try:
        # Usa aiohttp per fare la chiamata API asincrona
        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, headers=headers, json=payload) as response:
                response_data = await response.json()

                # Estrae il contenuto del messaggio
                return response_data["choices"][0]["message"]["content"]
                
    except aiohttp.ClientError as e:
        return f"Errore_Connessione: {str(e)}"
    except Exception as e:
        return f"Errore: {str(e)}"
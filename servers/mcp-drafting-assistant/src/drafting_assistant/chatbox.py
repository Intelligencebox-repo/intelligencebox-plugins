from openai import AsyncOpenAI
from dotenv import load_dotenv
from typing import List, Dict, Any, Optional
import json
import os

load_dotenv()
CHAT_URL = os.getenv("CHAT_URL")

# Inizializza il client asincrono per la chat
client = AsyncOpenAI(base_url=CHAT_URL, api_key="nessuna")

def parse_json(response: Optional[str]) -> Optional[Any]:

    if not response:
        return None
    try:             
        return json.loads(response)
    except json.JSONDecodeError as e:
        print(f"Errore nel parsing JSON: {e}\n Risposta ricebuta: {response}")
        return None
    except Exception as e:
        print(f"Errore generico durante il parsing: {e}")
        return None
    

async def chat_box(chat_id: str, prompt: str) -> Optional[Any]:
    """
    Funzione per comunicare con il modello nella Box.

    Args:
        chat_id (str): L'ID della chat.
        prompt (str): La richiesta.
    Returns:
        str: La risposta.
    """
    try:
        response = await client.chat.completions.create(
            model="local",
            messages=[
                {"role": "system", "content": f"Chat ID: {chat_id}"},
                {"role": "user", "content": prompt}
            ],
            temperature=0,
            response_format={"type": "json_object"}
        )

        risposta_pulita = parse_json(response.choices[0].message.content)
        return risposta_pulita
    
    except Exception as e:
        print(f"Errore durante la chiamata al modello: {e}")
        return None
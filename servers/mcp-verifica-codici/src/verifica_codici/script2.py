import aiohttp
import os
from dotenv import load_dotenv

load_dotenv()

RAG_ENDPOINT = os.getenv("RAG_ENDPOINT")

async def recupera_percorso_file(nome_documento: str, collection_id: str) -> str:
    """
    Cerca il documento nella collection usando l'endpoint RAG di Cinzia-Pro.

    Chiama POST /api/collections/query per trovare il documento tramite semantic search.

    Args:
        nome_documento (str): Il nome (o titolo) del documento da recuperare.
        collection_id (str): ID della collection dove cercare il documento.

    Returns:
        str: Il percorso completo del file trovato, oppure un messaggio di errore.
    """
    if not RAG_ENDPOINT:
        return "Errore: RAG_ENDPOINT non configurato nelle variabili d'ambiente"

    api_url = RAG_ENDPOINT.rstrip('/')

    headers = {
        "Content-Type": "application/json"
    }

    # Payload per endpoint /api/collections/query di Cinzia-Pro
    payload = {
        "query": nome_documento,              # Titolo documento dall'elenco
        "collection_name": collection_id,      # Collection dove cercare
        "search_mode": "standard",             # Modalità di ricerca
        "pipeline_version": None               # Auto-detect v1/v2
    }

    try:
        # Usa aiohttp per fare la chiamata API asincrona
        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, headers=headers, json=payload) as response:
                if response.status != 200:
                    error_text = await response.text()
                    return f"Errore_RAG: HTTP {response.status} - {error_text}"

                response_data = await response.json()

                # Estrae il file_path dal primo documento nei risultati
                # Formato risposta: {"documents": [...], "citation": [...], "total_results": N}
                if response_data.get("documents") and len(response_data["documents"]) > 0:
                    first_doc = response_data["documents"][0]

                    # Prova a estrarre file_path (può essere in vari campi)
                    file_path = (
                        first_doc.get("file_path") or
                        first_doc.get("metadata", {}).get("file_path") or
                        first_doc.get("source", "").split("#")[0]  # Rimuove anchor se presente
                    )

                    if file_path and file_path.startswith("/"):
                        return file_path
                    else:
                        return f"Errore: File_path non valido per '{nome_documento}': {file_path}"
                else:
                    return f"Errore: File '{nome_documento}' non trovato nella collection '{collection_id}'"

    except aiohttp.ClientError as e:
        return f"Errore_Connessione: {str(e)}"
    except Exception as e:
        return f"Errore: {str(e)}"
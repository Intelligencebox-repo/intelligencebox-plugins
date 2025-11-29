import json
import logging

from dotenv import load_dotenv

from .rag_client import build_query_url, perform_query

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
    query_url = build_query_url()
    if not query_url:
        return "Errore: endpoint di query non configurato (QUERY_HOST/QUERY_ENDPOINT o RAG_ENDPOINT)"
    if not collection_id:
        return "Errore: collection_id non fornito"
    logger.debug(f"[recupera_percorso_file] query endpoint: {query_url}")

    # Payload per endpoint /query di Cinzia-Pro
    payload = {
        "query": nome_documento,               # Titolo documento dall'elenco
        "collection_name": collection_id,      # Collection dove cercare
        "search_mode": "standard",             # Modalità di ricerca
        "pipeline_version": "v2"               # Force v2 pipeline (Docling text-based)
    }

    try:
        response_data = await perform_query(
            query=nome_documento,
            collection_id=collection_id,
            search_mode="standard",
            pipeline_version="v2",
            extra_payload=None,
        )

        # DEBUG: Log the full response structure
        logger.info(f"🔍 RAG RESPONSE for '{nome_documento}':")
        logger.info(f"   Response keys: {list(response_data.keys())}")
        logger.info(f"   Total results: {response_data.get('total_results', 0)}")

        # Estrae il file_path dal primo documento nei risultati
        # Formato risposta: {"documents": [...], "citation": [...], "total_results": N}
        documents = response_data.get("documents") or []
        if documents:
            first_doc = documents[0]

            # DEBUG: Log the first document structure
            logger.info(f"   First document keys: {list(first_doc.keys())}")
            logger.info(f"   file_path field: {first_doc.get('file_path')}")
            logger.info(f"   source field: {first_doc.get('source')}")
            logger.info(f"   metadata: {first_doc.get('metadata')}")

            # Prova a estrarre file_path (può essere in vari campi)
            file_path = (
                first_doc.get("file_path")
                or first_doc.get("metadata", {}).get("file_path")
                or first_doc.get("source", "").split("#")[0]  # Rimuove anchor se presente
            )

            logger.info(f"   Extracted file_path: {file_path}")

            if file_path:
                original_path = file_path

                # Normalize path: remove /files/ prefix if present (HTTP URL → filesystem path)
                if file_path.startswith("/files/"):
                    file_path = file_path.replace("/files/", "/", 1)
                    logger.info(f"   Removed /files/ prefix: {original_path} → {file_path}")

                # Ensure absolute path
                if not file_path.startswith("/"):
                    file_path = "/" + file_path
                    logger.info(f"   Added leading slash: {original_path} → {file_path}")

                logger.info(f"   ✅ Final normalized path: {file_path}")
                return file_path
            else:
                return f"Errore: File_path non valido per '{nome_documento}': {file_path}\n ==================== \n Payload: {json.dumps(payload)}"
        else:
            return f"Errore: File '{nome_documento}' non trovato nella collection '{collection_id}'\n ==================== \n Payload: {json.dumps(payload)}"

    except Exception as e:
        # Catch network / JSON errors
        return f"Errore_Connessione: {str(e)}"

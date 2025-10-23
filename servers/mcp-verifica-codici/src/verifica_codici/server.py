import asyncio
import os
from typing import List

# Import necessari da Pydantic per definire i parametri
from pydantic import BaseModel, Field

# Import necessari dal framework MCP
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.shared.exceptions import McpError
from mcp.types import Tool, ErrorData, TextContent, INTERNAL_ERROR, INVALID_PARAMS

# Import delle nostre funzioni logiche dai moduli separati
from .script1 import estrai_elenco_documenti
from .script2 import recupera_percorso_file
from .script3 import genera_immagine_pulita
from .script4 import estrai_codice_immagine
from .script5 import verifica_codici


# --- Definizione dei Parametri di Input con Pydantic ---
class VerificaCodiciParams(BaseModel):
    index_pdf_path: str = Field(..., description="Il percorso del file PDF che contiene l'elenco dei documenti da verificare.")
    codice_commessa: str = Field(..., description="Il codice della commessa da utilizzare per filtrare i documenti nell'elenco.")
    collection_id: str = Field(..., description="Collection ID dove cercare i documenti da verificare tramite RAG.")


# --- CREAZIONE DEL SERVER MCP ---
def create_verifica_codici_server() -> Server:
    """
    Crea e configura il server MCP per la verifica dei codici.
    Questa funzione può essere riutilizzata per diversi tipi di trasporto.
    """
    server = Server("verifica-codici")

    # --- REGISTRAZIONE DEL TOOL ---
    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="start_verification",
                description="Avvia il processo di verifica dei documenti a partire da un file di elenco.",
                inputSchema=VerificaCodiciParams.model_json_schema(),
            )
        ]

    # --- GESTIONE DELLA CHIAMATA AL TOOL ---
    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        if name != "start_verification":
            raise McpError(ErrorData(code=INVALID_PARAMS, message=f"Tool '{name}' non definito."))

        try:
            # Validazione dei parametri di input tramite Pydantic
            params = VerificaCodiciParams(**arguments)

            # --- ESECUZIONE DELLA LOGICA DI ORCHESTRAZIONE ---

            # STEP 1 - script1: Estrazione dell'elenco documenti
            elenco_da_controllare = await asyncio.to_thread(estrai_elenco_documenti, params.index_pdf_path, params.codice_commessa)
            if not elenco_da_controllare:
                return [TextContent(type="text", text="Verifica completata: nessun documento trovato nell'elenco fornito.")]

            risultati_negativi = []
            # Inizio ciclo di elaborazione
            for doc in elenco_da_controllare:
                titolo_documento = doc.get('titolo', 'Titolo Sconosciuto')
                
                try:
                    # STEP 2 - script2: Recupero del file specifico tramite RAG
                    percorso_file = await recupera_percorso_file(titolo_documento, params.collection_id)

                    # STEP 3 - script3: Generazione dell'immagine pulita
                    immagine_pulita = await asyncio.to_thread(genera_immagine_pulita, percorso_file)
                    if immagine_pulita is None:
                        raise ValueError("Generazione dell'immagine pulita fallita.")

                    # STEP 4 - script4: Estrazione del codice tramite Tesseract
                    codice_estratto = await asyncio.to_thread(estrai_codice_immagine, immagine_pulita)

                    # STEP 5 - script5: Verifica dei codici
                    risultato_verifica = verifica_codici(doc, codice_estratto)

                    if risultato_verifica['status'] == 'FAILED':
                        risultati_negativi.append(risultato_verifica)
                
                except Exception as e:
                    risultati_negativi.append({
                        'titolo_documento': titolo_documento,
                        'status': 'FAILED',
                        'error_details': f"Errore durante l'elaborazione: {str(e)}"
                    })
                    continue
            
            # --- Creazione del Report Finale ---
            if not risultati_negativi:
                report_finale = f"Successo! I codici di tutti i {len(elenco_da_controllare)} documenti analizzati coincidono."
            else:
                report_lines = [f"Sono stati trovati {len(risultati_negativi)} documenti con errori:"]
                for res in risultati_negativi:
                    line = (
                        f"- Titolo: {res['titolo_documento']}\n"
                        f"  Codice Atteso:   {res.get('codice_atteso', 'N/A')}\n"
                        f"  Codice Estratto: {res.get('codice_estratto', 'N/A')}"
                    )
                    report_lines.append(line)
                report_finale = "\n".join(report_lines)
                
            return [TextContent(type="text", text=report_finale)]

        except Exception as e:
            # Cattura errori di validazione Pydantic o altri errori imprevisti
            raise McpError(ErrorData(code=INTERNAL_ERROR, message=f"Errore durante l'esecuzione del tool: {e}"))

    return server


# --- FUNZIONE PRINCIPALE DEL SERVER (STDIO MODE) ---
async def serve():
    """
    Funzione principale che configura e avvia il server MCP per la verifica dei codici in modalità stdio.
    """
    server = create_verifica_codici_server()

    # --- AVVIO DEL SERVER IN MODALITÀ STDIO ---
    options = server.create_initialization_options()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, options)
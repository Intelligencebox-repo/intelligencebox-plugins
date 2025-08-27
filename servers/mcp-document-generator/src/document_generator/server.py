import os
import asyncio
from typing import Annotated

# Import necessari da Pydantic per definire i parametri
from pydantic import BaseModel, Field

# Import necessari dal framework MCP per creare il server
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.shared.exceptions import McpError
from mcp.types import Tool, ErrorData, TextContent, INTERNAL_ERROR, INVALID_PARAMS

# Import dalla libreria per creare file DOCX e pdf
import pypandoc
import markdown2
from xhtml2pdf import pisa


from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import uvicorn


# --- INIZIALIZZAZIONE DI FASTAPI ---
# Creiamo un'istanza dell'applicazione FastAPI
app = FastAPI()

# "Montiamo" la cartella 'output' come una cartella di file statici.
# Questo dice a FastAPI: "Qualsiasi richiesta all'URL '/files/...' deve cercare
# un file corrispondente nella cartella fisica './output'".
# Il percorso 'output' è relativo a dove viene eseguito lo script.
os.makedirs("output", exist_ok=True)
app.mount("/files", StaticFiles(directory="output"), name="files")

# Definiamo l'host e la porta per il nostro server web.
# Useremo '0.0.0.0' per renderlo accessibile dall'esterno del container Docker.
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 8000
BASE_URL = f"http://localhost:{SERVER_PORT}" # Useremo localhost per i test dal PC


# --- Definizione dei Parametri per gli Strumenti ---
class CreateDocxParams(BaseModel):
    """Parametri per lo strumento di creazione DOCX."""
    filename: Annotated[str, Field(description="Il nome del file DOCX da creare (es. 'report.docx').")]
    text_content: Annotated[str, Field(description="Il testo in formato Markdown da scrivere nel file.")]

class CreatePdfParams(BaseModel):
    """Parametri per lo strumento di creazione PDF."""
    filename: Annotated[str, Field(description="Il nome del file PDF da creare (es. 'report.pdf').")]
    text_content: Annotated[str, Field(description="Il testo in formato Markdown da scrivere nel file.")]


# --- Logica di Business ---
def create_docx_file(filename: str, text_content: str) -> str:
    """Crea un file DOCX convertendo il testo Markdown usando Pandoc. Salva il file sul sevrer e fornisce come risposta il link per accedervi."""
    os.makedirs("output", exist_ok=True)
    if not filename.lower().endswith(".docx"):
        filename += ".docx"
    output_path = os.path.join("output", filename)
    try:
        # Usa pypandoc per convertire il Markdown direttamente in un file DOCX
        pypandoc.convert_text(
            source=text_content,
            format='markdown',
            to='docx',
            outputfile=output_path
        )
        return f"File DOCX creato con successo. Informa l'utente che il file '{filename}' è stato creato e forniscigli esplicitamente questo link per il download: {BASE_URL}/files/{filename}"
    except Exception as e:
        raise McpError(ErrorData(code=INTERNAL_ERROR, message=f"Errore durante la creazione del DOCX con Pandoc: {e}"))
    
def create_pdf_file(filename: str, text_content: str) -> str:
    """Crea un file PDF convertendo il testo Markdown in HTML. Salva il file sul sevrer e fornisce come risposta il link per accedervi."""
    os.makedirs("output", exist_ok=True)
    if not filename.lower().endswith(".pdf"):
        filename += ".pdf"
    output_path = os.path.join("output", filename)
    try:
        # 1. Converte il testo Markdown in HTML
        html_content = markdown2.markdown(text_content, extras=["tables", "fenced-code-blocks"])
        # 2. Scrive il PDF partendo dall'HTML
        with open(output_path, "w+b") as pdf_file:
            pisa_status = pisa.CreatePDF(src=html_content, dest=pdf_file)
        if pisa_status.err:
            raise McpError(ErrorData(code=INTERNAL_ERROR, message="Errore durante la conversione da HTML a PDF."))
        return f"File PDF creato con successo. Informa l'utente che il file '{filename}' è stato creato e forniscigli esplicitamente questo link per il download: {BASE_URL}/files/{filename}"
    except Exception as e:
        raise McpError(ErrorData(code=INTERNAL_ERROR, message=f"Errore durante la creazione del PDF: {e}"))
    

# --- Logica del Server MCP ---
async def serve() -> None:
    """Avvia il server MCP per il generatore di documenti."""

    # --- NUOVA PARTE: Avvio del server web in background ---
    config = uvicorn.Config(app, host=SERVER_HOST, port=SERVER_PORT, log_level="info")
    uvicorn_server = uvicorn.Server(config)
    # Avviamo il server uvicorn come un'attività in background
    asyncio.create_task(uvicorn_server.serve())
    # --- FINE NUOVA PARTE ---


    server = Server("document-generator")

    # Registra gli strumenti
    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="create_docx",
                description="Crea un documento Word (.docx) modificabile, ideale per bozze o documenti che necessitano di successive modifiche. Salva il file sul sevrer e fornisce come risposta il link per accedervi.",
                inputSchema=CreateDocxParams.model_json_schema(),
            ),
            Tool(
                name="create_pdf",
                description="Crea un documento PDF non modificabile, ideale per report finali o documenti da stampare. Salva il file sul sevrer e fornisce come risposta il link per accedervi.",
                inputSchema=CreatePdfParams.model_json_schema(),
            )
        ]

    # Definisce come eseguire lo strumento quando viene chiamato
    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        if name == "create_docx":
            try:
                args = CreateDocxParams(**arguments)
                result_message = create_docx_file(args.filename, args.text_content)
            except ValueError as e:
                raise McpError(ErrorData(code=INVALID_PARAMS, message=f"Parametri invalidi per create_docx: {e}"))
        elif name == "create_pdf":
            try:
                args = CreatePdfParams(**arguments)
                result_message = create_pdf_file(args.filename, args.text_content)
            except ValueError as e:
                raise McpError(ErrorData(code=INVALID_PARAMS, message=f"Parametri invalidi per create_pdf: {e}"))
        else:
            # Questo non dovrebbe mai succedere se il client è corretto
            raise McpError(ErrorData(code=INVALID_PARAMS, message=f"Strumento '{name}' non conosciuto."))

        return [TextContent(type="text", text=result_message)]    

    # Avvia il server e lo mette in ascolto
    options = server.create_initialization_options()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, options)
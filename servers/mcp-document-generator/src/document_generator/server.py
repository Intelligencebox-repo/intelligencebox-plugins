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


# --- Definizione dei Parametri per gli Strumenti ---
class CreateDocxParams(BaseModel):
    """Parametri per lo strumento di creazione DOCX."""
    filename: Annotated[str, Field(description="Il nome del file DOCX da creare (es. 'report.docx').")]
    text_content: Annotated[str, Field(description="Il testo in formato Markdown da scrivere nel file.")]

class CreatePdfParams(BaseModel):
    """Parametri per lo strumento di creazione PDF."""
    filename: Annotated[str, Field(description="Il nome del file PDF da creare (es. 'report.pdf').")]
    text_content: Annotated[str, Field(description="Il testo in formato Markdown da scrivere nel file.")]


# --- CONFIGURATION ---
HOSTNAME = os.getenv("PUBLIC_HOSTNAME", "localhost")
SERVER_PORT = int(os.getenv("PORT", "8000"))
BASE_URL = f"http://{HOSTNAME}:{SERVER_PORT}"


# --- FUNZIONE HELPER per nomi di file unici ---
def get_unique_filepath(directory: str, filename: str) -> str:
    path = os.path.join(directory, filename)
    if not os.path.exists(path):
        return path

    base, extension = os.path.splitext(filename)
    counter = 1
    while True:
        new_filename = f"{base}({counter}){extension}"
        new_path = os.path.join(directory, new_filename)
        if not os.path.exists(new_path):
            return new_path
        counter += 1

# --- Logica di Business ---
def create_docx_file(filename: str, text_content: str) -> str:
    """Crea un file DOCX convertendo il testo Markdown usando Pandoc. Salva il file sul sevrer e fornisce come risposta il link per accedervi."""
    output_directory = "output"
    os.makedirs(output_directory, exist_ok=True)
    if not filename.lower().endswith(".docx"):
        filename += ".docx"
    unique_path = get_unique_filepath(output_directory, filename)
    final_filename = os.path.basename(unique_path)
    try:
        # Usa pypandoc per convertire il Markdown direttamente in un file DOCX
        pypandoc.convert_text(
            source=text_content,
            format='markdown',
            to='docx',
            outputfile=unique_path
        )
        return f"File DOCX creato con successo. Informa l'utente che il file '{final_filename}' è stato creato e forniscigli esplicitamente questo link per il download: {BASE_URL}/files/{final_filename}"
    except Exception as e:
        raise McpError(ErrorData(code=INTERNAL_ERROR, message=f"Errore durante la creazione del DOCX con Pandoc: {e}"))

def create_pdf_file(filename: str, text_content: str) -> str:
    """Crea un file PDF convertendo il testo Markdown in HTML. Salva il file sul sevrer e fornisce come risposta il link per accedervi."""
    output_directory = "output"
    os.makedirs(output_directory, exist_ok=True)
    if not filename.lower().endswith(".pdf"):
        filename += ".pdf"
    unique_path = get_unique_filepath(output_directory, filename)
    final_filename = os.path.basename(unique_path)
    try:
        # 1. Converte il testo Markdown in HTML
        html_content = markdown2.markdown(text_content, extras=["tables", "fenced-code-blocks"])
        # 2. Scrive il PDF partendo dall'HTML
        with open(unique_path, "w+b") as pdf_file:
            pisa_status = pisa.CreatePDF(src=html_content, dest=pdf_file)
        if pisa_status.err:
            raise McpError(ErrorData(code=INTERNAL_ERROR, message="Errore durante la conversione da HTML a PDF."))
        return f"File PDF creato con successo. Informa l'utente che il file '{final_filename}' è stato creato e forniscigli esplicitamente questo link per il download: {BASE_URL}/files/{final_filename}"
    except Exception as e:
        raise McpError(ErrorData(code=INTERNAL_ERROR, message=f"Errore durante la creazione del PDF: {e}"))
    

# --- CREAZIONE DEL SERVER MCP ---
def create_document_server() -> Server:
    """
    Crea e configura il server MCP per Document Generator.
    Questa funzione può essere riutilizzata per diversi tipi di trasporto.
    """
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
        try:
            result_message = None

            if name == "create_docx":
                args = CreateDocxParams(**arguments)
                result_message = await asyncio.to_thread(create_docx_file, args.filename, args.text_content)

            elif name == "create_pdf":
                args = CreatePdfParams(**arguments)
                result_message = await asyncio.to_thread(create_pdf_file, args.filename, args.text_content)

            else:
                raise McpError(ErrorData(code=INVALID_PARAMS, message=f"Strumento '{name}' non conosciuto."))

            return [TextContent(type="text", text=result_message)]

        except Exception as e:
            # Cattura sia gli errori di validazione Pydantic che quelli della logica di business
            raise McpError(ErrorData(code=INTERNAL_ERROR, message=f"Errore durante l'esecuzione del tool '{name}': {e}"))

    return server


# --- FUNZIONE PRINCIPALE DEL SERVER (STDIO MODE) ---
async def serve() -> None:
    """
    Funzione principale che configura e avvia il server MCP per Document Generator in modalità stdio.
    """
    server = create_document_server()

    # --- AVVIO DEL SERVER IN MODALITÀ STDIO ---
    options = server.create_initialization_options()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, options)
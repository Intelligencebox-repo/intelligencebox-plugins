import os
from typing import Annotated

# Import necessari da Pydantic per definire i parametri dello strumento
from pydantic import BaseModel, Field

# Import necessari dal framework MCP per creare il server
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.shared.exceptions import McpError
from mcp.types import Tool, ErrorData, TextContent, INTERNAL_ERROR, INVALID_PARAMS

import markdown2
from xhtml2pdf import pisa


# --- Definizione dei Parametri dello Strumento ---
class CreatePdfParams(BaseModel):
    """Parametri per lo strumento di creazione PDF."""

    filename: Annotated[
        str,
        Field(description="Il nome del file PDF da creare (es. 'report.pdf'). Deve finire con .pdf")
    ]
    text_content: Annotated[
        str,
        Field(description="Il testo da scrivere all'interno del file PDF.")
    ]


# --- Questa è la funzione che crea il PDF ---
def create_pdf_file(filename: str, text_content: str) -> str:
    """Crea un file PDF convertendo il testo Markdown in HTML."""

    os.makedirs("output", exist_ok=True)
    output_path = os.path.join("output", filename)

    try:
        # 1. Converte il testo Markdown in HTML
        html_content = markdown2.markdown(text_content, extras=["tables", "fenced-code-blocks"])

        # 2. Scrive il PDF partendo dall'HTML
        with open(output_path, "w+b") as pdf_file:
            pisa_status = pisa.CreatePDF(
                src=html_content,    # Il contenuto HTML da convertire
                dest=pdf_file        # L'oggetto file dove scrivere il PDF
            )

        if pisa_status.err:
            raise McpError(ErrorData(code=INTERNAL_ERROR, message="Errore durante la conversione da HTML a PDF."))

        return f"File PDF creato con successo da Markdown in: {output_path}"

    except Exception as e:
        raise McpError(ErrorData(code=INTERNAL_ERROR, message=f"Errore durante la creazione del PDF: {e}"))


# --- Logica del Server MCP ---
# Questa funzione asincrona imposta e avvia il server.
async def serve() -> None:
    """Avvia il server MCP per il generatore di PDF."""

    server = Server("pdf-generator")

    # Il decoratore "@server.list_tools" registra gli strumenti che il nostro server offre.
    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="create_pdf",
                description="Crea un file PDF con un testo specifico e lo salva.",
                # Specifica che i parametri di input devono rispettare lo schema definito prima
                inputSchema=CreatePdfParams.model_json_schema(),
            )
        ]

    # Il decoratore "@server.call_tool" definisce il codice da eseguire
    # quando Claude decide di usare uno dei nostri strumenti.
    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        # Valida gli argomenti ricevuti da Claude usando il nostro schema Pydantic
        try:
            args = CreatePdfParams(**arguments)
        except ValueError as e:
            raise McpError(ErrorData(code=INVALID_PARAMS, message=f"Parametri invalidi: {e}"))

        # Esegue la funzione che crea il PDF
        result_message = create_pdf_file(args.filename, args.text_content)

        # Restituisce il messaggio di successo a Claude
        return [TextContent(type="text", text=result_message)]

    # Questa parte avvia il server e lo mette in ascolto di richieste
    # tramite Standard Input/Output, il canale di comunicazione usato da MCP.
    options = server.create_initialization_options()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, options)
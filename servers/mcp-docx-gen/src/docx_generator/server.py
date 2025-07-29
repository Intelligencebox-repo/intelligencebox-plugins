import os
from typing import Annotated

# Import necessari da Pydantic per definire i parametri
from pydantic import BaseModel, Field

# Import necessari dal framework MCP per creare il server
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.shared.exceptions import McpError
from mcp.types import Tool, ErrorData, TextContent, INTERNAL_ERROR, INVALID_PARAMS

# Import dalla libreria per creare file DOCX
import pypandoc


# --- Definizione dei Parametri dello Strumento ---
class CreateDocxParams(BaseModel):
    """Parametri per lo strumento di creazione DOCX."""

    filename: Annotated[
        str,
        Field(description="Il nome del file DOCX da creare (es. 'report.docx').")
    ]
    text_content: Annotated[
        str,
        Field(description="Il testo in formato Markdown da scrivere nel file.")
    ]


# --- Logica di Business: Creazione del File DOCX ---
def create_docx_file(filename: str, text_content: str) -> str:
    """Crea un file DOCX convertendo il testo Markdown usando Pandoc."""
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
        return f"File DOCX creato con successo (via Pandoc) in: {output_path}"
    except Exception as e:
        raise McpError(ErrorData(code=INTERNAL_ERROR, message=f"Errore durante la creazione del DOCX con Pandoc: {e}"))
    

# --- Logica del Server MCP ---
async def serve() -> None:
    """Avvia il server MCP per il generatore di DOCX."""

    server = Server("docx-generator")

    # Registra lo strumento 'create_docx'
    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="create_docx",
                description="Crea un file DOCX editabile a partire da un testo in Markdown.",
                inputSchema=CreateDocxParams.model_json_schema(),
            )
        ]

    # Definisce come eseguire lo strumento quando viene chiamato
    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        try:
            args = CreateDocxParams(**arguments)
        except ValueError as e:
            raise McpError(ErrorData(code=INVALID_PARAMS, message=f"Parametri invalidi: {e}"))
        
        # Chiama la funzione che crea il file DOCX
        result_message = create_docx_file(args.filename, args.text_content)

        return [TextContent(type="text", text=result_message)]

    # Avvia il server e lo mette in ascolto
    options = server.create_initialization_options()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, options)
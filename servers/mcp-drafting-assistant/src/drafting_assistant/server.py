import asyncio
import os
from typing import List, Any, Dict

# Import necessari da Pydantic per definire i parametri
from pydantic import BaseModel, Field

# Import necessari dal framework MCP che stai usando
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.shared.exceptions import McpError
from mcp.types import Tool, ErrorData, TextContent, INTERNAL_ERROR, INVALID_PARAMS

from .pipeline import drafting_pipeline

# --- 1. Definizione dei Parametri --- 
class DraftingAssistantParams(BaseModel):
    tipo_atto: str = Field(..., description="Il tipo di atto notarile da generare (es. 'testamento', 'contratto di compravendita').")
    chat_id: str = Field(..., description="L'ID della chat in cui avviene la conversaizone.")

# --- 2. Logica del Server MCP ---
def create_drafting_assistant_server() -> Server:
    """
    Crea e configura il server MCP per la verifica dei codici.
    Questa funzione può essere riutilizzata per diversi tipi di trasporto.
    """

    server = Server("drafting_assistant")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="generate_draft",
                description="Genera una bozza di atto notarile recuperando un atto d'esempio su cui basarsi.",
                inputSchema=DraftingAssistantParams.model_json_schema(),
            )
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        if name != "generate_draft":
            raise McpError(ErrorData(code=INVALID_PARAMS, message=f"Tool '{name}' non definito per questo server."))
        
        try:
            # 1. Validazione dei parametri con Pydantic
            params = DraftingAssistantParams(**arguments)

            # 2. Chiama la funzione di business con i parametri validati
            bozza_atto = await drafting_pipeline(chat_id=params.chat_id, tipo_atto=params.tipo_atto)
            
            # 3. Restituzione del risultato
            return [TextContent(type="text", text=bozza_atto)]

        except McpError as e:
            raise e
        except Exception as e:
            raise McpError(ErrorData(code=INTERNAL_ERROR, message=f"Errore interno: {e}"))
        
    return server


async def serve():
    """
    Funzione principale che configura e avvia il server MCP per la verifica dei codici in modalità stdio.
    """
    server = create_drafting_assistant_server()

    # Avvia il server in modalità stdio
    options = server.create_initialization_options()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, options)
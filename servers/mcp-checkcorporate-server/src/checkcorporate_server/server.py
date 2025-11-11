import asyncio
import json
import os
from typing import Literal, Optional

from pydantic import BaseModel, Field

# MCP imports
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.shared.exceptions import McpError
from mcp.types import Tool, ErrorData, TextContent, INTERNAL_ERROR, INVALID_PARAMS

from .db_tools import DbTools
import sys


# --- PARAMS MODELS ---
class GetBilancioParams(BaseModel):
    societa: str = Field(..., description="La società (es. 'ACME')")
    esercizio: int = Field(..., description="L'esercizio (anno), es. 2024")
    tipo: Literal['Economico', 'Patrimoniale'] = Field(..., description="Tipo di bilancio: Economico o Patrimoniale")


class GetPianoParams(BaseModel):
    societa: str = Field(..., description="La società per cui restituire il piano dei conti")


def create_checkcorporate_server() -> Server:
    # Read credentials from environment. In containerized deployments these
    # will be provided as secrets/env vars (declared in manifest `configSchema`).
    # Read environment-provided configuration
    client_id = os.environ.get("CLIENT_ID")
    client_secret = os.environ.get("CLIENT_SECRET")
    api_endpoint = os.environ.get("API_ENDPOINT_URL")

    # Instantiate DbTools with credentials and API endpoint so tool handlers
    # can make use of them (e.g., to authenticate to external services or to
    # tag simulated SQL executions).
    db = DbTools(client_id=client_id, client_secret=client_secret, api_endpoint=api_endpoint)

    server = Server("checkcorporate_server")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        # Debug: log that list_tools was invoked
        print("[checkcorporate_server] list_tools called", file=sys.stderr, flush=True)
        return [
            Tool(name="get-bilancio", description="Recupera il bilancio aggregato (mock).", inputSchema=GetBilancioParams.model_json_schema()),
            Tool(name="get-piano-dei-conti", description="Recupera il piano dei conti per una società (mock).", inputSchema=GetPianoParams.model_json_schema()),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        try:
            # Debug: log incoming tool call
            print(f"[checkcorporate_server] call_tool invoked: {name} args={arguments}", file=sys.stderr, flush=True)
            if name == "get-bilancio":
                args = GetBilancioParams(**arguments)
                # run DB work in thread to avoid blocking
                result = await asyncio.to_thread(db.get_bilancio, args.societa, args.esercizio, args.tipo)

            elif name == "get-piano-dei-conti":
                args = GetPianoParams(**arguments)
                result = await asyncio.to_thread(db.get_piano_dei_conti, args.societa)

            else:
                raise McpError(ErrorData(code=INVALID_PARAMS, message=f"Tool '{name}' non definito."))

            # Return result as JSON text content
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, default=str))]

        except McpError:
            raise
        except Exception as e:
            raise McpError(ErrorData(code=INTERNAL_ERROR, message=f"Errore eseguendo '{name}': {e}"))

    return server


async def serve():
    # Start the MCP server using stdio transport. We print to stderr so that
    # any supervising client (which reads stdout for JSON-RPC) does not get
    # our logs mixed into the protocol stream.
    # Validate required environment variables (fail-fast)
    missing = [
        name
        for name in ("CLIENT_ID", "CLIENT_SECRET", "API_ENDPOINT_URL")
        if not os.environ.get(name)
    ]
    if missing:
        print(
            f"[checkcorporate_server] missing required environment variables: {', '.join(missing)}",
            file=sys.stderr,
        )
        print(
            "[checkcorporate_server] please provide the required secrets (CLIENT_ID, CLIENT_SECRET, API_ENDPOINT_URL) as environment variables or via your orchestrator/secret manager.",
            file=sys.stderr,
        )
        # Exit to indicate misconfiguration at startup
        raise SystemExit(1)

    server = create_checkcorporate_server()
    options = server.create_initialization_options()

    print(f"[checkcorporate_server] starting stdio server", file=sys.stderr)

    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, options)
    except Exception as e:
        # Log exception to stderr for diagnosability
        print(f"[checkcorporate_server] server runtime error: {e}", file=sys.stderr)
        raise

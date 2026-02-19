import asyncio
import json
import os
from typing import Literal, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Load environment variables from .env file if present
load_dotenv()

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
    tipo: str = Field(..., description="Tipo di report: scegliere tra quelli disponibili. ad esempio \"E1-Report Economico\" \"P1 Report Patrimoniale\" ")


class GetBilancioPerContoParams(BaseModel):
    societa: str = Field(..., description="La società (es. 'ACME')")
    esercizio: int = Field(..., description="L'esercizio (anno), es. 2024")
    tipo: str = Field(..., description="Tipo di report: scegliere tra quelli disponibili. ad esempio \"E1-Report Economico\" \"P1 Report Patrimoniale\" ")


class GetPianoParams(BaseModel):
    societa: str = Field(..., description="La società per cui restituire il piano dei conti")
    ricerca: str = Field(..., description="Filtro di ricerca opzionale (può essere stringa vuota)")


class GetSocietaParams(BaseModel):
    pass  # Nessun parametro richiesto: restituisce le società accessibili dall'utente


class GetReportDisponibiliParams(BaseModel):
    societa: str = Field(..., description="La società per cui elencare i report disponibili")
    ricerca: str = Field(..., description="Filtro di ricerca opzionale (può essere stringa vuota)")


def create_checkcorporate_server() -> Server:
    # Read credentials from environment. In containerized deployments these
    # will be provided as secrets/env vars (declared in manifest `configSchema`).
    # Read environment-provided configuration
    client_id = os.environ.get("CLIENT_ID")
    client_secret = os.environ.get("CLIENT_SECRET")
    api_endpoint = os.environ.get("API_ENDPOINT_URL")
    # Flag per ignorare la verifica SSL (valori truthy: 1, true, yes)
    ignore_ssl_env = os.environ.get("IGNORE_SSL_CERT", "0")
    ignore_ssl = str(ignore_ssl_env).lower() in ("1", "true", "yes")

    # Instantiate DbTools with credentials and API endpoint so tool handlers
    # can make use of them (e.g., to authenticate to external services or to
    # tag simulated SQL executions).
    db = DbTools(client_id=client_id, client_secret=client_secret, api_endpoint=api_endpoint, ignore_ssl=ignore_ssl)

    server = Server("checkcorporate_server")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        # Debug: log that list_tools was invoked
        print("[checkcorporate_server] list_tools called", file=sys.stderr, flush=True)
        return [
            Tool(name="get-bilancio", description="Recupera il bilancio economico o patrimoniale di una società. E' il tool di default corretto per ottenere un bilancio.", inputSchema=GetBilancioParams.model_json_schema()),
            Tool(name="get-bilancio-per-conto", description="Recupera il bilancio dettagliato per conto contabile", inputSchema=GetBilancioPerContoParams.model_json_schema()),
            Tool(name="get-piano-dei-conti", description="Recupera il piano dei conti per una società", inputSchema=GetPianoParams.model_json_schema()),
            Tool(name="get-report-disponibili", description="Elenca i report disponibili per il parametro 'tipo'", inputSchema=GetReportDisponibiliParams.model_json_schema()),
            Tool(name="get-societa", description="Restituisce l'elenco delle società alle quali l'utente può accedere", inputSchema=GetSocietaParams.model_json_schema()),
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
                # Log the API response received from the remote service
                try:
                    # Converti a stringa e sanitizza per evitare caratteri non ASCII
                    result_str = str(result)
                    if len(result_str) > 1000:
                        result_str = result_str[:1000] + "...[truncated]"
                    result_sanitized = result_str.encode('ascii', errors='replace').decode('ascii')
                    print(f"[checkcorporate_server] API result for get-bilancio: {result_sanitized}", file=sys.stderr, flush=True)
                except Exception:
                    print("[checkcorporate_server] Failed to print API result for get-bilancio", file=sys.stderr, flush=True)

            elif name == "get-bilancio-per-conto":
                args = GetBilancioPerContoParams(**arguments)
                result = await asyncio.to_thread(db.get_bilancio_per_conto, args.societa, args.esercizio, args.tipo)
                try:
                    result_str = str(result)
                    if len(result_str) > 1000:
                        result_str = result_str[:1000] + "...[truncated]"
                    result_sanitized = result_str.encode('ascii', errors='replace').decode('ascii')
                    print(f"[checkcorporate_server] API result for get-bilancio-per-conto: {result_sanitized}", file=sys.stderr, flush=True)
                except Exception:
                    print("[checkcorporate_server] Failed to print API result for get-bilancio-per-conto", file=sys.stderr, flush=True)

            elif name == "get-piano-dei-conti":
                args = GetPianoParams(**arguments)
                result = await asyncio.to_thread(db.get_piano_dei_conti, args.societa, args.ricerca)
                # Log the API response received from the remote service
                try:
                    # Converti a stringa e sanitizza per evitare caratteri non ASCII
                    result_str = str(result)
                    if len(result_str) > 1000:
                        result_str = result_str[:1000] + "...[truncated]"
                    result_sanitized = result_str.encode('ascii', errors='replace').decode('ascii')
                    print(f"[checkcorporate_server] API result for get-piano-dei-conti: {result_sanitized}", file=sys.stderr, flush=True)
                except Exception:
                    print("[checkcorporate_server] Failed to print API result for get-piano-dei-conti", file=sys.stderr, flush=True)

            elif name == "get-report-disponibili":
                args = GetReportDisponibiliParams(**arguments)
                result = await asyncio.to_thread(db.get_report_disponibili, args.societa, args.ricerca)
                try:
                    result_str = str(result)
                    if len(result_str) > 1000:
                        result_str = result_str[:1000] + "...[truncated]"
                    result_sanitized = result_str.encode('ascii', errors='replace').decode('ascii')
                    print(f"[checkcorporate_server] API result for get-report-disponibili: {result_sanitized}", file=sys.stderr, flush=True)
                except Exception:
                    print("[checkcorporate_server] Failed to print API result for get-report-disponibili", file=sys.stderr, flush=True)

            elif name == "get-societa":
                result = await asyncio.to_thread(db.get_societa)
                try:
                    result_str = str(result)
                    if len(result_str) > 1000:
                        result_str = result_str[:1000] + "...[truncated]"
                    result_sanitized = result_str.encode('ascii', errors='replace').decode('ascii')
                    print(f"[checkcorporate_server] API result for get-societa: {result_sanitized}", file=sys.stderr, flush=True)
                except Exception:
                    print("[checkcorporate_server] Failed to print API result for get-societa", file=sys.stderr, flush=True)

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
    # Ensure stdout/stderr use UTF-8 to avoid UnicodeEncodeError on Windows
    try:
        if hasattr(sys.stdout, "reconfigure"):
            try:
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
                sys.stderr.reconfigure(encoding="utf-8", errors="replace")
            except Exception as e:
                print(f"[checkcorporate_server] could not reconfigure stdio encoding: {e}", file=sys.stderr, flush=True)
    except Exception:
        pass
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


def main():
    """Entry point per avviare il server MCP."""
    import asyncio
    asyncio.run(serve())


if __name__ == "__main__":
    main()

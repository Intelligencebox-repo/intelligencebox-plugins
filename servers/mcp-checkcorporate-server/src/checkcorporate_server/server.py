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
    societa: str = Field(
        ...,
        description="Nome della società. Usa '*all' per interrogare tutte le società disponibili, oppure specifica il nome esatto (es. 'ACME SRL', 'BETA SPA')"
    )
    esercizio: int = Field(
        ...,
        description="Anno di esercizio fiscale (es. 2024, 2023). Indica l'anno del bilancio da recuperare"
    )
    tipo: str = Field(
        ...,
        description="Tipo di report da recuperare. Prima usa 'get-report-disponibili' per vedere i report disponibili. Esempi comuni: 'E1-Report Economico', 'P1-Report Patrimoniale', 'Economico', 'Patrimoniale'"
    )


class GetPianoParams(BaseModel):
    societa: str = Field(
        ...,
        description="Nome della società. Usa '*all' per interrogare tutte le società, oppure specifica il nome esatto (es. 'ACME SRL')"
    )
    ricerca: str = Field(
        ...,
        description="Filtro di ricerca testuale per codice o descrizione conto. Usa stringa vuota '' per ottenere tutti i conti. Esempi: 'dip' (dipendenti), 'amm' (ammortamenti), 'cassa', 'banca'"
    )


class GetReportDisponibiliParams(BaseModel):
    societa: str = Field(
        ...,
        description="Nome della società. Usa '*all' per vedere i report di tutte le società, oppure specifica il nome esatto"
    )
    ricerca: str = Field(
        ...,
        description="Filtro di ricerca per nome report. Usa stringa vuota '' per elencare tutti i report disponibili. Esempi: 'economico', 'patrimoniale', 'E1', 'P1'"
    )


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
            Tool(
                name="get-bilancio",
                description="Recupera i dati di bilancio aggregati per una società e anno fiscale. Richiede: societa (usa '*all' per tutte), esercizio (anno), tipo (prima usa get-report-disponibili per vedere i tipi). Esempio: societa='*all', esercizio=2024, tipo='E1-Report Economico'",
                inputSchema=GetBilancioParams.model_json_schema()
            ),
            Tool(
                name="get-piano-dei-conti",
                description="Recupera il piano dei conti (elenco codici e descrizioni conti contabili). Utile per trovare i codici conto da usare nelle analisi. Usa societa='*all' per tutte le società, ricerca='' per tutti i conti o un filtro testuale (es. 'dip', 'amm', 'cassa')",
                inputSchema=GetPianoParams.model_json_schema()
            ),
            Tool(
                name="get-report-disponibili",
                description="Elenca i tipi di report disponibili per il bilancio. USA QUESTO TOOL PRIMA di get-bilancio per conoscere i valori validi del parametro 'tipo'. Usa societa='*all' per tutte, ricerca='' per tutti i report",
                inputSchema=GetReportDisponibiliParams.model_json_schema()
            ),
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

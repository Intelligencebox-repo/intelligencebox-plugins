"""
SSE Server for Verifica Codici MCP
Provides HTTP/SSE transport for Docker deployments
"""
import asyncio
import os

from starlette.applications import Starlette
from starlette.routing import Route
from starlette.requests import Request
from mcp.server.sse import SseServerTransport
import uvicorn
from sse_starlette import EventSourceResponse

from .server import create_verifica_codici_server


async def sse_endpoint(request: Request):
    """SSE endpoint for MCP communication"""
    # Create the Verifica Codici server instance
    server = create_verifica_codici_server()

    # Use the proper SSE transport from mcp library
    from mcp.server.sse import sse_server

    # Handle the SSE connection using EventSourceResponse
    async def event_generator():
        async with sse_server(request) as (read_stream, write_stream):
            options = server.create_initialization_options()
            try:
                await server.run(read_stream, write_stream, options)
            except Exception as e:
                print(f"Error in SSE handler: {e}")
                raise

    return EventSourceResponse(event_generator())


# Create Starlette app with SSE route
app = Starlette(
    debug=False,
    routes=[
        Route("/sse", sse_endpoint, methods=["GET"]),
    ],
)


def main():
    """Main entry point for SSE server"""
    port = int(os.getenv("PORT", "8080"))
    host = os.getenv("HOST", "0.0.0.0")

    print(f"🚀 Starting Verifica Codici MCP SSE Server on {host}:{port}")
    print(f"📡 SSE endpoint: http://{host}:{port}/sse")

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info"
    )


if __name__ == "__main__":
    main()

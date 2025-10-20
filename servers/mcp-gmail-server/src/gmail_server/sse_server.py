"""
SSE Server for Gmail MCP
Provides HTTP/SSE transport for Docker deployments
"""
import asyncio
import os

from starlette.applications import Starlette
from starlette.requests import Request
from mcp.server.sse import SseServerTransport
import uvicorn
from sse_starlette import EventSourceResponse

from .server import create_gmail_server


async def handle_sse(request: Request):
    """Handle SSE endpoint for MCP protocol"""
    async with SseServerTransport("/messages") as streams:
        # Create the Gmail server
        server = create_gmail_server()

        # Initialize server options
        options = server.create_initialization_options()

        # Set up the SSE transport
        read_stream, write_stream = streams

        # Run the server with the streams
        await server.run(read_stream, write_stream, options)


# Create Starlette app with SSE route
app = Starlette(
    debug=False,
    routes=[],
)


@app.get("/sse")
async def sse_endpoint(request: Request):
    """SSE endpoint for MCP communication"""
    # Create the Gmail server instance
    server = create_gmail_server()

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


def main():
    """Main entry point for SSE server"""
    port = int(os.getenv("PORT", "8080"))
    host = os.getenv("HOST", "0.0.0.0")

    print(f"🚀 Starting Gmail MCP SSE Server on {host}:{port}")
    print(f"📡 SSE endpoint: http://{host}:{port}/sse")

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info"
    )


if __name__ == "__main__":
    main()

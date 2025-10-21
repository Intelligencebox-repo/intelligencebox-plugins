"""
SSE Server for Gmail MCP
Provides HTTP/SSE transport for Docker deployments
"""
import os

from starlette.applications import Starlette
from starlette.routing import Route
from mcp.server.sse import SseServerTransport
import uvicorn

from .server import create_gmail_server


# Create SSE transport instance
# The "/messages" endpoint will receive POST requests with client messages
sse_transport = SseServerTransport("/messages")


async def sse_endpoint(scope, receive, send):
    """
    SSE GET endpoint - establishes Server-Sent Events stream
    This is called when a client connects to GET /sse
    """
    server = create_gmail_server()

    # Use the connect_sse context manager to get read/write streams
    async with sse_transport.connect_sse(scope, receive, send) as streams:
        read_stream, write_stream = streams
        options = server.create_initialization_options()

        try:
            # Run the MCP server with the established streams
            await server.run(read_stream, write_stream, options)
        except Exception as e:
            print(f"Error in SSE handler: {e}")
            raise


async def messages_endpoint(scope, receive, send):
    """
    POST /messages endpoint - receives client messages
    This is called when the client sends messages via POST
    """
    await sse_transport.handle_post_message(scope, receive, send)


# Create Starlette app with both SSE and messages routes
app = Starlette(
    debug=False,
    routes=[
        Route("/sse", sse_endpoint, methods=["GET"]),
        Route("/messages", messages_endpoint, methods=["POST"]),
    ],
)


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

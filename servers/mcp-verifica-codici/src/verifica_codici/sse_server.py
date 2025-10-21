"""
SSE Server for Verifica Codici MCP
Provides HTTP/SSE transport for Docker deployments
"""
import os

from starlette.applications import Starlette
from starlette.routing import Route
from mcp.server.sse import SseServerTransport
import uvicorn

from .server import create_verifica_codici_server


# Create SSE transport instance
# The "/messages" endpoint will receive POST requests with client messages
sse_transport = SseServerTransport("/messages")


async def handle_sse(scope, receive, send):
    """
    SSE GET endpoint - establishes Server-Sent Events stream

    IMPORTANT: This uses raw ASGI signature (scope, receive, send) instead of
    Starlette's Request wrapper. This is required because connect_sse() manages
    the complete ASGI response lifecycle internally. Using Request would cause
    Starlette to try sending its own response after connect_sse() completes,
    resulting in "ASGI message 'http.response.start' sent after response completed" error.

    This pattern is per official MCP documentation at:
    https://modelcontextprotocol.io/docs/develop/build-server
    """
    server = create_verifica_codici_server()

    # connect_sse handles the complete ASGI response lifecycle
    async with sse_transport.connect_sse(scope, receive, send) as streams:
        read_stream, write_stream = streams
        options = server.create_initialization_options()

        try:
            # Run the MCP server with the established streams
            await server.run(read_stream, write_stream, options)
        except Exception as e:
            print(f"Error in SSE handler: {e}")
            raise


async def handle_messages(scope, receive, send):
    """
    POST /messages endpoint - receives client messages

    IMPORTANT: Also uses raw ASGI signature for the same reason as handle_sse.
    The handle_post_message method manages the ASGI response lifecycle internally.
    """
    await sse_transport.handle_post_message(scope, receive, send)


# Create Starlette app with routes using raw ASGI endpoints
app = Starlette(
    debug=False,
    routes=[
        Route("/sse", endpoint=handle_sse, methods=["GET"]),
        Route("/messages", endpoint=handle_messages, methods=["POST"]),
    ]
)


def main():
    """Main entry point for SSE server"""
    port = int(os.getenv("PORT", "8080"))
    host = os.getenv("HOST", "0.0.0.0")

    print(f"🚀 Starting Verifica Codici MCP SSE Server on {host}:{port}")
    print(f"📡 SSE endpoint: http://{host}:{port}/sse")
    print(f"📬 Messages endpoint: http://{host}:{port}/messages")

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info"
    )


if __name__ == "__main__":
    main()

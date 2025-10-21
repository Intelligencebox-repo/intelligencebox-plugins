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


async def handle_sse(scope, receive, send):
    """
    SSE GET endpoint - establishes Server-Sent Events stream

    connect_sse() manages the ASGI response lifecycle, so no additional Response
    should be sent after awaiting server.run().
    """
    if scope["type"] != "http":
        raise RuntimeError("SSE endpoint only supports HTTP connections")

    server = create_gmail_server()

    # connect_sse handles the complete ASGI response lifecycle internally
    async with sse_transport.connect_sse(
        scope,
        receive,
        send
    ) as streams:
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

    handle_post_message() writes the response directly to the ASGI send callable.
    """
    if scope["type"] != "http":
        raise RuntimeError("Messages endpoint only supports HTTP connections")

    await sse_transport.handle_post_message(
        scope,
        receive,
        send
    )

class SSEEndpoint:
    """Starlette-compatible ASGI endpoint for establishing SSE connections."""

    async def __call__(self, scope, receive, send):
        await handle_sse(scope, receive, send)


class MessagesEndpoint:
    """Starlette-compatible ASGI endpoint for handling SSE POST messages."""

    async def __call__(self, scope, receive, send):
        await handle_messages(scope, receive, send)


# Create Starlette app with routes using raw ASGI endpoints
app = Starlette(
    debug=False,
    routes=[
        Route("/sse", endpoint=SSEEndpoint(), methods=["GET"]),
        Route("/messages", endpoint=MessagesEndpoint(), methods=["POST"]),
    ]
)


def main():
    """Main entry point for SSE server"""
    port = int(os.getenv("PORT", "8080"))
    host = os.getenv("HOST", "0.0.0.0")

    print(f"🚀 Starting Gmail MCP SSE Server on {host}:{port}")
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

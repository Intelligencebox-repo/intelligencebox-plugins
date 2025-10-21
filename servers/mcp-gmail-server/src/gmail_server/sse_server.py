"""
SSE Server for Gmail MCP
Provides HTTP/SSE transport for Docker deployments
"""
import os

from starlette.applications import Starlette
from starlette.routing import Route
from starlette.requests import Request
from starlette.responses import Response
from mcp.server.sse import SseServerTransport
import uvicorn

from .server import create_gmail_server


# Create SSE transport instance
# The "/messages" endpoint will receive POST requests with client messages
sse_transport = SseServerTransport("/messages")


async def handle_sse(request: Request):
    """
    SSE GET endpoint - establishes Server-Sent Events stream

    IMPORTANT: Uses Starlette's Request wrapper to satisfy Route's expectations.
    The connect_sse() context manager sends the SSE response internally via request._send.
    We must return an empty Response() to satisfy Starlette's routing system, even though
    connect_sse() already sent the complete response.

    This pattern is per official MCP Python SDK example:
    https://github.com/modelcontextprotocol/python-sdk/blob/main/src/mcp/server/sse.py
    """
    server = create_gmail_server()

    # connect_sse handles the complete ASGI response lifecycle internally
    async with sse_transport.connect_sse(
        request.scope,
        request.receive,
        request._send
    ) as streams:
        read_stream, write_stream = streams
        options = server.create_initialization_options()

        try:
            # Run the MCP server with the established streams
            await server.run(read_stream, write_stream, options)
        except Exception as e:
            print(f"Error in SSE handler: {e}")
            raise

    # Return empty response to satisfy Starlette (actual response already sent by connect_sse)
    return Response()


async def handle_messages(request: Request):
    """
    POST /messages endpoint - receives client messages

    IMPORTANT: Uses Request wrapper and returns empty Response for same reason as handle_sse.
    The handle_post_message method sends the response internally.
    """
    await sse_transport.handle_post_message(
        request.scope,
        request.receive,
        request._send
    )

    # Return empty response to satisfy Starlette (actual response already sent)
    return Response()


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

from .server import serve

def main():
    """MCP Verifica Codici Server"""
    import asyncio
    asyncio.run(serve())

if __name__ == "__main__":
    main()
from .server import serve

def main():
    """MCP CheckCorporate Server"""
    import asyncio
    asyncio.run(serve())

if __name__ == "__main__":
    main()

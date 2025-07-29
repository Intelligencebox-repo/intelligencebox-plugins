from .server import serve

def main():
    """MCP PDF Generator Server"""
    import asyncio
    asyncio.run(serve())

if __name__ == "__main__":
    main()
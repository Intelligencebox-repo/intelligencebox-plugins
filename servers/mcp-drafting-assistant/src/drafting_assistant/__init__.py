from .server import serve

def main():
    """MCP Drafting Assistant Server"""
    import asyncio
    asyncio.run(serve())

if __name__ == "__main__":
    main()
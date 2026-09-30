"""Offline subprocess fixture: real MCP transport, deterministic providers, no key access."""
import asyncio
import sys
from pathlib import Path
from agent_mcp.config import load_settings
from agent_mcp import server

class OfflineProviders:
    def __init__(self, *args):
        pass
    async def execute(self, request, spec):
        await asyncio.sleep(0.1)
        return {"text": "offline answer", "model": spec.model, "usage": {}, "artifacts": [], "truncated": False, "finish_reason": "completed"}
    async def close(self):
        pass

server.Providers = OfflineProviders
server.create_server(load_settings(Path(sys.argv[1]))).run(transport="stdio")

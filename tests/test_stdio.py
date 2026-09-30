import asyncio
import json
import sys
from datetime import timedelta
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

def unpack(result):
    assert not result.isError, str(result)
    return result.structuredContent or json.loads(result.content[0].text)

async def test_real_stdio_task_lifecycle(settings, tmp_path):
    config = tmp_path / "config.json"
    config.write_text(settings.model_dump_json(), encoding="utf-8")
    launcher = Path(__file__).with_name("stdio_fixture.py")
    params = StdioServerParameters(command=sys.executable, args=[str(launcher), str(config)])
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=15)) as session:
            await session.initialize()
            names = {tool.name for tool in (await session.list_tools()).tools}
            assert names == {"list_capabilities", "submit_text", "query_knowledge", "submit_image", "submit_audio", "submit_batch", "get_task", "cancel_task", "list_tasks"}
            caps = unpack(await session.call_tool("list_capabilities"))
            assert "ds" in caps["models"]
            result = unpack(await session.call_tool("submit_batch", {"tasks": [{"kind": "text", "prompt": "task one"}, {"kind": "text", "model": "gt", "prompt": "task two"}]}))
            assert result["ok"] and len(result["tasks"]) == 2
            ids = [t["task_id"] for t in result["tasks"]]
            states = [unpack(await session.call_tool("get_task", {"task_id": id, "wait_seconds": 2}))["task"] for id in ids]
            assert all(t["state"] == "succeeded" and t["result"]["text"] == "offline answer" for t in states)
            knowledge = unpack(await session.call_tool("query_knowledge", {"question": "What is photosynthesis?", "max_output_tokens": 256}))
            assert knowledge["task"]["kind"] == "knowledge" and knowledge["task"]["model_alias"] == "gk"
            answer = unpack(await session.call_tool("get_task", {"task_id": knowledge["task"]["task_id"], "wait_seconds": 2}))["task"]
            assert answer["state"] == "succeeded" and answer["result"]["live_search"] is False
            new = unpack(await session.call_tool("submit_text", {"model": "ds", "prompt": "cancel me"}))
            cancelled = unpack(await session.call_tool("cancel_task", {"task_id": new["task"]["task_id"]}))
            assert cancelled["task"]["state"] == "cancelled"
            invalid = unpack(await session.call_tool("submit_text", {"model": "bad", "prompt": "x"}))
            assert invalid["error"]["code"] == "invalid_model"

async def test_production_server_handshake_without_keys(settings, tmp_path):
    config = tmp_path / "production.json"
    config.write_text(settings.model_dump_json(), encoding="utf-8")
    params = StdioServerParameters(command=sys.executable, args=["-m", "agent_mcp", "--config", str(config), "serve"])
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=15)) as session:
            await session.initialize()
            assert len((await session.list_tools()).tools) == 9
            result = unpack(await session.call_tool("get_task", {"task_id": "nonexistent"}))
            assert result["error"]["code"] == "unknown_task"

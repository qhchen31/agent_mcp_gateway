"""One small, paid world-knowledge query through the real MCP stdio service."""
import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent


def unpack(result):
    if result.isError:
        raise RuntimeError("MCP tool returned an error")
    return result.structuredContent or json.loads(result.content[0].text)


async def main():
    params = StdioServerParameters(command=sys.executable,
        args=["-m", "agent_mcp", "--config", str(ROOT / "config.json"), "serve"], cwd=str(ROOT))
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=45)) as session:
            await session.initialize()
            names = {tool.name for tool in (await session.list_tools()).tools}
            caps = unpack(await session.call_tool("list_capabilities"))
            defaults = caps["limits"]["default_models"]
            accepted = unpack(await session.call_tool("query_knowledge", {
                "question": "请使用 Google 搜索核实法国首都的名称，只用一句话回答。", "max_output_tokens": 256}))
            if not accepted.get("ok"):
                raise RuntimeError(json.dumps(accepted, ensure_ascii=False))
            task = accepted["task"]
            for _ in range(7):
                task = unpack(await session.call_tool("get_task", {
                    "task_id": task["task_id"], "wait_seconds": 30}))["task"]
                if task["state"] in {"succeeded", "failed", "cancelled"}:
                    break
            result = task.get("result") or {}
            checks = {
                "separate_tools": {"query_knowledge", "submit_text"} <= names,
                "separate_default_routes": defaults["text"] == "deepseek-text" and defaults["knowledge"] == "gemini-knowledge",
                "knowledge_kind": task["kind"] == "knowledge",
                "default_alias": task["model_alias"] == "gemini-knowledge",
                "succeeded": task["state"] == "succeeded",
                "actual_model": result.get("model") == "gemini-3.8-flash",
                "correct_answer": "巴黎" in result.get("text", "") or "paris" in result.get("text", "").lower(),
                "search_enabled": result.get("search_enabled") is True,
                "actual_search": result.get("knowledge_source") == "web" and result.get("live_search") is True,
                "sources_returned": bool(result.get("sources")),
                "not_truncated": result.get("truncated") is False,
            }
            report = {"tested_at": datetime.now(timezone.utc).isoformat(),
                "transport": "MCP stdio", "default_models": defaults,
                "checks": checks, "passed": all(checks.values()), "task": task}
            output = ROOT / "outputs" / "knowledge-self-test" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") / "result.json"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"report": str(output), "passed": report["passed"], "checks": checks,
                "task": {"state": task["state"], "model": result.get("model"), "text": result.get("text"),
                    "usage": result.get("usage"), "search_queries": result.get("search_queries"),
                    "sources": result.get("sources")}}, ensure_ascii=True, indent=2))
            return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

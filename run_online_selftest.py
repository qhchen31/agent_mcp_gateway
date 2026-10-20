"""Explicit paid MCP smoke tests; synthetic media, no key-bearing files or logs."""
import asyncio
import json
import math
import os
import struct
import sys
import wave
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from agent_mcp.config import load_settings

ROOT = Path(__file__).resolve().parent
TERMINAL = {"succeeded", "failed", "cancelled"}


def unpack(result):
    if result.isError:
        raise RuntimeError("MCP protocol/tool error")
    return result.structuredContent or json.loads(result.content[0].text)


async def main():
    settings = load_settings(ROOT / "config.json")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = ROOT / "outputs" / "online-self-test" / stamp
    output.mkdir(parents=True, exist_ok=True)
    data = settings.model_dump(mode="json")
    data.update(max_output_tokens=256, rate_limit_retries=0,
                text_timeout_seconds=60, media_timeout_seconds=180)
    data["models"][data["default_models"]["image"]]["image_size"] = "512"
    config = output / "config.small.json"
    config.write_text(json.dumps(data, indent=2), encoding="utf-8")
    audio = settings.allowed_input_dirs[0] / ("online-tone-" + stamp + ".wav")
    audio.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(audio), "wb") as wav:
        wav.setparams((1, 2, 16000, 16000, "NONE", "not compressed"))
        wav.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * n / 16000))) for n in range(16000)))
    # Use the installed plugin's launcher; only substitute a small test config.
    manifest = ROOT / ".local-plugin" / "plugins" / "agent-mcp-gateway" / ".mcp.json"
    launcher = json.loads(manifest.read_text(encoding="utf-8"))["mcpServers"]["agent-mcp-gateway"]
    args = list(launcher["args"])
    args[args.index("--config") + 1] = str(config)
    env = {name: os.environ[name] for name in launcher.get("env_vars", []) if name in os.environ}
    params = StdioServerParameters(command=launcher["command"], args=args, cwd=launcher["cwd"], env=env)
    checks = {}
    report = {"tested_at": datetime.now(timezone.utc).isoformat(), "transport": "MCP stdio",
              "retries": 0, "checks": checks, "passed": False}

    async def run(session, name, tool, arguments):
        accepted = unpack(await session.call_tool(tool, arguments))
        if not accepted.get("ok"):
            checks[name] = {"state": "rejected", "error": accepted.get("error")}
        else:
            task = accepted["task"]
            for _ in range(7):
                response = unpack(await session.call_tool("get_task", {"task_id": task["task_id"], "wait_seconds": 30}))
                task = response["task"]
                if task["state"] in TERMINAL:
                    break
            if task["state"] not in TERMINAL:
                task = unpack(await session.call_tool("cancel_task", {"task_id": task["task_id"]}))["task"]
            checks[name] = task
        # Persist each result so partial runs remain reviewable. Requests are synthetic.
        (output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        result = checks[name].get("result") or {}
        print(json.dumps({"check": name, "state": checks[name]["state"],
                          "model": result.get("model"), "text": result.get("text"),
                          "error": checks[name].get("error"), "artifacts": result.get("artifacts", [])}), flush=True)
        return result

    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=45)) as session:
            await session.initialize()
            report["tools"] = sorted(tool.name for tool in (await session.list_tools()).tools)
            await session.call_tool("list_capabilities")
            await run(session, "deepseek_text", "submit_text", {"prompt": "Return only a Python function add(a, b) that returns their sum.", "max_output_tokens": 128})
            await run(session, "gemini_text", "submit_text", {"model": "gemini-text", "prompt": "Reply with exactly: OK", "max_output_tokens": 128})
            await run(session, "gemini_knowledge", "query_knowledge", {"question": "Use Google Search to verify the capital of France. Answer in one short sentence.", "max_output_tokens": 256})
            await run(session, "gemini_audio", "submit_audio", {"file_path": str(audio), "prompt": "Describe this short audio. Is it speech or a steady tone? Answer briefly.", "max_output_tokens": 256})
            image = await run(session, "gemini_image", "submit_image", {"prompt": "One solid blue circle centered on plain white. No text. Return one image only."})
            if image.get("artifacts"):
                await run(session, "gemini_edit", "submit_image", {"prompt": "Change only the blue circle to red. Keep the white background. Return one image only.", "reference_paths": [image["artifacts"][0]["path"]]})
            else:
                checks["gemini_edit"] = {"state": "skipped", "reason": "Image generation did not return an artifact"}
    semantic_checks = {
        "nine_tools": len(report["tools"]) == 9,
        "all_tasks_succeeded": all(task["state"] == "succeeded" for task in checks.values()),
        "gemini_text_ok": (checks["gemini_text"].get("result") or {}).get("text", "").strip() == "OK",
        "knowledge_used_search": (checks["gemini_knowledge"].get("result") or {}).get("live_search") is True,
        "knowledge_has_sources": bool((checks["gemini_knowledge"].get("result") or {}).get("sources")),
        "images_saved": all(bool((checks[name].get("result") or {}).get("artifacts")) for name in ("gemini_image", "gemini_edit")),
    }
    report.update(semantic_checks=semantic_checks, passed=all(semantic_checks.values()))
    (output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(output / "result.json"), "passed": report["passed"], "semantic_checks": semantic_checks}), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception:
        # Never print exception details that might contain upstream credentials.
        print("Online self-test could not complete. Check the local report and MCP configuration.", file=sys.stderr)
        raise SystemExit(1)

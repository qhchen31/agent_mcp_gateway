"""One explicitly requested paid audio task through a fresh MCP connection."""
import argparse
import asyncio
import hashlib
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


async def main(args):
    audio = args.file.resolve(strict=True)
    digest = hashlib.sha256(audio.read_bytes()).hexdigest()
    output = ROOT / "outputs" / "audio-connection-test" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output.mkdir(parents=True, exist_ok=False)
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8-sig"))
    config["rate_limit_retries"] = 0
    config_path = output / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    params = StdioServerParameters(command=sys.executable, args=["-m", "agent_mcp", "--config", str(config_path), "serve"], cwd=str(ROOT))
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=45)) as session:
            await session.initialize()
            accepted = unpack(await session.call_tool("submit_audio", {"file_path": str(audio),
                "prompt": args.prompt, "max_output_tokens": args.max_output_tokens}))
            if not accepted.get("ok"):
                raise RuntimeError(json.dumps(accepted))
            task = accepted["task"]
            print("Task accepted:", task["task_id"], flush=True)
            for _ in range(22):
                task = unpack(await session.call_tool("get_task", {"task_id": task["task_id"], "wait_seconds": 30}))["task"]
                print("State:", task["state"], "seconds:", task["run_seconds"], flush=True)
                if task["state"] in {"succeeded", "failed", "cancelled"}:
                    break
    result = task.get("result") or {}
    unchanged = digest == hashlib.sha256(audio.read_bytes()).hexdigest()
    passed = task["state"] == "succeeded" and bool(result.get("text")) and not result.get("truncated") and unchanged
    report = {"tested_at": datetime.now(timezone.utc).isoformat(), "passed": passed,
        "input_bytes": audio.stat().st_size, "input_unchanged": unchanged, "task": task}
    target = output / "result.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(target), "passed": passed, "state": task["state"], "error": task.get("error"),
        "model": result.get("model"), "usage": result.get("usage"), "audio_transport": result.get("audio_transport"),
        "remote_file_deleted": result.get("remote_file_deleted"), "truncated": result.get("truncated")}, ensure_ascii=True), flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, required=True, help="Allowed absolute audio path; uploads content to Gemini")
    parser.add_argument("--prompt", default="State the spoken language and summarize the main topics in four short English bullets. Do not provide coding solutions or speculate about inaudible content.")
    parser.add_argument("--max-output-tokens", type=int, default=1024)
    raise SystemExit(asyncio.run(main(parser.parse_args())))

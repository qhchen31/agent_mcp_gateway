"""Three small paid calls through real MCP stdio; synthetic public fixtures only."""
import asyncio
import json
import struct
import sys
import wave
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

ROOT = Path(__file__).resolve().parent


def fixtures():
    folder = ROOT / "inputs" / "multimodal-selftest"
    folder.mkdir(parents=True, exist_ok=True)
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    image = folder / "blue.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 64, 64, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress((b"\0" + b"\0\0\xff" * 64) * 64)) + chunk(b"IEND", b""))
    writer = PdfWriter()
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    font_ref = writer._add_object(font)
    for text in ("Page one: ALPHA", "Page two: BETA"):
        page = writer.add_blank_page(400, 300)
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})})
        content = DecodedStreamObject(); content.set_data(f"BT /F1 24 Tf 30 200 Td ({text}) Tj ET".encode())
        page[NameObject("/Contents")] = writer._add_object(content)
    pdf = folder / "two-pages.pdf"
    with pdf.open("wb") as stream:
        writer.write(stream)
    return image, pdf


def unpack(result):
    if result.isError:
        raise RuntimeError("MCP tool failed")
    return result.structuredContent or json.loads(result.content[0].text)


async def main():
    image, pdf = fixtures()
    folder = ROOT / "outputs" / "multimodal-selftest" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder.mkdir(parents=True, exist_ok=False)
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8-sig"))
    config.update(rate_limit_retries=0, max_output_tokens=2048, speech_max_output_tokens=2048)
    config_file = folder / "config.small.json"
    config_file.write_text(json.dumps(config), encoding="utf-8")
    params = StdioServerParameters(command=sys.executable, args=["-m", "agent_mcp", "--config", str(config_file), "serve"], cwd=str(ROOT))
    tasks = [
        {"kind": "vision", "file_paths": [str(image)], "prompt": "Name the main color. Answer one English word.", "max_output_tokens": 256},
        {"kind": "document", "file_path": str(pdf), "pages": [2, 1], "max_output_tokens": 2048},
        {"kind": "speech", "prompt": "The test number is seven.", "style": "clear and calm"},
    ]
    if len(sys.argv) > 1:
        if sys.argv[1] not in {"vision", "document", "speech"}:
            raise ValueError("Optional argument must be vision, document or speech")
        tasks = [task for task in tasks if task["kind"] == sys.argv[1]]
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=45)) as session:
            await session.initialize()
            names = {tool.name for tool in (await session.list_tools()).tools}
            assert len(names) == 12
            accepted = unpack(await session.call_tool("submit_batch", {"tasks": tasks}))
            if not accepted.get("ok"):
                raise RuntimeError(json.dumps(accepted))
            results = []
            for task in accepted["tasks"]:
                for _ in range(22):
                    task = unpack(await session.call_tool("get_task", {"task_id": task["task_id"], "wait_seconds": 30}))["task"]
                    if task["state"] in {"succeeded", "failed", "cancelled"}:
                        break
                results.append(task)
    by_kind = {task["kind"]: task for task in results}
    checks = {"all_succeeded": all(t["state"] == "succeeded" for t in results)}
    if checks["all_succeeded"]:
        if "vision" in by_kind:
            vision = by_kind["vision"]["result"]
            checks["vision_color"] = "blue" in vision["text"].lower() and not vision["truncated"]
        if "document" in by_kind:
            doc = by_kind["document"]["result"]
            md = Path(doc["artifacts"][0]["path"]).read_text(encoding="utf-8")
            checks["pdf_text_and_order"] = "ALPHA" in md and "BETA" in md and md.index("BETA") < md.index("ALPHA") and doc["pages"] == [2, 1] and doc["complete"]
        if "speech" in by_kind:
            speech = by_kind["speech"]["result"]
            with wave.open(speech["artifacts"][0]["path"], "rb") as audio:
                checks["valid_wav"] = audio.getframerate() == 24000 and audio.getnchannels() == 1 and audio.getnframes() > 0
        checks["models"] = all(t["result"]["model"] == ("gemini-3.8-flash-tts" if t["kind"] == "speech" else "gemini-3.8-flash") for t in results)
    report = {"tested_at": datetime.now(timezone.utc).isoformat(), "passed": all(checks.values()), "checks": checks, "tasks": results}
    output = folder / "result.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(output), **report}, ensure_ascii=True, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

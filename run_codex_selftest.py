"""Explicit, paid harness integration check. Temporary overrides only; never reads keys/auth files."""
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from agent_mcp.config import load_settings

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "outputs" / "codex-harness-test" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def main():
    codex = shutil.which("codex")
    if not codex:
        raise SystemExit("Codex CLI not found in PATH")
    settings = load_settings(ROOT / "config.json")
    test = settings.model_dump(mode="json")
    test.update(max_output_tokens=512, text_timeout_seconds=60, media_timeout_seconds=120, rate_limit_retries=0)
    test["models"][test["default_models"]["image"]]["image_size"] = "512"
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT.parent / "latest_run.txt").write_text(str(OUT), encoding="utf-8")
    config = OUT / "config.small.json"
    config.write_text(json.dumps(test, ensure_ascii=False, indent=2), encoding="utf-8")
    audio = ROOT / "inputs" / "codex-test.wav"
    if not audio.is_file():
        raise SystemExit("Prepare inputs/codex-test.wav with the supplied local speech script first")
    python = ROOT / ".venv" / "Scripts" / "python.exe"
    def literal(value):
        return "'" + str(value).replace("'", "") + "'"
    override = "mcp_servers.agent-mcp={command=" + literal(python) + ",args=['-m','agent_mcp','--config'," + literal(config) + ",'serve'],cwd=" + literal(ROOT) + ",required=true,startup_timeout_sec=20,tool_timeout_sec=45,default_tools_approval_mode='approve',enabled_tools=['list_capabilities','submit_batch','submit_image','get_task']}"
    prompt = """Perform this small, explicitly authorized paid MCP integration test. Use ONLY the agent-mcp MCP tools.
Do not use shell, browse, inspect credentials/auth files, modify config, or call any other service/tool.
1. Call list_capabilities. Verify defaults text=deepseek-text, audio=gemini-audio, image=gemini-image, and no OpenAI provider or transcription tool.
2. Use submit_batch to submit two tasks WITHOUT model arguments:
   text: prompt='Return only a Python function add(a,b) returning a+b.', max_output_tokens=128.
   audio: file_path='AUDIO_PATH', prompt='Transcribe the spoken sentence only.', max_output_tokens=256.
3. Submit ONE image WITHOUT a model argument: 'One solid blue circle centered on a plain white background. No text. Return one image only.'
4. Query these IDs with get_task(wait_seconds=30) until terminal, at most 5 polls each. A get_task ok=true does not mean task succeeded.
5. If the image succeeded, submit exactly ONE edit WITHOUT a model argument using its returned image path as reference_paths: 'Change only the blue circle to red. Keep the white background. Return one image only.' Poll similarly.
Never retry failed tasks or submit replacements. Use small requests only. Stop the affected check if an API error occurs.
Final response MUST be compact JSON containing checks (name, task_id, state, model_alias, actual model, text, usage, artifacts, error), and overall passed boolean.
Audio passes if the transcript conveys: The test number is seven. Text passes if code correctly adds a and b.
Image and edit pass on successful API results with saved image artifacts. Do not claim visual inspection; the caller will verify artifacts separately.
""".replace("AUDIO_PATH", str(audio).replace("\\", "/"))
    (OUT / "prompt.txt").write_text(prompt, encoding="utf-8")
    command = [codex, "exec", "--ignore-user-config", "--ephemeral", "--skip-git-repo-check", "--disable", "apps",
        "--sandbox", "read-only", "--json", "-C", str(ROOT), "-c", "model_reasoning_effort='low'", "-c", override,
        "-o", str(OUT / "final.json"), "-"]
    (OUT / "invocation.json").write_text(json.dumps(command[:-1], indent=2), encoding="utf-8")
    with (OUT / "events.jsonl").open("w", encoding="utf-8") as stdout, (OUT / "stderr.log").open("w", encoding="utf-8") as stderr:
        result = subprocess.run(command, input=prompt, stdout=stdout, stderr=stderr, text=True, encoding="utf-8", timeout=420)
    print(json.dumps({"codex_exit_code": result.returncode, "evidence_directory": str(OUT)}, indent=2))
    if (OUT / "final.json").is_file():
        final_text = (OUT / "final.json").read_text(encoding="utf-8")
        print(final_text)
        try:
            final = json.loads(final_text)
            checks = {check["name"]: check for check in final.get("checks", [])}
            passed = final.get("passed") is True and all(checks.get(name, {}).get("state") == "succeeded" for name in ("text", "audio", "image", "edit"))
        except (ValueError, TypeError, KeyError):
            passed = False
        return result.returncode if result.returncode else (0 if passed else 1)
    return result.returncode or 1


if __name__ == "__main__":
    raise SystemExit(main())

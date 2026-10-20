import argparse
import asyncio
import getpass
import json
import logging
import shutil
import sys
import warnings
from pathlib import Path

from .config import SUPPORTED, load_settings
from .providers import Providers
from .security import AgentError, Credentials, FilePolicy
from .tasks import TERMINAL, TaskManager, TaskRequest

ROOT = Path(__file__).resolve().parent.parent


async def self_test(settings, args):
    alias = args.model or settings.default_models.get(args.kind or "text")
    spec = settings.models.get(alias)
    if not spec:
        raise AgentError("invalid_model", "Specify a configured model alias")
    kind = args.kind or spec.capabilities[0]
    files = FilePolicy(settings)
    manager = TaskManager(settings, Providers(settings, files, Credentials(settings.credential_service)), files)
    manager.start()
    try:
        from .server import DOCUMENT_PROMPT
        prompt = args.prompt if args.prompt is not None else (DOCUMENT_PROMPT if kind == "document" else "Reply with OK.")
        request = TaskRequest(kind=kind, model=alias, prompt=prompt, file_path=args.file,
                              reference_paths=args.reference or [], max_output_tokens=args.max_output_tokens,
                              file_paths=args.image or [], pages=args.pages, voice=args.voice, style=args.style)
        task = manager.submit([request])[0]
        while task["state"] not in TERMINAL:
            await asyncio.sleep(0.2)
            task = manager.get(task["task_id"])
        print(json.dumps(task, ensure_ascii=False, indent=2))
        return 0 if task["state"] == "succeeded" else 1
    finally:
        await manager.close()


def main():
    parser = argparse.ArgumentParser(description="Local agent MCP; secrets live in Windows Credential Manager")
    parser.add_argument("--config", type=Path, default=ROOT / "config.json")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Create config.json from the example without overwriting existing configuration")
    commands.add_parser("serve", help="Run MCP over stdio; stdout is reserved for protocol messages")
    commands.add_parser("doctor", help="Validate configuration and check the credential backend without reading keys")
    for command in ("set-key", "delete-key"):
        command_parser = commands.add_parser(command)
        command_parser.add_argument("provider", choices=sorted(SUPPORTED))
    live = commands.add_parser("self-test", help="Make ONE real paid task using a configured alias")
    live.add_argument("--model", help="Configured alias; omitted uses the default for --kind (text by default)")
    live.add_argument("--kind", choices=["text", "knowledge", "image", "audio", "vision", "document", "speech"])
    live.add_argument("--prompt", help="Task text; document defaults to faithful extraction; speech reads this verbatim")
    live.add_argument("--file", help="Allowed absolute audio/PDF path")
    live.add_argument("--reference", action="append", help="Allowed absolute image path; repeat for multiple images")
    live.add_argument("--max-output-tokens", type=int, help="Lower the text/audio output budget for small checks")
    live.add_argument("--image", action="append", help="Allowed absolute image path for vision; repeat for multiple images")
    live.add_argument("--pages", type=int, nargs="+", help="1-based PDF page numbers in upload order")
    live.add_argument("--voice", help="Prebuilt speech voice")
    live.add_argument("--style", help="Speech delivery style, separate from verbatim --prompt")
    args = parser.parse_args()
    try:
        if args.command == "init":
            if args.config.exists():
                raise AgentError("config_exists", "Configuration already exists; edit it directly")
            with args.config.open("xb") as target, (ROOT / "config.example.json").open("rb") as source:
                shutil.copyfileobj(source, target)
            settings = load_settings(args.config)
            for directory in [*settings.allowed_input_dirs, settings.output_dir]:
                directory.mkdir(parents=True, exist_ok=True)
            print("Created configuration and media directories. Set keys with set-key.")
            return 0
        settings = load_settings(args.config)
        credentials = Credentials(settings.credential_service)
        if args.command == "set-key":
            # Abort if getpass would fall back to echoing input in a noninteractive shell.
            if not sys.stdin.isatty():
                raise AgentError("interactive_required", "Run set-key in an interactive terminal; never pass keys as arguments")
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                value = getpass.getpass(f"{args.provider} API key (hidden): ")
            credentials.set(args.provider, value)
            print("Credential stored in Windows Credential Manager.")
        elif args.command == "delete-key":
            credentials.delete(args.provider)
            print("Credential deleted.")
        elif args.command == "doctor":
            backend = credentials.backend()
            print(json.dumps({"config_valid": True, "credential_backend": type(backend).__name__,
                "keys_read": False, "models": list(settings.models), "input_dirs": [str(p) for p in settings.allowed_input_dirs],
                "output_dir": str(settings.output_dir)}, indent=2))
        elif args.command == "self-test":
            return asyncio.run(self_test(settings, args))
        elif args.command == "serve":
            logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(message)s")
            logging.getLogger("httpx").setLevel(logging.WARNING)
            logging.getLogger("httpcore").setLevel(logging.WARNING)
            from .server import create_server
            create_server(settings).run(transport="stdio")
        return 0
    except AgentError as exc:
        print(json.dumps({"error": exc.as_dict()}, ensure_ascii=False), file=sys.stderr)
        return 1
    except Exception:
        # Config validation errors may quote forbidden fields (including mistakenly supplied secrets).
        print("Failed to start or validate configuration. Check file paths, allowed fields, and installed dependencies.", file=sys.stderr)
        return 1

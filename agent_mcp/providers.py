import asyncio
import base64
import json
import random
import re
import ssl
import logging
from urllib.parse import urlsplit
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

from .config import ModelSpec, Settings
from .security import AgentError, Credentials, FilePolicy

BASE_URLS = {"deepseek": "https://api.deepseek.com", "gemini": "https://generativelanguage.googleapis.com/v1beta"}
log = logging.getLogger(__name__)


class Providers:
    def __init__(self, settings: Settings, files: FilePolicy, credentials: Credentials, client: httpx.AsyncClient | None = None):
        self.settings, self.files, self.credentials = settings, files, credentials
        self.client = client or httpx.AsyncClient(http2=settings.http2_enabled,
            timeout=httpx.Timeout(None, connect=20, write=30, pool=20), follow_redirects=False)
        self.owns_client = client is None

    async def close(self):
        if self.owns_client:
            await self.client.aclose()

    def retry_delay(self, value: str | None, attempt: int) -> float:
        delay = self.settings.retry_base_seconds * (2 ** attempt) + random.uniform(0, 0.2)
        if value:
            try:
                delay = float(value)
            except ValueError:
                try:
                    when = parsedate_to_datetime(value)
                    delay = (when - datetime.now(timezone.utc)).total_seconds()
                except (ValueError, TypeError):
                    pass
        return max(0, min(delay, self.settings.max_retry_delay_seconds))

    @staticmethod
    def tls_error(exc):
        current, seen = exc, set()
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            if isinstance(current, ssl.SSLCertVerificationError):
                return AgentError("tls_certificate", "TLS certificate verification failed; verify the trusted CA/network configuration. Not retried")
            if isinstance(current, ssl.SSLError) and not isinstance(current, (ssl.SSLWantReadError, ssl.SSLWantWriteError)):
                return AgentError("tls_error", "TLS transport failed; upstream completion is uncertain. Check network/proxy stability; certificate verification remains enabled. Not retried")
            current = current.__cause__ or current.__context__
        return AgentError("network", "Network request failed; request was not automatically retried")

    @staticmethod
    def official_file_url(url):
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError:
            raise AgentError("upstream_format", "Gemini returned an invalid file URL") from None
        if (parsed.scheme != "https" or parsed.hostname != "generativelanguage.googleapis.com"
                or port not in (None, 443) or parsed.username or parsed.password or parsed.fragment
                or not parsed.path.startswith(("/upload/v1beta/files", "/v1beta/files/"))):
            raise AgentError("upstream_format", "Gemini returned an unexpected file URL")
        return url

    async def post(self, provider: str, route: str, method="POST", raw_response=False, retry_rate_limit=True, **kwargs) -> dict:
        # No API key appears in a URL, config file, tool argument, or error message.
        key = await asyncio.to_thread(self.credentials.get, provider)
        headers = {"x-goog-api-key": key} if provider == "gemini" else {"Authorization": "Bearer " + key}
        headers.update(kwargs.pop("headers", {}))
        url = self.official_file_url(route) if route.startswith("https://") and provider == "gemini" else BASE_URLS[provider] + route
        retries = self.settings.rate_limit_retries if retry_rate_limit else 0
        for attempt in range(retries + 1):
            try:
                async with self.client.stream(method, url, headers=headers, **kwargs) as response:
                    status = response.status_code
                    if status == 429:
                        # Billing/quota failures also use HTTP 429. They cannot be repaired by retries.
                        error_bytes = bytearray()
                        async for chunk in response.aiter_bytes():
                            error_bytes.extend(chunk)
                            if len(error_bytes) > 8192:
                                break
                        error = {}
                        if len(error_bytes) <= 8192:
                            try:
                                body = json.loads(error_bytes)
                                if isinstance(body, dict) and isinstance(body.get("error"), dict):
                                    error = body["error"]
                            except (ValueError, UnicodeError):
                                pass
                        quota_codes = {"insufficient_quota", "insufficient_user_quota", "credit_balance_exhausted",
                            "billing_hard_limit_reached", "organization_spend_limit_exceeded", "project_spend_limit_exceeded",
                            "organization_usage_limit_exceeded", "usage_limit_exceeded"}
                        if error.get("code") in quota_codes or error.get("type") == "insufficient_quota":
                            # Only an allowlisted identifier is exposed, never an upstream message.
                            reason = error["code"] if error.get("code") in quota_codes else "insufficient_quota"
                            raise AgentError("quota_exceeded", f"{provider} API returned {reason}; check API credits and account/project limits. Not retried")
                    if status == 429 and attempt < retries:
                        delay = self.retry_delay(response.headers.get("retry-after"), attempt)
                    elif status >= 300:
                        code = {401: "authentication", 403: "access_denied", 429: "rate_limit"}.get(status, "upstream_http")
                        raise AgentError(code, f"{provider} API returned HTTP {status}; check model access and configuration")
                    else:
                        buffer = bytearray()
                        async for chunk in response.aiter_bytes():
                            buffer.extend(chunk)
                            if len(buffer) > self.settings.max_response_bytes:
                                raise AgentError("response_too_large", "Upstream response exceeds max_response_bytes")
                        if raw_response:
                            return {"headers": dict(response.headers), "body": bytes(buffer)}
                        if not buffer:
                            return {}
                        try:
                            result = json.loads(buffer)
                        except (ValueError, UnicodeError):
                            raise AgentError("upstream_format", "Upstream did not return valid JSON") from None
                        if not isinstance(result, dict):
                            raise AgentError("upstream_format", "Upstream response must be an object")
                        return result
                await asyncio.sleep(delay)
            except httpx.TimeoutException:
                raise AgentError("upstream_timeout", "Upstream timed out; request was not retried because completion is uncertain") from None
            except (httpx.RequestError, ssl.SSLError) as exc:
                raise self.tls_error(exc) from None
        raise AgentError("rate_limit", "Rate limit retry budget exhausted")

    async def execute(self, request, spec: ModelSpec) -> dict:
        if spec.provider == "gemini":
            return await self.gemini(request, spec)
        if request.kind in ("text", "knowledge"):
            return await self.text(request, spec)
        raise AgentError("unsupported_capability", "Provider does not implement this capability")

    @staticmethod
    def user_text(request) -> str:
        if request.context:
            return request.prompt + "\n\nContext supplied by the parent agent:\n" + request.context
        return request.prompt

    def tokens(self, request) -> int:
        return request.max_output_tokens or self.settings.max_output_tokens

    @staticmethod
    def result(text: str, model: str, usage: dict, finish: str, artifacts=None, truncated=False) -> dict:
        return {"text": text, "model": model, "usage": usage, "finish_reason": finish, "truncated": truncated, "artifacts": artifacts or []}

    async def text(self, request, spec):
        user = self.user_text(request)
        data = await self.post("deepseek", "/chat/completions", json={"model": spec.model,
            "messages": [{"role": "system", "content": request.system_prompt}, {"role": "user", "content": user}],
            "max_tokens": self.tokens(request), "thinking": {"type": spec.thinking_mode}})
        choices = data.get("choices") or []
        if not choices:
            raise AgentError("empty_result", "DeepSeek returned no candidate")
        choice = choices[0]
        finish = choice.get("finish_reason")
        if finish not in ("stop", "length"):
            raise AgentError("upstream_incomplete", "DeepSeek response was filtered, interrupted, or requires tools")
        text = (choice.get("message") or {}).get("content")
        if not text:
            raise AgentError("empty_result", "DeepSeek returned no final text")
        return self.result(text, data.get("model", spec.model), data.get("usage") or {}, finish, truncated=finish == "length")

    async def delete_remote_file(self, name):
        try:
            async with asyncio.timeout(10):
                await self.post("gemini", "/" + name, method="DELETE")
            return True
        except (AgentError, TimeoutError):
            return False

    async def upload_audio(self, data, mime):
        log.info("Gemini audio upload started bytes=%d", len(data))
        start = await self.post("gemini", "https://generativelanguage.googleapis.com/upload/v1beta/files",
            raw_response=True, headers={"X-Goog-Upload-Protocol": "resumable", "X-Goog-Upload-Command": "start",
                "X-Goog-Upload-Header-Content-Length": str(len(data)), "X-Goog-Upload-Header-Content-Type": mime},
            json={"file": {"display_name": "agent-mcp-audio"}})
        url = self.official_file_url(start["headers"].get("x-goog-upload-url", ""))
        try:
            try:
                granularity = int(start["headers"].get("x-goog-upload-chunk-granularity", "262144"))
            except (ValueError, TypeError):
                raise AgentError("upstream_format", "Gemini returned invalid upload chunk granularity") from None
            if not 1 <= granularity <= 1073741824:
                raise AgentError("upstream_format", "Gemini returned invalid upload chunk granularity")
            for offset in range(0, len(data), granularity):
                chunk = data[offset:offset + granularity]
                final = offset + len(chunk) == len(data)
                async def blocks():
                    for position in range(0, len(chunk), 65536):
                        yield chunk[position:position + 65536]
                result = await self.post("gemini", url, content=blocks(), retry_rate_limit=False,
                    headers={"Content-Type": mime, "Content-Length": str(len(chunk)), "X-Goog-Upload-Offset": str(offset),
                        "X-Goog-Upload-Command": "upload, finalize" if final else "upload"})
                log.info("Gemini audio upload accepted bytes=%d/%d", offset + len(chunk), len(data))
            uploaded = result.get("file") or {}
            if not re.fullmatch(r"files/[A-Za-z0-9_-]+", uploaded.get("name", "")):
                raise AgentError("upstream_format", "Gemini returned an invalid uploaded file identifier")
            return uploaded
        except BaseException:
            # Cancel an incomplete upload; never restart it or repeat generation automatically.
            try:
                async with asyncio.timeout(5):
                    await self.post("gemini", url, headers={"X-Goog-Upload-Command": "cancel"})
            except (AgentError, TimeoutError):
                pass
            raise

    async def gemini(self, request, spec):
        uploaded = None
        if request.kind == "audio":
            path, _ = self.files.validate(request.file_path, "audio")
            if path.stat().st_size > self.settings.gemini_audio_upload_threshold_bytes:
                data, mime, _ = self.files.read(request.file_path, "audio")
                uploaded = await self.upload_audio(data, mime)
        remote_name = uploaded["name"] if uploaded else None
        try:
            if uploaded:
                while uploaded.get("state") == "PROCESSING":
                    await asyncio.sleep(1)
                    uploaded = await self.post("gemini", "/" + remote_name, method="GET")
                    if uploaded.get("name") != remote_name:
                        raise AgentError("upstream_format", "Gemini returned inconsistent file metadata")
                if uploaded.get("state") != "ACTIVE":
                    raise AgentError("file_processing", "Gemini could not process the uploaded audio")
                self.official_file_url(uploaded.get("uri", ""))
                if urlsplit(uploaded["uri"]).path != "/v1beta/" + remote_name:
                    raise AgentError("upstream_format", "Gemini returned an inconsistent file reference")
            result = await self.gemini_content(request, spec, uploaded)
            if request.kind == "audio":
                result["audio_transport"] = "files_api" if uploaded else "inline"
            return result
        finally:
            if remote_name:
                cleaned = await self.delete_remote_file(remote_name)
                if "result" in locals():
                    result["remote_file_deleted"] = cleaned
                if not cleaned:
                    log.warning("Gemini temporary audio cleanup incomplete; provider retention policy applies")

    async def gemini_content(self, request, spec, uploaded=None):
        parts = [{"text": self.user_text(request)}]
        pdf_pages, pdf_count = None, None
        media = [(p, "image") for p in request.reference_paths]
        media.extend((p, "image") for p in request.file_paths)
        if request.kind == "document":
            pdf, pdf_pages, pdf_count = self.files.prepare_pdf(request.file_path, request.pages)
            parts[0]["text"] += "\nKeep uploaded page order. Label each page using this original 1-based page mapping: " + json.dumps(pdf_pages) + ". Return only the requested document content, without discussion of these instructions."
            parts.append({"inlineData": {"mimeType": "application/pdf", "data": base64.b64encode(pdf).decode("ascii")}})
        if request.kind == "audio":
            if uploaded:
                parts.append({"fileData": {"mimeType": uploaded["mimeType"], "fileUri": uploaded["uri"]}})
            else:
                media.append((request.file_path, "audio"))
        for filename, kind in media:
            data, mime, _ = self.files.read(filename, kind)
            parts.append({"inlineData": {"mimeType": mime, "data": base64.b64encode(data).decode("ascii")}})
        config = {"maxOutputTokens": self.tokens(request)}
        if request.kind == "image":
            # Text token budgets do not cap generated image dimensions or image cost.
            config = {"responseModalities": ["TEXT", "IMAGE"],
                "imageConfig": {"imageSize": spec.image_size, "aspectRatio": spec.image_aspect_ratio}}
        if request.kind == "speech":
            parts = [{"text": request.prompt}]
            style = request.style if request.style is not None else self.settings.speech_style
            if style:
                parts[0]["speech_metadata"] = {"style": style}
            config = {"responseModalities": ["AUDIO"], "maxOutputTokens": self.settings.speech_max_output_tokens,
                "speechConfig": {"voiceConfig": {"voice": request.voice or self.settings.speech_voice}}}
        elif request.kind in ("vision", "document"):
            config["responseModalities"] = ["TEXT"]
            config["thinkingConfig"] = {"thinkingLevel": self.settings.understanding_thinking_level.upper()}
        body = {"contents": [{"role": "user", "parts": parts}], "generationConfig": config}
        search_enabled = request.kind == "knowledge" and self.settings.knowledge_search_enabled
        if search_enabled:
            body["tools"] = [{"google_search": {}}]
        if request.system_prompt and request.kind != "speech":
            body["systemInstruction"] = {"parts": [{"text": request.system_prompt}]}
        encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > self.settings.gemini_max_request_bytes:
            raise AgentError("request_too_large", "Encoded Gemini request exceeds gemini_max_request_bytes")
        data = await self.post_gemini(spec.model, encoded)
        if (data.get("promptFeedback") or {}).get("blockReason"):
            raise AgentError("filtered", "Gemini blocked the input")
        candidates = data.get("candidates") or []
        if not candidates:
            raise AgentError("empty_result", "Gemini returned no candidate")
        candidate = candidates[0]
        finish = candidate.get("finishReason")
        if finish not in ("STOP", "MAX_TOKENS"):
            raise AgentError("upstream_incomplete", "Gemini response was filtered or incomplete")
        if request.kind == "speech" and finish != "STOP":
            raise AgentError("upstream_incomplete", "Speech output was truncated; no complete audio artifact saved")
        text_parts, artifacts = [], []
        for part in (candidate.get("content") or {}).get("parts", []):
            if part.get("thought"):
                continue
            if "text" in part:
                text_parts.append(part["text"])
            inline = part.get("inlineData")
            if inline and request.kind == "image":
                artifacts.append(self.files.save_image(inline.get("data"), inline.get("mimeType")))
            if inline and request.kind == "speech":
                if artifacts:
                    raise AgentError("upstream_format", "Expected one complete WAV response")
                artifacts.append(self.files.save_audio(inline.get("data"), inline.get("mimeType")))
        if request.kind == "image" and not artifacts:
            raise AgentError("empty_result", "Gemini returned no generated image")
        if request.kind == "speech" and not artifacts:
            raise AgentError("empty_result", "Gemini returned no generated audio")
        if request.kind not in ("image", "speech") and not text_parts:
            raise AgentError("empty_result", "Gemini returned no final text")
        result = self.result("\n".join(text_parts), data.get("modelVersion", spec.model), data.get("usageMetadata") or {}, finish, artifacts, finish == "MAX_TOKENS")
        if request.kind == "document":
            artifact = self.files.save_document(result["text"])
            result.update(text=result["text"][:self.settings.document_preview_characters], artifacts=[artifact],
                preview_truncated=len(result["text"]) > self.settings.document_preview_characters,
                pages=pdf_pages, source_page_count=pdf_count, complete=finish == "STOP")
        if request.kind == "knowledge":
            grounding = candidate.get("groundingMetadata") or {}
            sources = [chunk["web"] for chunk in grounding.get("groundingChunks", []) if chunk.get("web")]
            queries = [query for query in grounding.get("webSearchQueries", []) if query.strip()]
            searched = bool(queries or sources)
            result.update(search_enabled=search_enabled, live_search=searched,
                knowledge_source="web" if searched else "model", sources=sources,
                search_queries=queries, grounding_metadata=grounding)
        return result

    async def post_gemini(self, model, encoded):
        # Passing JSON preserves the correct Content-Type; the size check uses the same compact serialization.
        return await self.post("gemini", f"/models/{model}:generateContent", json=json.loads(encoded))

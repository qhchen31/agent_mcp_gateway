import asyncio
import pytest
from agent_mcp.security import AgentError
from agent_mcp.tasks import TaskManager, TaskRequest

class ControlledProviders:
    def __init__(self):
        self.release = asyncio.Event()
        self.started = []
        self.closed = False
    async def execute(self, request, spec):
        self.started.append((request.prompt, spec.provider))
        await self.release.wait()
        return {"text": request.prompt}
    async def close(self):
        self.closed = True

async def tick():
    for _ in range(8):
        await asyncio.sleep(0)

async def test_concurrency_and_provider_fairness(settings, files):
    settings.global_concurrency = 3
    settings.provider_concurrency = {"deepseek": 1, "gemini": 2}
    provider = ControlledProviders()
    manager = TaskManager(settings, provider, files)
    manager.start()
    try:
        tasks = manager.submit([TaskRequest(kind="text", model=m, prompt=str(i)) for i, m in enumerate(["ds", "ds", "ds", "gt", "gt", "gt"])])
        await tick()
        assert manager.running == {"deepseek": 1, "gemini": 2}
        assert [p for _, p in provider.started] == ["deepseek", "gemini", "gemini"]
        assert sum(j.state == "queued" for j in manager.jobs.values()) == 3
        provider.release.set()
        await tick()
        await tick()
        assert all(manager.get(j["task_id"])["state"] == "succeeded" for j in tasks)
    finally:
        await manager.close()
    assert provider.closed

async def test_atomic_batch_and_queue_limit(settings, files):
    manager = TaskManager(settings, ControlledProviders(), files)
    with pytest.raises(AgentError):
        manager.submit([TaskRequest(kind="text", model="ds", prompt="ok"), TaskRequest(kind="text", model="missing", prompt="bad")])
    assert not manager.jobs
    settings.queue_limit = 1
    with pytest.raises(AgentError, match="queue capacity"):
        manager.submit([TaskRequest(kind="text", model="ds", prompt="ok")] * 2)
    assert not manager.jobs

async def test_cancel_releases_slots(settings, files):
    settings.global_concurrency = 1
    provider = ControlledProviders()
    manager = TaskManager(settings, provider, files)
    manager.start()
    try:
        tasks = manager.submit([TaskRequest(kind="text", model="ds", prompt=str(i)) for i in range(3)])
        await tick()
        assert (await manager.cancel(tasks[1]["task_id"]))["state"] == "cancelled"
        assert (await manager.cancel(tasks[0]["task_id"]))["state"] == "cancelled"
        await tick()
        assert manager.get(tasks[2]["task_id"])["state"] == "running"
        assert sum(manager.running.values()) == 1
        provider.release.set()
        await tick()
        assert manager.get(tasks[2]["task_id"])["state"] == "succeeded"
        assert sum(manager.running.values()) == 0
    finally:
        await manager.close()

async def test_timeout_and_prompt_cleanup(settings, files):
    settings.text_timeout_seconds = 0.01
    manager = TaskManager(settings, ControlledProviders(), files)
    manager.start()
    try:
        job = manager.submit([TaskRequest(kind="text", model="ds", prompt="PRIVATE PROMPT")])[0]
        await asyncio.sleep(0.05)
        result = manager.get(job["task_id"])
        assert result["error"]["code"] == "task_timeout"
        assert "PRIVATE" not in str(result)
        assert manager.jobs[job["task_id"]].request is None
    finally:
        await manager.close()

async def test_unexpected_exception_redacted(settings, files):
    class Broken(ControlledProviders):
        async def execute(self, *args):
            raise RuntimeError("SECRET API KEY AND PROMPT")
    manager = TaskManager(settings, Broken(), files)
    manager.start()
    try:
        job = manager.submit([TaskRequest(kind="text", model="ds", prompt="x")])[0]
        await tick()
        result = manager.get(job["task_id"])
        assert result["error"]["code"] == "internal_error"
        assert "SECRET" not in str(result)
    finally:
        await manager.close()

async def test_retention_bound_and_expiry(settings, files):
    settings.max_completed_tasks = 1
    provider = ControlledProviders()
    provider.release.set()
    manager = TaskManager(settings, provider, files)
    manager.start()
    try:
        tasks = manager.submit([TaskRequest(kind="text", model="ds", prompt=str(i)) for i in range(2)])
        await tick()
        assert len(manager.jobs) == 1
        with pytest.raises(AgentError):
            manager.get(tasks[0]["task_id"])
        manager.jobs[tasks[1]["task_id"]].ended -= settings.result_ttl_seconds + 1
        with pytest.raises(AgentError):
            manager.get(tasks[1]["task_id"])
    finally:
        await manager.close()

@pytest.mark.parametrize("payload", [
    {"kind": "text", "model": "ds", "prompt": ""},
    {"kind": "text", "model": "ds", "prompt": "x", "max_output_tokens": 999999},
    {"kind": "image", "model": "gi", "prompt": "x", "max_output_tokens": 12},
    {"kind": "text", "model": "ds", "prompt": "x", "file_path": "file.wav"},
    {"kind": "audio", "model": "ga", "prompt": "x"},
    {"kind": "image", "model": "ds", "prompt": "x"},
])
def test_invalid_requests(settings, files, payload):
    with pytest.raises(AgentError):
        TaskManager(settings, ControlledProviders(), files).submit([TaskRequest(**payload)])

async def test_defaults_and_explicit_override(settings, files):
    provider = ControlledProviders()
    manager = TaskManager(settings, provider, files)
    manager.start()
    try:
        request = TaskRequest(kind="text", prompt="default")
        task = manager.submit([request])[0]
        assert task["model_alias"] == "ds" and task["provider"] == "deepseek"
        assert request.model is None
        task = manager.submit([TaskRequest(kind="text", prompt="override", model="gt")])[0]
        assert task["provider"] == "gemini"
        provider.release.set()
        await tick()
    finally:
        await manager.close()

async def test_failure_has_no_cross_provider_fallback(settings, files):
    class Failed(ControlledProviders):
        async def execute(self, request, spec):
            self.started.append(spec.provider)
            raise AgentError("authentication", "test failure")
    provider = Failed()
    manager = TaskManager(settings, provider, files)
    manager.start()
    try:
        task = manager.submit([TaskRequest(kind="text", prompt="x")])[0]
        await tick()
        assert manager.get(task["task_id"])["state"] == "failed"
        assert provider.started == ["deepseek"]
    finally:
        await manager.close()

async def test_knowledge_distinct_routing_and_prompt(settings, files):
    provider = ControlledProviders()
    manager = TaskManager(settings, provider, files)
    manager.start()
    try:
        tasks = manager.submit([TaskRequest(kind="text", prompt="ordinary task"), TaskRequest(kind="knowledge", prompt="What is photosynthesis?")])
        assert tasks[0]["provider"] == "deepseek"
        assert tasks[1]["provider"] == "gemini" and tasks[1]["model_alias"] == "gk"
        request = manager.jobs[tasks[1]["task_id"]].request
        assert "Use available search tools" in request.system_prompt
        provider.release.set()
        await tick()
        answer = manager.get(tasks[1]["task_id"])["result"]
        assert answer["knowledge_source"] == "model" and answer["live_search"] is False
        assert "knowledge_source" not in manager.get(tasks[0]["task_id"])["result"]
        with pytest.raises(AgentError):
            manager.submit([TaskRequest(kind="knowledge", model="ds", prompt="wrong capability")])
    finally:
        await manager.close()

async def test_knowledge_uses_text_timeout(settings, files):
    settings.text_timeout_seconds = 0.01
    settings.media_timeout_seconds = 10
    manager = TaskManager(settings, ControlledProviders(), files)
    manager.start()
    try:
        task = manager.submit([TaskRequest(kind="knowledge", prompt="test")])[0]
        await asyncio.sleep(0.05)
        assert manager.get(task["task_id"])["error"]["code"] == "task_timeout"
    finally:
        await manager.close()

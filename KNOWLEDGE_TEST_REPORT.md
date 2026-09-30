# 世界知识接口功能测试

测试时间：2026-10-01 01:51（北京时间）。

新增独立 MCP 工具 `query_knowledge`，任务类型为 `knowledge`，默认配置别名 `gemini-knowledge`，实际模型 `gemini-3.8-flash`。普通 `submit_text` 仍默认 `deepseek-text`。两条默认路由均可在 config.json 中分别修改。

离线测试：43 项通过，覆盖实际 MCP 工具发现与任务生命周期、知识默认路由、能力校验、专用提示词、结果标记和文本超时，以及已有功能回归。增加了搜索开关、普通文本不附加搜索、开启搜索但未实际搜索时的标记、完整来源元数据保存的验证。

真实测试使用官方 MCP Python SDK 通过 stdio 启动生产服务，调用 `query_knowledge` 时省略 model，仅提交一次问题：“请使用 Google 搜索核实法国首都的名称，只用一句话回答。”

结果：成功，答案为“法国的首都是巴黎（Paris）。”，实际模型为 `gemini-3.8-flash`，未截断，运行约 4.687 秒。输入 252 tokens、回答 14 tokens、思考 195 tokens，总计 461 tokens（平台原始 usage）。输出预算设为 256 tokens。搜索使用量单独计费，不由 token 预算限制。

11 项检查全部通过：独立工具发现、两种默认路由区分、knowledge 类型、默认别名、执行成功、实际模型、正确答案、搜索开启、实际搜索、来源返回、无截断。证据：`outputs/knowledge-self-test/20260930T175138Z/result.json`。

实际搜索词为 `capital of France`，来源为 wikipedia.org，返回原始 Google 来源跳转链接、groundingSupports 和 searchEntryPoint。结果标记 `search_enabled=true`、`live_search=true`、`knowledge_source="web"`。

此轮验证的是 MCP 客户端到真实 Gemini API 的调用链；未重复执行此前的 Codex CLI 图像/音频自检。接口默认允许联网，Gemini 决定是否执行搜索，没有搜索证据时标记模型知识回答。配置 `knowledge_search_enabled` 可调整开关。这次小样本不代表所有知识问题都能准确回答。

用户确认联网前的纯模型知识测试也成功，152 tokens；历史证据保留于 `outputs/knowledge-self-test/20260930T174725Z/result.json`。这两次真实请求合计 613 tokens，后一次执行了 1 个搜索查询。

复现（会调用真实 API）：

```powershell
Set-Location 'E:\Project\Script\agent_mcp'
.\.venv\Scripts\python.exe run_knowledge_selftest.py
```

# Gemini 弃用参数检查

检查日期：2026-10-07（Asia/Shanghai）。依据 Google AI Studio 的服务通知 `[Action Required] Update thinking_budget and sampling parameters` 及官方参数迁移文档。

## 结论

当前网关未向 Gemini 发送通知中列出的弃用参数，无需修改生产请求逻辑、模型 ID、凭据或 Codex 注册。

| 通知涉及的参数 | REST 对应名称 | 当前 Gemini 请求 |
| --- | --- | --- |
| thinking_budget | thinkingBudget | 未发送 |
| temperature | temperature | 未发送 |
| top_p | topP | 未发送 |
| top_k | topK | 未发送 |

网关使用 httpx 直接构造 REST JSON，不经过会补充生成参数的 Google SDK。`agent_mcp/providers.py` 中，文本/知识/音频的 generationConfig 仅包含 maxOutputTokens；图像生成/编辑包含 responseModalities 和 imageConfig。知识查询另外添加 Google Search 工具。

`max_output_tokens` 转换为 maxOutputTokens，是输出 token 上限，不是已弃用的 thinking_budget。网关不发送 thinkingConfig，使用模型默认思考设置；通知明确允许省略思考配置。

配置中的 thinking_mode 仅影响 DeepSeek Chat Completions 的 thinking.type，不会传给 Gemini。即使 Gemini 别名上该共享字段被设为 enabled，也不会产生 Gemini 思考预算请求。

通知指出 generateContent 仍受支持，建议新项目使用 Interactions；本次参数检查不要求迁移 API。不能仅凭账户/项目级通知将违规请求归因于本网关，其他使用同一项目的客户端仍可能发送这些参数。

## 验证

2026-10-21 补充：0.3 新增 vision/document 时以受支持的 thinkingConfig.thinkingLevel=LOW 控制思考；此项不是弃用的 thinkingBudget。TTS 不附加思考配置。下文“未发送 thinkingConfig”描述的是2026-10-07检查时的旧版本。

新增 5 个请求体回归用例：文本、知识、音频、文生图和参考图编辑。用 httpx MockTransport 检查实际序列化后的请求，递归排查蛇形/驼峰两类弃用字段，验证 DeepSeek 思考设置不会泄漏到 Gemini，并核对现有输出预算和图像配置。

测试结果：48 项全部通过（含已有测试）。测试不读取真实 API 密钥、不发送上游请求、不产生费用。该检查证明当前代码的请求构造行为，不代表对未来所有模型兼容性的承诺。

复现：

```powershell
Set-Location 'E:\Project\Script\agent_mcp'
.\.venv\Scripts\python.exe -m pytest -q
```

参考：[官方生成参数迁移说明](https://ai.google.dev/gemini-api/docs/generate-content/whats-new-gemini-3.5)、[官方思考参数说明](https://ai.google.dev/gemini-api/docs/generate-content/thinking)。

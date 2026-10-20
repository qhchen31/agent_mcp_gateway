# 本地 Agent MCP（0.3）

供 Codex 等本地 harness 委派独立任务，父 agent 负责拆分、提供上下文与整合。子模型不继承父 agent 的历史、终端或工具权限。

| 任务 | 默认模型 |
| --- | --- |
| 文本、代码、建议 | DeepSeek V4.1 Flash，API ID deepseek-flash |
| 世界知识问答 | gemini-3.8-flash，独立 knowledge 类型 |
| 图片理解、OCR、PDF 提取 | gemini-3.8-flash |
| 语音生成（单人 WAV） | gemini-3.8-flash-tts |
| 音频理解、摘要、问答、转录 | gemini-3.8-flash |
| 图像生成、参考图编辑 | gemini-3.1-flash-image |

Gemini 3.8 Flash 支持图像/音频输入，但不能生成图像，绘图因此使用独立 Flash Image 模型。保留 gemini-text 别名，可显式选择 Gemini 处理文本。

已删除工具内 OpenAI provider、相关模型配置和专用转录入口。已有 OpenAI 凭据不再使用，本次未删除凭据。Codex 父 agent 仍用其已有登录方式。

## 使用与密钥

支持 Windows 与 Linux，要求 Python 3.11+。Windows 使用 Credential Manager；Linux 使用桌面 Secret Service（例如 GNOME Keyring），不回退明文或环境变量密钥。Linux 安装、密钥加载和 Codex 插件说明见 [Linux 与插件接入](LINUX_SETUP.md)。首次安装 Windows（PowerShell，按需调整克隆位置）：

```powershell
git clone git@github.com:qhchen31/agent_mcp_gateway.git 'E:\Project\Script\agent_mcp'
Set-Location 'E:\Project\Script\agent_mcp'
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[test]'
.\.venv\Scripts\python.exe -m agent_mcp init
```

`init` 会根据配置文件所在目录生成绝对输入/输出路径，无需手动替换盘符。公开模板使用相对路径占位符，应通过 `init` 初始化。Windows harness 示例仍使用 `E:\Project\Script\agent_mcp`，请同步调整 MCP 启动路径。

然后在交互式 PowerShell 中保存密钥：

```powershell
Set-Location 'E:\Project\Script\agent_mcp'
.\.venv\Scripts\python.exe -m agent_mcp set-key deepseek
.\.venv\Scripts\python.exe -m agent_mcp set-key gemini
.\.venv\Scripts\python.exe -m agent_mcp doctor
```

密钥隐藏输入并存入 Windows 凭据管理器。doctor 不读取密钥或请求 API。未配置的平台不影响另一平台，调用时返回 missing_credential。更新密钥再次 set-key；删除用 delete-key deepseek 或 delete-key gemini。

重新安装：python -m venv .venv，然后用该虚拟环境的 python -m pip install -e '.[test]'。无配置时运行 python -m agent_mcp init，已有配置不会覆盖。requirements.lock.txt 保存已测试 Windows/Python 3.12 依赖。

## MCP 工具

| 工具 | 用途 |
| --- | --- |
| list_capabilities | 模型别名、default_models 和执行限制；不保证账户权限 |
| submit_text | 文本/代码，model 省略时默认 DeepSeek |
| query_knowledge | 世界知识问答，默认 Gemini 3.8 Flash，允许 Google 搜索 |
| submit_vision | 图片转文本，默认 Gemini 3.8 Flash |
| submit_document | PDF 选页提取／问答，保存 Markdown 并返回预览 |
| submit_speech | 单人文本转语音，正文与 style 分开，保存 WAV |
| submit_audio | 音频理解/转录，model 省略时默认 Gemini 3.8 Flash |
| submit_image | 文生图/参考图编辑，默认 Gemini Flash Image |
| submit_batch | 整体校验与原子入队，按 kind 分别选择默认模型 |
| get_task | 查询状态/结果，可等待 0–30 秒 |
| cancel_task | 取消本地任务 |
| list_tasks | 当前进程的任务元数据 |

先 list_capabilities，再 submit_batch，然后父 agent 继续工作，最后 get_task。例：

```json
{"tasks":[{"kind":"text","prompt":"检查代码边界条件","context":"父 agent 提供的代码"},{"kind":"text","model":"gemini-text","prompt":"提出另一种方案"},{"kind":"audio","file_path":"E:\\Project\\Script\\agent_mcp\\inputs\\meeting.wav","prompt":"提取行动项"}]}
```

显式 model 必须为配置别名；调用失败不切换平台。提交时 ok=true 仅代表接受任务，需检查 task.state。状态为 queued → running → succeeded/failed/cancelled。结果包含 text、实际模型、原始 usage、finish_reason、truncated、artifacts 与耗时。截断内容仍返回且标记；过滤或无输出不标记成功。usage 不代表货币费用。

世界知识查询使用独立 `query_knowledge` 工具，参数为 `question`、可选 `context`、`max_output_tokens` 和模型别名 `model`。例如：

```json
{"question":"法国的首都是哪座城市？请只回答城市名。","max_output_tokens":256}
```

返回任务 ID 后用 `get_task` 获取答案；批量提交可用 `kind="knowledge"`、`prompt` 指定问题。默认别名 `gemini-knowledge` 与普通文本默认 `deepseek-text` 分开配置，模型别名必须具备对应能力。知识任务使用文本超时。

该接口默认接入 Gemini 官方 Google Search 工具，模型根据问题决定是否实时搜索；可在问题中明确要求搜索核查。专用提示词要求区分事实与不确定性、不捏造来源，并把检索内容作为证据。普通文本/代码、音频和图像入口不因此增加搜索工具。

知识结果包含 `search_enabled`（工具是否开启）、`live_search`（是否返回搜索执行证据）、`knowledge_source`（web 或 model）、`sources`（来源标题和链接）、`search_queries` 与完整 `grounding_metadata`（引用关联和 Search Suggestions）。允许搜索不代表每次都会搜索，模型直接回答时 `live_search=false`。上游来源可能使用 Google 跳转链接，服务保留原始链接。父 agent 展示搜索答案时应同时提供来源，并按官方要求处理 Search Suggestions；原始 HTML 仅作为数据返回。若改配 DeepSeek 知识模型，目前仅提供模型知识回答。

新增接口参数、限额及实例见 [多模态接口说明](MULTIMODAL_GUIDE.md)。当前共 8 个任务接口（含批量）和 4 个管理接口。

## 文件与安全边界

输入必须为绝对路径，默认只读取 inputs 和 outputs；运行时再次检查解析路径与大小。参考图支持 PNG/JPEG/WebP，音频支持常见 mp3/wav/m4a/mp4/aac/ogg/flac/webm 扩展名，平台仍可能限制具体编码。媒体会上传到所选官方 API。

生成图片随机命名，保存到 outputs，不覆盖文件。返回绝对路径；编辑时通过 reference_paths 传入已有图片。任务记录过期不会删除图片，由用户管理磁盘空间。

第一版不自动下载 URL、分段长录音、保留上游会话或执行代码。Gemini 使用内联媒体，完整 base64 JSON 最多 20 MB。

按操作系统显式选择 WinVaultKeyring 或 Linux SecretService.Keyring，不使用自动选择的第三方/明文后端，也不回退明文配置/环境变量。日志不记录密钥或请求/响应全文；完成后释放原始请求对象。结果仍可能包含任务内容。凭据管理器解决误提交风险，不能隔离同用户下有脚本执行权限的进程。

## 配置

修改 config.json 后重启 MCP。公开模板为 config.example.json，本地配置、虚拟环境与输入输出被 .gitignore 排除。未知字段（包括 api_key/base_url）被拒绝，只请求两家固定官方域名。

| 配置 | 默认值 |
| --- | --- |
| default_models | text=deepseek-text，knowledge=gemini-knowledge，audio=gemini-audio，image=gemini-image，vision=gemini-vision，document=gemini-document，speech=gemini-speech |
| knowledge_search_enabled | true，仅对 Gemini knowledge 任务启用 Google Search |
| global_concurrency / provider_concurrency | 4 / 每个平台 2 |
| queue_limit | 32，仅计等待任务 |
| text_timeout_seconds / media_timeout_seconds | 180 / 600 |
| max_output_tokens | 4096，文本/音频调用可降低 |
| rate_limit_retries | 2，仅明确限流；已识别额度不足不重试 |
| retry_base_seconds / max_retry_delay_seconds | 1 / 30 |
| result_ttl_seconds / max_completed_tasks | 3600 / 256 |
| max_prompt_characters | 100000，含 prompt/context/system_prompt |
| max_input_file_bytes / max_response_bytes | 12 MiB / 64 MiB |
| gemini_max_request_bytes | 20000000，含 base64 和提示词 |
| allowed_input_dirs / output_dir | inputs、outputs / outputs |
| credential_service | local-agent-mcp |
| models | 官方 ID、能力、图像尺寸/比例、思考模式 |

DeepSeek thinking_mode 默认 disabled，节省简单任务的思考 token；可配置 enabled。图像 image_size 默认 1K，image_aspect_ratio 默认 1:1；Flash Image 可配置 512/1K/2K/4K。文本输出预算不限制图片费用。

并发按进程计算，不跨 harness 合并。执行超时包含网络/限流等待，不含排队。网络、超时、5xx 不自动重发；取消不能保证上游停止计费。重启丢失任务 ID，完成记录按 TTL/数量上限清除。不做自动货币预算或失败切换平台。

## Codex 临时接入与自检

官方 MCP Python SDK 1.x，stdio，无需开放端口。mcp.stdio.example.json 和 codex.mcp.example.toml 含 command/args/cwd。其他 harness 使用相同启动参数，外层配置结构按客户端适配。

长期注册、逐工具许可、完整参数示例和排障见 [桌面 Harness Agent 接入手册](HARNESS_INTEGRATION.md)。该文档可单独交给其他桌面 agent，包含安装、注册、调用与验证流程。Codex 示例默认提交需审批、查询/取消放行；严格人工审批还需有效 reviewer 为 user。

run_codex_selftest.py 用 CLI -c 临时注册本服务，忽略用户配置、关闭 Apps，不修改全局/项目配置。非交互默认可能拒绝 MCP 调用，因此自检临时 default_tools_approval_mode=approve，并只暴露 list_capabilities、submit_batch、submit_image、get_task 四个已授权工具；shell 保持 read-only，prompt 禁止其他工具。

以下会调用真实 API 并可能计费：

```powershell
Set-Location 'E:\Project\Script\agent_mcp'
.\prepare_test_audio.ps1
.\.venv\Scripts\python.exe run_codex_selftest.py
```

本机 Microsoft Zira 合成短录音；临时限制输出 512 tokens、图像 512×512、429 不重试。只提交一次代码、音频、图像及一次编辑，失败不重复提交。证据保存到 outputs/codex-harness-test 的独立运行目录。

CLI 退出码 0 不等于 API 任务成功，需检查 final.json 中每项 state 和 passed；视觉效果还需检查图片文件。最新报告见 CODEX_TEST_REPORT.md，旧版历史自检保留于 SELF_TEST_REPORT.md。

仓库保留文字测试报告；原始证据、媒体和运行目录仅存在于执行测试的本机，不随仓库发布。上述报告中的输出路径用于定位本机证据，克隆仓库后可运行对应脚本生成自己的记录。

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m agent_mcp self-test --max-output-tokens 128
.\.venv\Scripts\python.exe run_knowledge_selftest.py
.\.venv\Scripts\python.exe -m agent_mcp self-test --kind knowledge --prompt '法国的首都是哪座城市？' --max-output-tokens 256
.\.venv\Scripts\python.exe -m agent_mcp self-test --kind audio --file 'E:\Project\Script\agent_mcp\inputs\codex-test.wav' --prompt 'Transcribe only.' --max-output-tokens 256
.\.venv\Scripts\python.exe -m agent_mcp self-test --kind image --prompt 'A blue circle on white'
```

离线测试不读真实密钥、不调用 API。真实单项自检每次执行一个任务。常见错误代码：missing_credential、invalid_model、path_denied、queue_full、request_too_large、quota_exceeded。账户模型/区域/额度需以真实调用为准。

`run_knowledge_selftest.py` 通过真实 MCP stdio 服务只提交一次搜索核查问题，并验证工具区分、默认路由、实际模型、答案、实际搜索和来源返回。输出上限 256 tokens，包含思考 token 的实际用量以 usage 为准；Google Search 的费用另按平台规则计算，token 上限不限制搜索次数。测试证据保存至 outputs/knowledge-self-test。最新结果见 KNOWLEDGE_TEST_REPORT.md。已有 harness 需重启 MCP 服务或重新加载工具列表才能发现新接口。

## 多模态版本验收

0.3 版本真实 MCP stdio 验收与初次 PDF 截断修正记录见 [多模态测试报告](MULTIMODAL_TEST_REPORT.md)。运行 `python run_multimodal_selftest.py` 会提交读图、PDF 和 TTS 三个收费任务；可附加 `document`、`vision` 或 `speech` 仅测一项。

## 官方参考

- [DeepSeek V4.1 Flash 与 API ID](https://api-docs.deepseek.com/updates/)
- [DeepSeek 思考模式](https://api-docs.deepseek.com/guides/thinking_mode/)
- [Gemini 3.8 Flash 能力](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash)
- [Gemini Google Search 与来源元数据](https://ai.google.dev/gemini-api/docs/generate-content/google-search)
- [Gemini 图像与尺寸](https://ai.google.dev/gemini-api/docs/generate-content/image-generation)
- [MCP Python SDK 1.x](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x)
- [Codex MCP 配置](https://learn.chatgpt.com/docs/extend/mcp)
- [keyring](https://keyring.readthedocs.io/en/latest/)

## 许可证

项目使用 [MIT License](LICENSE)。第三方依赖及官方 API 服务分别遵循其自身许可证与服务条款。

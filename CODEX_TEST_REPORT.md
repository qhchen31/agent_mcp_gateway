# Codex 临时 MCP 接入测试

日期：2026-10-01（Asia/Shanghai）。本机 codex-cli 0.159.2。当前版本只提供 DeepSeek / Gemini，不再提供 OpenAI API。

## 结果

实际通过 Codex CLI 加载 MCP、读取能力、批量提交、查询任务、生成与编辑图片。四项真实任务全部 succeeded，未截断。调用均省略 model 参数，验证了配置中的默认路由。

| 检查 | 实际模型 | 运行耗时 | 结果 | 上游 total tokens |
| --- | --- | --- | --- | --- |
| 文本／代码 | deepseek-flash（官方 V4.1 Flash） | 2.766 秒 | 返回正确的 add(a,b) 函数 | 51 |
| 音频 | gemini-3.8-flash | 4.125 秒 | 准确转录 The test number is seven. | 132 |
| 图像生成 | gemini-3.1-flash-image | 8.188 秒 | 蓝色圆形、白色背景，512×512 JPEG | 925 |
| 图像编辑 | gemini-3.1-flash-image | 9.266 秒 | 圆形变红，白色背景保留，512×512 JPEG | 1198 |

两张图片已独立打开检查，并通过图像解码确认尺寸。代码输出是仅包含加法返回值的简单函数，未执行模型提供的任意代码。音频在本机离线合成，2.224 秒、98130 字节，没有上传用户私人录音。

四次子模型调用合计返回 total tokens=2306，各平台字段原样保留；这不是货币费用计算。图像生成/编辑各一次，512 分辨率；文本预算 128，音频预算 256，临时配置总输出上限 512。失败不重提，429 不重试。

## 接入过程与边界

首次 Codex 已发现 MCP，但非交互 approval policy=never 拒绝 list_capabilities，因此未提交任何子模型任务。随后使用用户已授权的临时配置：仅 agent-mcp 服务的 list_capabilities、submit_batch、submit_image、get_task 设置 approve，并暴露这四个工具。未放开其他服务或工具的审批策略。

成功运行事件中，所有 MCP 调用 server 均为 agent-mcp；未出现 shell 或其他工具调用。使用 --ignore-user-config、--ephemeral、关闭 Apps、read-only shell sandbox、命令行 -c 注入服务；未修改全局或项目 Codex 配置、未读取或修改认证文件、未显示或修改密钥。

Codex 父 agent 自身也消耗账户使用量：成功轮 CLI 报告 input_tokens=129138，其中 cached_input_tokens=114176；output_tokens=1118。初次被审批阻止的轮次报告 input_tokens=46354，其中 cached=42240，output=382。这些是多次模型轮次累计的 harness 用量，与上表子模型 API tokens 分开，不能把 2306 当成本轮总消耗。

本次验证标准 MCP 与 Codex CLI 临时接入，不代表已注册到桌面聊天或其他 harness。长期使用可参考 codex.mcp.example.toml；本次按要求仅临时验证。

## 证据与产物

以下为测试本机的相对路径；原始输出与媒体由 .gitignore 排除，不包含在 GitHub 仓库中。

- 成功轮最终结果：`outputs/codex-harness-test/20260930T173103Z/final.json`
- 成功轮 MCP 事件：`outputs/codex-harness-test/20260930T173103Z/events.jsonl`
- 临时小样本配置：`outputs/codex-harness-test/20260930T173103Z/config.small.json`
- Codex 启动参数：`outputs/codex-harness-test/20260930T173103Z/invocation.json`
- 首次审批阻止记录：`outputs/codex-harness-test/final.json`
- 蓝色圆形：`outputs/8a462aee7f9b423b8a405bcd7e43eeb5.jpg`
- 编辑后的红色圆形：`outputs/beec7c95830f42ca8acc915b0db19235.jpg`

当前 37 项离线测试通过，覆盖移除 provider 的校验、默认路由、显式覆盖、失败不切换平台、文件边界、任务调度/取消/超时和真实 stdio 握手。

可重复测试：运行 prepare_test_audio.ps1，再用项目虚拟环境运行 run_codex_selftest.py。再次运行会发起真实收费 API 请求，不应将它作为自动离线测试。

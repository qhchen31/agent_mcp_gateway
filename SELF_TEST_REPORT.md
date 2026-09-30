# 真实自检记录

> 历史记录：对应 0.1 版三平台自检。当前 0.2 版已移除 OpenAI API，以下 OpenAI 自检命令不再适用；当前结果见 CODEX_TEST_REPORT.md。

日期：2026-10-01，Asia/Shanghai。

使用当前 config.json 的模型配置和 Windows 凭据管理器中的密钥。测试提示为 `Reply with exactly OK.`，未显示或记录密钥。

| 平台 | 配置模型 | 结果 | 耗时 | 上游用量 |
| --- | --- | --- | --- | --- |
| DeepSeek | deepseek-flash | 成功，返回 OK，未截断 | 4.391 秒 | 输入 52、输出 15（含推理 13），总计 67 tokens |
| Gemini | gemini-3.8-flash | 成功，返回 OK，未截断 | 2.906 秒 | 输入 23、可见输出 1、思考 54，总计 78 tokens |
| OpenAI | gpt-4.1-mini | 生成失败，HTTP 429；单次诊断确认 error.type=insufficient_quota | 初次自检 26.391 秒，含重试 | 未返回生成用量 |

OpenAI 补充检查：GET /v1/models 返回 HTTP 200，且当前模型存在于列表。密钥可以通过该接口认证，但当前生成额度/计费状态不可用。余额、组织或项目限额需用户在平台检查；此报告未读取计费后台，不能确定具体哪个限额造成阻断。

初次 OpenAI 自检执行了配置允许的两次 429 重试，随后执行一次不重试的最小生成诊断（输出预算 16 tokens）和一次模型列表只读查询。未继续重复生成测试。随后已修正工具：识别已知额度/计费 429，返回 quota_exceeded 并停止重试。

本轮验证范围仅为三组密钥的文本调用和 OpenAI 认证诊断。未验证图像生成、图像编辑、音频理解或转录的实际权限。耗时为本次测试观测值，不是性能承诺；没有计算货币费用。

OpenAI API 额度处理后，可重新运行：

```powershell
Set-Location 'E:\Project\Script\agent_mcp'
.\.venv\Scripts\python.exe -m agent_mcp self-test --model openai-text
```

参考：[OpenAI 官方错误说明](https://developers.openai.com/api/docs/guides/error-codes)。

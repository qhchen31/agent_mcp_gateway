# 0.3 多模态验收

日期：2026-10-21（Asia/Shanghai）。服务通过真实 MCP stdio 启动，发现12个工具；提交省略model，验证各类型默认路由。没有重复运行绘图或音频理解的收费测试。

| 类型 | 实际模型 | 验收结果 | 原始 total tokens |
| --- | --- | --- | --- |
| vision | gemini-3.8-flash | 自制64×64纯蓝图片，回答Blue，未截断 | 1162 |
| document 初次 | gemini-3.8-flash | 1024预算被思考耗尽，返回MAX_TOKENS；网关正确标记truncated=true、complete=false | 2181 |
| speech | gemini-3.8-flash-tts | “The test number is seven.”生成2.36秒WAV，119398字节，24kHz／单声道／16-bit，成功解码 | 66 |
| document 修正后 | gemini-3.8-flash | LOW思考，2048预算；原两页按[2,1]上传，正确提取BETA、ALPHA并标注Page 2、Page 1，未截断 | 1536 |

共4次生成请求，合计4945 tokens；用量包含输入、思考及输出，各平台原始字段保留，不换算货币费用。一次批量中的3项实际独立请求，不是平台Batch折扣API。没有自动重提：初次PDF截断后调整参数，仅显式重测PDF一项。

首轮证据：`outputs/multimodal-selftest/20261020T165251Z/result.json`。PDF复测证据：`outputs/multimodal-selftest/20261020T165425Z/result.json`。产物为该结果中返回的绝对路径；这些运行输出不上传GitHub。

读图/PDF现在默认LOW思考（understanding_thinking_level可配置）；TTS独立输出预算、不发送思考配置；没有恢复thinkingBudget或自定义采样参数。不能从一次小样本推断所有OCR、长文、语言与音色的质量。

离线验证68项全部通过，覆盖既有48项、PDF截页顺序及原页号、超页/空页/重复/越界/加密/损坏、文本预览与模型截断区分、读图多图输入、TTS正文与style分离、完整WAV不重复加头、格式与帧长度检查、输入限额、参数混用拒绝、12个工具发现和新增单项接口调用。doctor确认配置有效、WinVaultKeyring后端且未读取密钥。

Codex注册仅追加submit_vision、submit_document、submit_speech到现有agent-mcp允许列表，新增提交仍继承prompt。保留现有auto_review、其他服务和四个管理工具的直接放行规则；原配置已在用户目录备份。当前会话工具目录可能仍为旧版，需要重启或重连。

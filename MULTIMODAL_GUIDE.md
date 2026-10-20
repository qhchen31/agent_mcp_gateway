# 多模态接口（0.3）

本版本共 12 个 MCP 工具：8 个任务接口 submit_text、query_knowledge、submit_image、submit_vision、submit_audio、submit_document、submit_speech、submit_batch，加上 list_capabilities、get_task、list_tasks、cancel_task。提交经过 harness 审批；新提交工具在 Codex 中保持 prompt，由既有自动审查器判断，查询／取消放行。当前会话需要重连或重启才能发现新增工具。

所有提交返回 task_id，随后用 get_task 等待结果。提交成功不等于完成。调用时 model 是配置别名；省略则使用各类型默认路由。不自动重提、切换模型或拆分成长文收费任务。批量支持全部七种 kind，整体校验后入队，执行结果按任务分别返回。

## 图片理解与绘图

`submit_vision(file_paths, prompt, context="", max_output_tokens=null, model=null)`：图片转文字、OCR、图表分析、多图比较。默认 gemini-vision → gemini-3.8-flash，仅请求 TEXT。每次 1–8 张（max_vision_images 可配置），格式 PNG/JPEG/WebP；沿用绝对路径白名单、单文件 12 MiB 和编码请求 20 MB 限制。多图总编码体积也受限制，不能简单按单文件限额累加。

```json
{"file_paths":["E:\\Project\\Script\\agent_mcp\\inputs\\chart.png"],"prompt":"提取表格并解释趋势","max_output_tokens":1024}
```

`submit_image(prompt, reference_paths=null, model=null)`：保留既有绘图／编辑功能，默认 gemini-image → gemini-3.1-flash-image，返回图片 artifact，不用于纯读图。不得将 gemini-image 别名传给 submit_vision：能力校验会拒绝。

## PDF

`submit_document(file_path, prompt=忠实提取指令, pages=null, max_output_tokens=null, model=null)`：默认 gemini-document → gemini-3.8-flash。默认忠实提取为 Markdown，尽量保留表格、原始页号，无法识别时标注；自定义 prompt 可请求摘要／问答。模型提取不保证字符、阅读顺序、页码引用完全准确，不能代替原 PDF 保存。

```json
{"file_path":"E:\\Project\\Script\\agent_mcp\\inputs\\paper.pdf","pages":[3,1],"max_output_tokens":4096}
```

pages 为不重复的 1-based 原页码数组，按数组顺序上传；省略表示全部页。默认每次最多选 20 页（max_pdf_pages），原文件仍不得超过 max_input_file_bytes（默认12 MiB）。本地 pypdf 实际截页，不上传未选页面的页面集合；PDF 引用对象可能随页面复制，不是可见像素级的数据隔离。拒绝加密、损坏、空页选择、重复／越界页码和超限文件。无需凭据之外的 PDF 密码，也不自动渲染／本地 OCR、自动分片或调用 Files API。

返回结果包含：

- artifacts：随机命名的 UTF-8 `.md` 绝对路径及大小，保存本次实际生成内容。
- text：前 document_preview_characters 字符的预览（默认2000）。
- preview_truncated：仅预览被裁短，与模型输出截断不同。
- truncated：上游是否 MAX_TOKENS；complete：上游是否正常 STOP，仅表示生成结束，不保证文档语义完整。
- pages、source_page_count：选中原页号及源文件页数。

文件保存不能消除上游截断；truncated=true 时文件也只是部分结果。请显式缩小选页范围或调整预算后再决定是否重提。默认 max_output_tokens=4096，同时覆盖回答与思考；复杂长文可能需要更多预算。读图／PDF 默认使用 LOW 思考级别，可通过 understanding_thinking_level=low/medium/high 配置。只发送受支持的 thinkingLevel，不发送 thinkingBudget、temperature、topP、topK。

## 音频理解与语音生成

`submit_audio(file_path, prompt, max_output_tokens=null, model=null)`：保留既有转录／理解接口，默认 gemini-audio → gemini-3.8-flash。输入允许目录内的音频，输出文本。

`submit_speech(text, voice=null, style=null, model=null)`：默认 gemini-speech → gemini-3.8-flash-tts。单人、非流式朗读，不做模型问答或自动改写；语气指令放独立 style，不能拼到 text。文本中的模型支持的发声标签仍可能影响朗读，不将其解释为普通可听文字保证。

```json
{"text":"你好，这是一次语音测试。","voice":"Kore","style":"清晰、自然、平静"}
```

默认 speech_voice=Kore、speech_style 为空；支持官方30种预置声音（如 Puck、Aoede），不支持自定义 voice_ / voicekey_、克隆、多说话人、流式、转码或长文拼接。正文默认最多2000字符（max_speech_characters），另以正文＋style 的8000 UTF-8字节保守门槛预检8192-token输入限制，可能比平台实际允许更严格。不是精确 tokenizer，不调用额外 countTokens。

speech_max_output_tokens 独立配置，默认16384，不复用普通文本4096上限。语音接口不接受 max_output_tokens 参数；批量 speech 项传入该字段也会拒绝。TTS 不发送 systemInstruction 或 thinkingConfig。直接保存上游完整 WAV，校验 MIME、RIFF、PCM帧长度和24kHz／单声道／16-bit格式；不再给已经有头的音频重复封装。上游截断、无音频或格式错误均失败，不把残缺音频标记成功。

成功结果的 artifacts 含 WAV 绝对路径、MIME、字节、时长、采样率和声道；text 通常为空。前端可展示本地音频播放器。文件命名不覆盖已有文件。

## 批量字段差异

```json
{"tasks":[{"kind":"vision","file_paths":["E:\\Project\\Script\\agent_mcp\\inputs\\chart.png"],"prompt":"描述图片"},{"kind":"document","file_path":"E:\\Project\\Script\\agent_mcp\\inputs\\paper.pdf","pages":[1,2]},{"kind":"speech","prompt":"Hello.","voice":"Kore","style":"warm"}]}
```

单独 submit_speech 的 text 在批量中写作 prompt；单独 query_knowledge 的 question 在批量中也写作 prompt。新增媒体任务沿用 media_timeout_seconds=600、Gemini并发2、全局并发4及进程内队列；超时不含排队。重启会丢失任务记录，已生成文件仍保留。所有输入会传给所选官方 API，网关不会自动执行模型或文档中的指令。

完整部署与审批参考 HARNESS_INTEGRATION.md。小样本验收脚本 run_multimodal_selftest.py 使用本地自制图片／PDF及一句朗读文本，实际 API 调用会计费；可附加 document/vision/speech 只测试一类。没有新增视频、输出 schema 约束或持久优先委派指令。

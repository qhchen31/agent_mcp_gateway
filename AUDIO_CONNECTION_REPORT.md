# 音频连接故障修复（0.3.1）

日期：2026-11-03（Asia/Shanghai）。

## 现象与证据

音频请求返回 network 或 internal_error。原任务的脱敏堆栈表明部分失败发生在 httpx/httpcore/anyio 的 TLS 读取阶段，底层 ssl.SSLError 未被现有 httpx.RequestError 分支捕获。单纯扩大生成超时不会修复此类错误。

本次只读诊断中，Gemini模型元数据读取返回200，证明该次认证与模型访问正常；不含凭据的小请求可返回404/403。合成大请求在HTTP/1.1下出现超时或RemoteProtocolError，HTTP/2下也曾超时；因此没有证据断言问题仅由密钥、单一TLS版本或HTTP协议导致，也不能定位具体路由器、代理或运营商。

## 修复

- 默认大于1MiB的音频采用官方Files API的resumable上传，随后用fileData引用发起一次生成，不再把整段Base64放入生成JSON。源文件12MiB上限不变。
- 上传按服务返回的x-goog-upload-chunk-granularity处理。本机实际返回8388608（8MiB），不能硬编码256KiB请求块；每个HTTP块内部再以64KiB数据流发送。首次协议验证的400发生在上传阶段，尚未生成，修正后再验证。
- 启用HTTP/2协商并保留HTTP/1.1兼容；可配置http2_enabled。它是传输选项，不保证解决任意网络故障。证书验证始终开启，不强制降级TLS。
- 原生或被包装的SSL错误分别返回tls_error/tls_certificate，隐藏底层敏感异常消息，不再笼统表现为internal_error。保留网络/超时不重发生成的约定，上传数据流也不自动重传。
- 上传URL必须为固定Google官方HTTPS域名，禁用重定向，检查文件名与引用一致性。成功、失败、取消后尝试清理远端文件；失败会告警，成功结果提供remote_file_deleted。若网络阻止删除，受平台保留政策约束（当前48小时）。

## 真实验收

离线回归91项全部通过，新增覆盖原生/包装SSL错误、证书错误脱敏、上传域名限制、256KiB和8MiB服务粒度、流式长度、失败与取消时清理以及不重复生成。另有512KiB合成文件上传/删除对照成功，不产生模型生成用量。

通过新的MCP stdio会话，使用已获用户许可上传的原问题音频的独立副本，9,412,939字节。文件不切分、不转码，原件与副本内容未改动。

任务ea36543206cd4328929453fc72848dc4成功，实际模型gemini-3.8-flash，audio_transport=files_api，运行139.563秒；返回简短语言识别与主题摘要，未截断。remote_file_deleted=true。输入14751 tokens、可见输出152、思考449、总计15352。仅此成功请求发起生成；前一阶段的400任务在上传阶段失败，没有生成结果。

本次仅验证连接与识别链路，不是原作业的完整转录或要求分析交付。课程内容和摘要只保存在本机outputs中，不随仓库发布。

原始证据：outputs/audio-connection-test/20261102T162020Z/result.json（本机文件；目录时间为UTC）。复现脚本run_audio_connection_selftest.py需要显式--file，执行会上传内容并产生模型费用，请仅对获授权音频运行。

官方依据：[Files API](https://ai.google.dev/gemini-api/docs/files)、[音频输入](https://ai.google.dev/gemini-api/docs/generate-content/audio)、[HTTPX HTTP/2](https://www.python-httpx.org/http2/)。

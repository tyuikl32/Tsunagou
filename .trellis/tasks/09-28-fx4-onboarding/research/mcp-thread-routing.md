# Codex 请求身份依据

核实日期：2026-09-28。

OpenAI 官方源码提交 [3a9df58 / PR 18093](https://github.com/openai/codex/commit/3a9df58d0611e51dc059d2e9175f4b338d8b99a1) 为模型发起的 MCP tools/call 和手动 app-server mcpServer/tool/call 均在请求 `_meta.threadId` 注入真实 thread ID；同名 metadata 值被宿主写入的值覆盖。

因此 bridge 应读 request.params._meta.threadId，以此选择当前私有 session/项目路由；不能把 tool arguments 中的字段视为身份，也不能把共享 MCP 进程的 profile 当成一个 Worker。环境 CODEX_THREAD_ID 只适用于确知单会话独占进程的回退。

当前 application/onboarding.py 已能在 Agent 的真实 shell 环境中通过应用管道只读核对原 thread，并写私有 request。它不创建身份/授权。当前票据 host_binding 已将 U 选定的原 thread 与 enrollment 绑定，enroll/rebind 后在 SQLite 提交外注册 FX3 provider，同 command 重放不重复改 binding revision。

仍需实现：CLI prepare/connect 串联、MCP 按请求隔离、原会话第一次 context 验证、双原会话真实验收。官方代码存在该 metadata 不等于当前安装版本的实测已经通过。

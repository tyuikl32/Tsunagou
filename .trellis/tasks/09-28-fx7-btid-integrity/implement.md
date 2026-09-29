# FX7 实施与验证

1. 在目标仓库读取 AGENTS、当前状态、Modules/Btid.cs、Backend/HttpBackend.cs、现有 tests/Http 与 wwwroot/package.json；通过隔离 checkout 工作。
2. 补可再分发的完整样例及 CRC 错、HMAC 错、头/表/扇区截断反例。新增 tests/Http/btid-integrity.ps1 调真实 HTTP，给请求合理的测试超时以捕获死循环；不以 mock parser 通过。
3. 修 Btid 读循环、完整读和校验 false；复用 HTTP 已有错误映射。
4. 检查 wwwroot 的错误处理，422 显示业务校验失败，服务不可达才显示网络故障。若现有行为已正确，仅增加实际验证，不为任务数量重写 UI。
5. 执行已有 HTTP 回归和新反例，记录 requestId/响应状态/耗时。合法大文件不应整体额外复制多份到内存。
6. 将实际样例和步骤交给 FX6；业务改动留在业务仓库，Tsunagou 仅保存任务与脱敏验收引用。

~~~powershell
# 以下在实际选定的 SegaImageManageTool checkout 执行
dotnet build
pwsh -File tests/Http/run.ps1
pwsh -File tests/Http/btid-integrity.ps1
node --test tests/WebUI/api.test.mjs
~~~

新的 btid-integrity.ps1 由本任务实现。2026-09-28 已核对当前 wwwroot/package.json 只有 private/type，没有 build script；此版本前端为直接提供的静态文件，不能使用旧 web/pnpm build 步骤。dotnet build 后启动真实服务作页面回归。无需编写旧文件迁移，也不因发现旧警告而扩大修复范围。

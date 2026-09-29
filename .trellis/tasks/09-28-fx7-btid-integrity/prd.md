# FX7 Sega BTID 完整性与截断处理

状态：completed；FX-R08，独立业务修复。实施目标 D:\ALL.NET\SegaImageManageTool 的隔离 checkout；不改 Tsunagou 协议。与 FX1–FX5 无代码依赖，最终 FX6 业务回归已使用隔离 checkout 验收。

## 证据与结果

Modules/Btid.cs:33 未检查完整头读取；:44–45 忽略 CRC/HMAC 返回值；:193–216 循环读到零没有退出，且 CRC 使用整个缓冲区而非实际长度。Backend/HttpBackend.cs 已将 InvalidDataException/EndOfStreamException 等映射为 422 invalid_image，沿用该契约。

| ID | 验收 |
| --- | --- |
| B1 | 合法完整 BTID 仍返回正确元数据，实际 CRC/HMAC 检查成立 |
| B2 | CRC 或 HMAC 不匹配时明确无效，不显示“校验通过” |
| B3 | 头、CRC 表、签名或扇区截断快速结束，不循环挂起 |
| B4 | 无效尺寸/偏移/溢出在必要解析边界拒绝，正常大文件按块处理 |
| B5 | 真实 HTTP 返回既有 422 invalid_image；页面区别业务无效和 API 不可达 |
| B6 | 构建及已有测试通过，保留用户原有改动，不扩展为解析器/前端重构 |

不新增通用防御框架，不更换算法或添加未证实的格式规则。实现步骤和样例边界分别见 [implement.md](implement.md)、[design.md](design.md)。

验证：B1–B6 已完成；构建、真实 HTTP 样例、页面上传正反结果和同源端口选择记录见 [实现进度](implementation-progress.md) 与 [验证摘要](validation.json)。

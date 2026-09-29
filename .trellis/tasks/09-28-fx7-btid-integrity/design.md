# FX7 业务设计

修复 Btid.Create 的完整读取和校验结果传播。固定长度头、CRC 表及签名必须读完整，截断抛 EndOfStreamException；CRC/HMAC false 抛 InvalidDataException。不在 HTTP handler 中吞掉后仍返回成功模型。

扇区循环 len==0 立即失败，只计算实际读到的字节；避免 readCount 为零时继续。尺寸转换与偏移乘法使用 checked，所声明区间不得超出实际文件长度；只检查参与实际读取的字段，不发明任意最大尺寸或拒绝真实格式支持的尾部数据。

沿现有 .NET 类型、流读取和加密算法。需要完整读时用运行时现有 ReadExactly 或等价小辅助函数；不新增依赖。既有 HTTP 422 invalid_image 和 requestId 保持，普通网络不可达才显示 API unreachable。

使用已有合成样例生成基础，确认它确实满足 CRC/HMAC；若旧样例仅凭忽略校验通过，修正样例生成，不能松绑解析器迎合它。合法样例经单点字节翻转、截短和非法尺寸生成反例。样例不包含用户不可再分发文件。

目标项目当前前端在 wwwroot，HTTP 入口在 Backend/HttpBackend.cs；历史报告中的 web 目录名不能作为当前路径。修改前再次读取目标仓库约定和状态。

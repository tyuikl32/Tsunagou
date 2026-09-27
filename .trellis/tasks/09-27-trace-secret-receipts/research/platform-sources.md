# PT2 平台保护依据

查询日期：2026-09-27。

- [Microsoft CryptProtectData](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata)：使用当前用户凭据保护数据；本项目不启用 LOCAL_MACHINE，设置 UI_FORBIDDEN，释放返回 buffer。
- [Microsoft DPAPI 示例](https://learn.microsoft.com/en-us/windows/win32/seccrypto/example-c-program-using-cryptprotectdata)：验证加解密及 LocalFree 的调用约定。DPAPI 是本机用户保护，不是抵抗当前用户 Full Access 的边界。
- [SQLite Backup API](https://www.sqlite.org/backup.html)：迁移演练使用一致备份，不能分别复制活跃 DB/WAL 作为同一快照。
- [SQLite VACUUM](https://www.sqlite.org/lang_vacuum.html) 与 [WAL](https://www.sqlite.org/wal.html)：清理需考虑数据库和 WAL 可见残留；不承诺擦除外部备份或存储介质的取证副本。

具体 TTL、精确命令绑定、ACK 和恢复窗口是 Tsunagou 的实现决策，不是上述平台接口自动提供的能力。

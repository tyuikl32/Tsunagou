# PT6 实施步骤

1. 盘点现有 reconnect/wake/coordination 事件，给其归类而不删除历史。
2. 为常驻 bridge no-op、epoch 变化、callback 重试、host unknown、Agent pull/turn 建 fixture。
3. 让 history CLI 显示证据类型和关联 ID，验证 callback 不冒充 turn。
4. 用一个验收后缺陷创建新 task/result，验证关联可查且旧记录不被追补。

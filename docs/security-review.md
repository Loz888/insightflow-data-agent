# 最终安全与可靠性审查（Day9 功能冻结）
## 实际修复
1. 取消会传递到等待锁的服务、Graph 检查点和借用中的 PostgreSQL 连接。
   Cancellation.bind 的活跃保护避免旧 token 取消已回池后被另一请求借用的连接。
   断连由 async API 检测；取消后不写入会话事实。
2. Session 获取/保存、Schema 检索和数据库连接异常返回固定脱敏分类；
   不把内部异常、密码或不完整结果交给 API。
3. 原默认权限会授权未来表，现用 004_reader_restriction.sql 撤销默认 SELECT，
   精确授权五表，测试真实新增 private_notes 不可读并清理测试对象。
4. search_path 明确 pg_catalog 优先；普通白名单函数进一步转换为 pg_catalog 调用。
   单靠搜索路径不能阻止精确类型重载优先，因此还用真实 ROUND/SUM 同名重载测试，
   包括嵌套调用按子表达式优先绑定。Coalesce/Nullif/Cast 是 PostgreSQL 特殊表达式。
5. 保留默认拒绝 AST、Reader/只读事务、计划/超时/输出预算；互不替代。

## 矩阵与故障
原 25 攻击矩阵加 ALTER/TRUNCATE、嵌套子查询/CTE、引号标识符、Schema 限定、
危险函数与畸形 SQL。对所有模型 SQL 使用同一执行器。
Reader 真实 SELECT 正向及 INSERT/UPDATE/DELETE/DDL/未授权表负向均验证。
语句/锁超时、超大结果、复杂计划在现有真实 PostgreSQL 测试执行。

故障覆盖：真实连接端口失败、语句超时、LLM Timeout/429/503/坏响应、
无效 SQL、Schema 检索失败、Context 预算、Session 状态故障。
模型 API 错误本地 Mock HTTP 验证；模型调用和 SQL 修正分别有硬预算。
恶意问题和检索描述可影响模型文本，但不能提高工具权限；
测试故意让 Provider 生成系统表 SQL，仍被 AST/权限阻断。

## 并发与取消
同一服务显式全局串行，包含同 Session 原子历史更新，不声称高吞吐。
真实持有表锁时取消查询，连接释放后正常复用；排队取消不建立 Session；
同 Session 两并发请求不丢历史；ASGI disconnect 会发出取消信号。
SQL 驱动取消是尽力而为，仍由查询/锁超时提供独立上限。
正在进行的同步模型 HTTP 不能强制立即中断，最多受单次配置超时约束；
取消检查会阻止其后再次发起 HTTP 尝试和保存答案。这不是任意代码抢占。

## 边界
仅可信合成数据，本地回环、无认证。Session 键不是租户授权。
AST 不代表已防御所有 PostgreSQL/解析器漏洞、侧信道或不可信数据库管理员。
计划成本为估算，不是 OS 内存/CPU 沙箱。未来 Schema/函数变化需再次审查。
没有长期记忆、多 Agent、向量库、复杂前端或分布式平台。

## 冻结
Day9 后停止新增业务功能。Day10 只在现有边界加观测和测量，
Day11 文档/重现，Day12 验收/CI。仅真实 Bug 可继续修复核心逻辑。
实际测试节点见 reports/reliability.json；失败/跳过不被忽略。

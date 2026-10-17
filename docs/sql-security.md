# SQL 安全边界
仅本地可信合成数据演示，不宣称生产数据安全或多租户隔离。

1. SQLGlot PostgreSQL AST：一条 SELECT，显式节点/函数/类型白名单，
   未知语法默认拒绝。禁止写入 CTE、SELECT INTO、多语句、系统/未授权表、
   动态函数、跨库、锁行和无条件 JOIN。字段存在性与歧义检查基于真实元数据。
2. 资源预算：SQL 长度 8000、常量 1024、AST 450 节点/深度 30、最多 6 JOIN；
   EXPLAIN 估算成本/行数不超过 100000。估算不是硬资源隔离。
3. 独立数据库权限：insightflow_reader 为非 Owner、非超级用户，仅 business
   Schema USAGE 与五表 SELECT，无建库/建角色/写表权限。开发者 owner 仅初始化使用。
4. 每个池连接强制 read_only；每次查询事务设置 statement_timeout=1500ms、
   lock_timeout=200ms、idle_in_transaction_session_timeout=3000ms，
   固定 search_path 与 UTC。池最多 2（配置硬上限 4）连接。
5. 服务端游标最多获取 max_rows+1（默认 100+1）；超过行数或 32768 字节返回
   明确错误。数据体积按 UTF-8 JSON 测量，不静默冒充完整结果。
6. 只有语法/已知字段错误可进入最多两次 SQL 修正；权限/危险 SQL/超时/
   不足业务信息/输出超限不自动重试。DB 错误不返回连接信息。
7. PostgreSQL 默认允许某些公开目录函数和元数据。AST 默认拒绝系统访问，
   DB 权限作为独立防线；没有声称撤销所有系统目录权限。
8. 无身份认证，默认绑定 127.0.0.1；Session ID 是本地会话键，不是授权凭证。
   不应向互联网或不可信用户公开服务。

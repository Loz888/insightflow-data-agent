# InsightFlow 源码学习指南
本文按当前源码说明，针对本项目，不把 Mock 当成通用 LLM。
先读一条成功请求，再读失败/取消和独立评测。所有命令都在仓库根目录执行。

## Chapter 1：项目启动过程
1. scripts/serve.sh 读取本地环境，移除管理员 DSN，启动 uvicorn，默认 127.0.0.1:8000。
2. uvicorn 导入 insightflow.api.app:app。模块末尾 app=create_app() 构建 FastAPI 对象，
   Settings 从进程环境读取配置，不在 Python 模块中自动读秘密文件。
3. create_app 注册 routes.router、/health、/schema，定义异步 lifespan。
4. lifespan 在有 Reader DSN 时建立 AgentService：
   选择 Mock 或显式授权的 DeepSeek，SchemaCatalog 读取真实元数据，
   ReadonlyExecutor 建受限连接池，Tools/Nodes/build_graph 编译 StateGraph，
   SessionStore 和串行锁属于该服务实例。
5. 退出 lifespan 时 executor.close 释放连接池。无 DSN 只有存活检查，
   /schema 空目录、/chat 503，不能把存活当数据库健康。

源码：[app.create_app](../src/insightflow/api/app.py)、
[Settings](../src/insightflow/config.py)、[AgentService.__init__](../src/insightflow/agent/service.py)。

## Chapter 2：一次请求完整调用链
以 POST /chat {session_id:demo, question:2026年9月退款率是多少？} 为例。

| 步骤 / 文件函数 | 输入 | 输出 / State 更新 | 可能失败 |
| --- | --- | --- | --- |
| api/schemas.ChatRequest | JSON | 有界问题、ASCII Session 键 | 空/超长/未知字段，422 |
| api/routes.chat | 请求模型 | Cancellation；to_thread 调 service.run | 无数据库 503，断连取消 |
| agent/service.AgentService.run | 问题/Session | 唯一 request_id；锁；旧有效约束与历史 | 排队取消、Session 容量/故障 |
| nodes.understand | 问题+旧约束 | plan：metric/month/region/group/currency | 无指标或模糊指代请求澄清 |
| nodes.select | plan+问题 | selected_tables/retrieved_context | Schema/预算不足 |
| nodes.generate | 计划/定义/Schema/历史/反馈 | ContextManager.build；generated_sql | 上下文超限、模型故障 |
| nodes.validate | 原 SQL | validation_result，表清单 | 语法、危险语法、字段歧义 |
| nodes.execute | 原 SQL | Tools → executor → query_result | 权限、超时、结果限制、取消 |
| nodes.answer | 真实结果或 error | final_answer：SQL/证据/限制 | 无结果就说证据不足 |
| service.run / routes.chat | 完整结果 | 有效会话原子保存、ChatResponse | 取消不存；保存失败不返回业务答案 |

[完整图](../src/insightflow/agent/graph.py)；
[节点](../src/insightflow/agent/nodes.py)；
[工具](../src/insightflow/agent/tools.py)。

在 ExecuteSQL 内继续追踪：
SQLInput → SQLValidator.validate（再次强制校验）→ 借池连接 →
只读事务和 SET LOCAL 预算 → EXPLAIN 估算 → 服务端游标取最多 max_rows+1 →
Decimal 转字符串、UTF-8 字节检查 → query_result。
实际送给 PostgreSQL 的是安全规范化 SQL，物理表限定 business，
普通白名单函数限定 pg_catalog；响应展示生成 SQL 与该结果证据。

## Chapter 3：LangGraph
[AgentState](../src/insightflow/agent/state.py) 是 TypedDict，
StateGraph 为每个字段建立通道，节点返回更新字典，不更改全局业务状态。
最重要字段是 question/session_id/conversation_context/plan、
selected_tables/retrieved_context/generated_sql/validation_result/query_result/
final_answer/error/retry_count；另有 history、context_budget、timings、node_events。

build_graph 用真实 StateGraph.add_node/add_edge/add_conditional_edges/compile。
入口 START 到 UnderstandQuestion；理解/Schema 失败直接 GenerateAnswer。
生成/校验/执行失败到 ClassifyFailure。
routing.after_node 看 error，after_classify 决定 retry 或 answer。
nodes.classify 只给可恢复 SQL 语法/字段错误至多两次修正；
模型传输重试由 Provider 自身有限处理，权限/安全/超时不盲目重试。
LangGraph recursion_limit=30 是额外防线，不代替业务重试预算。

Day1 的 build_basic_graph 只用于原始两节点测试，业务使用 build_graph；
不是另一套自制 Agent Framework。

## Chapter 4：SQL Security
[validator.SQLValidator.validate](../src/insightflow/database/validator.py)：
PostgreSQL Dialect 解析 → 单 SELECT → AST/函数/类型白名单 →
复杂度/连接限制 → 作用域内物理表和 Schema → 真实字段/歧义检查 →
普通函数按子表达式优先限定 pg_catalog。
不支持的语法默认拒绝。Coalesce/Nullif/Cast 是特殊表达式。

[connection.checked_connection](../src/insightflow/database/connection.py)
核对专用数据库名、实际用户、非超级权限及非 Owner Reader；
固定 pg_catalog 优先元数据解析。
[executor.ReadonlyExecutor.execute](../src/insightflow/database/executor.py)
即使调用者已校验，也再次校验。Reader 仅五表 SELECT，
READ ONLY、statement/lock/idle 超时、EXPLAIN 预算、游标/字节预算并存。
SQLGlot 不拥有授权能力；Prompt 不拥有授权能力；只读事务也不能代替危险函数限制。
004_reader_restriction.sql 防止未来表被默认授权；普通函数限定命名空间避免重载劫持。
安全边界和真实负向测试见 security-review.md，不声称覆盖所有攻击或不可信管理员。

## Chapter 5：Retrieval
[SchemaCatalog](../src/insightflow/retrieval/schema_catalog.py)
组合真实 read_catalog 的表/列/类型/FK 与受信任描述、指标和示例。
[SchemaRetriever.retrieve](../src/insightflow/retrieval/retriever.py)
用指标必要表映射与关键词/字段得分排序，再沿 FK 补全必要连接。
只从授权表中选择；最多 MaxSchemaItems，缺预算会拒绝，不能丢 JOIN。
结果包含 retrieved_tables/columns/metrics/retrieval_scores/schemas，
再由 nodes.select 注入 State，ContextManager 才将其送入生成 Prompt。

当前是受控指标映射主导的检索，不是向量搜索。
Recall@5 用独立 ReferenceSQL 物理表标注，不能用生成 SQL 自己作为答案。
Mock 生成器不消费 Schema 文本，四模式实验不能证明真实 LLM 的检索收益。

## Chapter 6：Context Management
[SessionStore.get/record](../src/insightflow/context/session.py)
在本进程保留约束与有限成功历史；失败/取消不成为可信事实。
没有 Checkpointer 跨进程持久化，重启丢失。不同 Session 不共享问题上下文。
服务全局串行锁定义同 Session 更新次序，也限制总体并发吞吐。

[ContextManager.build](../src/insightflow/context/manager.py)
构建系统要求、权威指标/约束、相关 Schema、当前问题、历史、错误反馈。
先删旧工具输出，再删旧非权威历史；指标/月份/地区/币种不能删。
ceil(UTF-8 字节/3) 是估算，不是模型 tokenizer。
例如“那华东地区呢”继承月份和指标；新条件覆盖旧值；
“那第二个呢”无法可靠解释时澄清。
自然语言历史不是业务 Ground Truth。

[cancellation.Cancellation](../src/insightflow/agent/cancellation.py)
把断连/取消传播到锁等待、Graph 检查点与借用的连接。
bind 回调活跃保护避免旧 token 取消被别的请求复用的连接。
正在进行的同步模型 HTTP 只能受单次超时约束，取消后不会继续新尝试。

## Chapter 7：Evaluation
[build_ground_truth.py](../scripts/build_ground_truth.py)
只执行独立维护的 ReferenceSQL。正常 accept 不重建 Ground Truth。
[runner.run_evaluation](../src/insightflow/evaluation/runner.py)
每案新 Session，执行前序问答与当前问题，记录实际 SQL、状态、用量与耗时。
独立重查生成 SQL 佐证回答 evidence，同时用原参考结果判正确。

[scorer.equivalent/grounded/summarize](../src/insightflow/evaluation/scorer.py)：
结果按列、顺序或多重集合比较，Decimal 容差、NULL 与 0 分离。
Exact Match 只是 SQL 文本指标，不是否决等价 SQL 的依据。
SQL 能执行≠业务结果正确；回答忠于自己查询≠查询回答了用户问题。
测试里的错误产品数 SQL 可以执行且 grounded，却应为 RESULT_MISMATCH。
这正是防止 False Success Claim 的独立证据边界。
P50/P95 用 nearest rank；性能额外 P99，小样本不能视为生产尾延迟保证。

ablation.experiment 共用安全后端，切换历史和 Schema 来源，保存实际失败。
performance.run_profile 用真实线程请求和 perf_counter；
plans 仅为受控诊断执行 ANALYZE/BUFFERS，API 不开放任意 EXPLAIN。
real_model.main 没有用户显式付费门控就生成 NOT_RUN，不调用真实模型。

## Chapter 8：重要工程取舍
- LangGraph 将步骤、状态和失败边显式化，便于测试有限循环；不是自动正确性保证。
- 不将全部 Schema 填 Prompt，避免不相关内容；当前 Mock 不能证明 LLM RAG 收益。
- SQL 安全由代码、数据库权限与资源预算执行，LLM 无权自行授权。
- 结果正确率比字符串相同更接近业务要求，但仍依赖可信参考口径与数据。
- Mock 用来验证工程链路和上下文规则，不替代未知问题的真实 LLM 能力评测。
- PostgreSQL 提供真实关系、NUMERIC、约束、权限和查询计划，不引入额外数据平台。
- 全局串行保护简单会话一致性，付出并发排队成本；当前原型不冒称可横向扩展。
- 无认证，只本地演示；长期记忆、向量库、多租户与复杂前端均为 Planned。

## 推荐十步阅读顺序
1. api/schemas.ChatRequest 与 api/routes.chat：请求如何进来。
2. agent/state.AgentState：字段怎样流转。
3. agent/graph.build_graph 与 nodes.Nodes：正常/失败路径。
4. retrieval/schema_catalog.SchemaCatalog、retriever.SchemaRetriever.retrieve：Schema 选择。
5. context/session.SessionStore、manager.ContextManager.build：历史与权威约束。
6. database/validator.SQLValidator.validate：默认拒绝。
7. database/connection.checked_connection、executor.ReadonlyExecutor.execute：真实只读执行。
8. evaluation/runner.run_evaluation、scorer.equivalent/grounded：独立评分。
9. observability.observed_node、evaluation/performance.run_profile：真实延迟与排队。
10. tests/test_workflow.py、test_reliability.py、scripts/demo_mock.sh：成功、失败、取消整链路。

从 demo 的一个问题打断点，不要先从所有测试或大段 Prompt 同时开始。

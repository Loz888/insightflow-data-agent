# 从一个请求读懂 V2

先运行 scripts/serve.sh，打开回环页面，用 scripts/local_token.py 在本机查看Bearer。
问题选“2026年9月排除华东地区的订单数是多少？”，再问“那华南地区呢？”。

1. `src/insightflow/v2/api.py:create_app/submit/chat/principal`：输入ChatInput，认证派生主体；幂等键不是访问凭证。
2. `contracts.py:QueryPlan/Window/Decision/Action/Answer`：时间、否定、比较、工具与证据都结构化；extra字段拒绝。
3. `service.py:Runtime.submit` → `store.py:Store.enqueue/claim`：先持久排队，再按Session序号领取，不跨网络占事务。
4. `graph.py:build_graph/plan` → `provider.py:AsyncDeepSeek.request`：DeepSeek真正理解并产出计划；无Mock回退。
5. `semantics.py:guard_question`：明确日期/排除/指标不能悄悄变；缺同比数据澄清。
6. `retrieval.py:Retriever.refresh/select`：授权真实元数据、FK、Schema版本；不可信描述仅作为数据。
7. `graph.py:action/tool` → `tools.py:Registry.execute`：模型产生JSON action，服务端检查参数、前置工具、ID与预算。
8. `semantics.py:SemanticSQLGuard.validate` + 原 `database/validator.py:SQLValidator.validate`：业务含义与AST安全分别检查。
9. 原 `database/executor.py:ReadonlyExecutor.execute`：Reader/只读/计划/超时/行字节预算；线程取消回调绑定借用连接寿命。
10. `graph.py:answer/verify_answer` → `Store.complete`：模型解释引用实际单元格；失败可退确定性证据，成功事实才CAS提交。
11. `api.py:events`：SSE以run关联；失败不会输出成功答案；断连会取消。
12. `evaluation.py:reference_result/constraint_correct/run_cases`：参考SQL与Agent独立，结果、语义、证据、E2E分开。

失败链从 tests/test_v2_provider.py（协议）→ test_v2_semantics.py（含义）→ test_v2_runtime.py（租约/取消/所有权）→
test_v2_dataset.py（87案例+双快照）依次阅读。真实失败不只看异常：看对应runs.jsonl里的decisions/tool_records/events。

需要理解的边界：QueryPlan不是通用中文证明器；SQL契约不是任意等价证明；正常重放幂等不等于付费Exactly-once；
按principal隔离会话不等于按租户隔离业务行；Mock全绿不等于真实模型全绿。

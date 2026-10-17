# 中文项目描述（依据实际证据）

InsightFlow 是面向合成业务数据库的受约束数据分析 Agent。项目使用 FastAPI、LangGraph、PostgreSQL 和 SQLGlot，
由真实 DeepSeek V4.1 Flash Max 完成问题理解、结构化计划、工具参数/SQL生成和带证据引用的解释。
系统在模型之外实施 SQL 安全与业务语义校验，并用 PostgreSQL 保存会话、运行、阶段事件、幂等和共享费用账本。
同会话以租约和版本维持顺序，不同会话可并发，支持取消、deadline、过载、失联中断、SSE、OpenTelemetry与Prometheus。

评测保留原30题，新增87条离线案例与两份独立Seed快照；真实Max第二轮30场景27成功，实际失败和定向复验完整保留。
工程测试与全新环境结果见总验收，不以Mock成绩代表模型能力。
项目还测量了控制面持久化带来的性能开销，没有虚构上线、业务收益、用户规模、生产级保证或个人贡献。

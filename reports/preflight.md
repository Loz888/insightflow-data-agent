# 最终阶段 Preflight · 实际执行 2026-10-17
基线提交：5e41ee42a5cfd495f6e4b1a4d6ed47f161c1a7b6。源码与原测试在基线验收前未修改。
Private GitHub 仓库已建立，保留此前六个阶段提交。

## 当前功能 / 模块
api → agent/graph,nodes,service,tools → retrieval/context → llm → database；
evaluation 使用独立 ReferenceSQL 结果，Mock 不读取 QuestionID 或参考答案。
真实 StateGraph 包含六个正常节点及 ClassifyFailure 条件分支，最多两次 SQL 修正。
执行图见 docs/architecture.md，节点源码名一致。

## 实际测试
重新执行 scripts/accept.sh：
80 PASS / 0 FAIL / 0 SKIP / 0 ERROR，33 单元、47 集成。
格式/静态/compileall/pip check/真实 PostgreSQL 权限/Mock Demo 通过。
30 条 Mock 场景执行/结果/证据均通过；不把 SQL Exact Match 当成正确性的必要条件。
此前干净虚拟环境安装和回环 HTTP 也已验证，原始证据在仓库外持久目录。

## 数据安全审计
SQLGlot PostgreSQL 默认拒绝 AST、Schema/Table 白名单与字段校验实际执行；
所有生成 SQL 经过同一 ReadonlyExecutor，再次强制 AST 校验。
独立 reader 身份和只读事务，连接池/超时/计划/行数/字节限制均有真实测试。
管理员连接只用于初始化和测试 Fixture，不进入 AgentService。
没有生产安全、多租户或所有 PostgreSQL 攻击的保证。

## Retrieval / Context 审计
真实元数据、排序、选择、JOIN 闭合和 Prompt 注入已存在，不是整库 Prompt。
但选择主要依赖受控指标映射；Mock SQL 规则不消费 Schema 文本，
现有通过率不能证明真实 LLM 的 RAG 收益。需 Day8 消融明确说明。
Session 有界且隔离，仅单进程内存；错误结果不写入成功历史。
没有长期记忆，关键约束与历史分开，无 Ground Truth 注入 Prompt。

## Evaluation 风险
原始 30 个独立参考 SQL 已执行；结果不是 Agent 生成 SQL 的复制。
已有错误但可执行 SQL 的负向评分对照。
原 questions.relevant_tables 个别为宽泛业务关联集合（如退款订单率列出明细），
Recall 实验需要独立审核参考 SQL 的实际物理表标注，不修改原 SQL/答案。
现有延迟是真实小样本，不能视为稳定生产性能。

## 尚需完成 / 安全风险
- DeepSeek 缺细粒度错误、finish_reason 检查、总 Token 与受限退避。
- 需要新增严格 INSIGHTFLOW_ENABLE_PAID_EVAL=1 门控，绝不自动打开真实付费。
- 没有四模式消融、独立 Recall@K 和上下文错误专项。
- 当前全局锁定义了串行行为，但尚未实现/验证请求取消传递。
- 故障注入覆盖和结构化分阶段耗时不足。
- 尚无性能并发实验、ANALYZE/BUFFERS 计划分析、源码学习指南和远程 CI。

## 后续修改位置
Day7 llm/deepseek、errors、evaluation/real_model、SDK 本地测试。
Day8 config/nodes/service、ablation、retrieval/context 专项测试。
Day9 executor/API/service 取消及错误边界、注入/权限/故障测试，之后功能冻结。
Day10 在现有节点/工具加观测，performance 脚本与 SQL 计划。
Day11 README、Mermaid、LEARNING_GUIDE、干净环境重现，不重写核心架构。
Day12 final 评测与报告、隐私审计、GitHub Actions，正常 Push，保持 Private。

## Unverified Claims
真实 DeepSeek NOT_RUN；未开展付费、公开仓库或求职相关任务。

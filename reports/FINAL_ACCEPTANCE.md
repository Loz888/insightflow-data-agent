# InsightFlow 最终验收

实际集中执行日期：2026-10-17。Day1–6 是任务书计划阶段，不虚构未来执行日期。
六阶段均先测试和保存报告再提交；原 Go 项目代码与数据库不作修改。

## 工程信息

- 路径：~/projects/insightflow-data-agent
- Python：3.12.3
- 独立 Git 历史，使用 GitHub 隐私邮箱；目标私有仓库 Loz888/insightflow-data-agent。
- 最终 Commit SHA 随交付消息给出；报告所在提交可用 git rev-parse HEAD 查询，避免报告内容与自身提交哈希循环依赖。
- 简历 V0 在仓库外受限私人目录，不追踪。

| Core dependency | Verified version |
| --- | --- |
| langgraph | 1.2.16 |
| fastapi | 0.143.3 |
| psycopg | 3.3.6 |
| psycopg-pool | 3.3.3 |
| sqlglot | 30.23.0 |
| pydantic | 2.14.1 |
| pytest | 9.1.1 |
| httpx | 0.28.1 |
| openai | 3.33.0 |
| ruff | 0.17.1 |

## 架构与数据

真实 LangGraph：UnderstandQuestion → SelectSchema → GenerateSQL → ValidateSQL → ExecuteSQL → GenerateAnswer；
生成/校验/执行错误进入 ClassifyFailure，可恢复错误至多两次修正，其他直接失败。
完整 State、工具职责与检索排序/选择/注入见 docs/architecture.md 和 src/insightflow/agent/state.py。
ContextManager 保留指标、月份、地区、币种；Session 隔离，仅进程内短期记忆，重启不恢复。
SQL 默认拒绝 AST + 独立 reader 权限 + 只读事务 + 超时/计划/结果预算，不宣称生产安全。

两个独立库 insightflow_dev/test，每库 customers=100、products=30、orders=500、order_items=1001、refunds=165。
五表具有主外键、状态/正数 CHECK 与连接/时间/地区索引。金额 NUMERIC/Decimal。
reader 非超级用户/非 Owner，无写表/建库/建角色权限；owner 只用于明确的迁移与 Seeder。
GMV、Paid Revenue、退款金额、订单数、退款订单率、退款金额率和客单价定义见 docs/metrics.md；
按订单日期分批，先分别聚合明细和退款，避免多对多重复计数。

## 工程测试

**80 PASS / 0 FAIL / 0 SKIP / 0 ERROR**；单元 33、集成 47。
计数为实际 pytest 参数化测试条目，30 个业务评测问题另计。

| Test file | Passed items |
| --- | ---: |
| tests/test_api.py | 1 |
| tests/test_chat_api.py | 9 |
| tests/test_context.py | 11 |
| tests/test_database.py | 3 |
| tests/test_deepseek.py | 5 |
| tests/test_evaluation.py | 4 |
| tests/test_graph.py | 1 |
| tests/test_metrics.py | 1 |
| tests/test_retrieval.py | 3 |
| tests/test_sql_security.py | 38 |
| tests/test_workflow.py | 4 |

安全测试 25 类攻击拒绝，业务数据前后摘要一致；另验证真实权限、两个超时、输出与计划预算。
API 测试包含请求限制、响应证据形状、真实数据查询、多轮和并发 Session 隔离。
真实回环 HTTP /health、/schema、/chat 均成功。
Ruff、格式检查、compileall、pip check、Mock Demo、专用数据库/权限检查通过。
缺测试库直接失败，accept 不接受 SKIP。

## Agent Evaluation（Mock）

- 30 案例：10 基础、10 JOIN/聚合、5 复杂指标、5 多轮。
- SQL Execution：30/30；Result Correctness：30/30；Groundedness：30/30；E2E：30/30。
- SQL Exact Match：8/30（26.67%）；其余不同 SQL 经独立结果核对仍正确。
- P50：13.656 ms；P95：26.916 ms；平均重试：0。
- Mock 策略调用 70（含五个前序轮次）；外部模型未调用。
- 真实 DeepSeek：NOT RUN；Token 用量未知/null，不冒充零 Token。
- 错误分布：本次 30 场景无失败；failures.json 保留实际空列表。
- 额外负向对照：可执行但错误的 SQL 被评分为 RESULT_MISMATCH，并保留失败样本。
- 延迟只描述本机固定合成小样本，不代表生产性能或真实模型能力。

原始逐案证据、机器汇总、失败列表及 Markdown 见 reports/evaluation/。
总验收机器结果见 reports/acceptance.json。原始日志/虚拟环境/凭据在 Git 外。
Ground Truth 由独立参考 SQL 生成；验收不重写参考答案。

## 重现与退出码

README Quick Start 已在干净代码副本、新虚拟环境和锁依赖安装中验证。
数据库初始化明确复用本项目两个合成库，不接管已有其他数据库。
scripts/accept.sh：依赖 → 专用数据库/权限 → 静态/编译 → 全量 pytest → Demo → 30 案例。
退出 0 全通过；1 场景能力不满足但保留完整报告；2 工程故障。
服务 scripts/serve.sh 绑定 127.0.0.1；无认证不适合公开部署。
真实模式只在显式启用、Key/保守价格/调用与费用预算齐备时跑单问题演示。

## Known Issues / Unverified Claims

固定受控中文指标；不支持任意 Schema、季度/日级区间、其他年份/币种或通用 BI。
短期会话仅本进程；没有持久记忆、多租户授权、生产安全或分布式调度。
Context Token 为 UTF-8 估算，不是模型 tokenizer 计量。
DeepSeek 真实网络与计费未验证；SDK 错误/JSON/预算仅用本地 HTTP Mock 测试。
没有发布公开仓库、选择 License 或配置远程 CI。
详细能力范围、后续 Roadmap 见 README。

## 目录树（不含私有配置/缓存）

```text
.env.example
.gitignore
README.md
docs/architecture.md
docs/context-management.md
docs/evaluation.md
docs/metrics.md
docs/sql-security.md
evaldata/expected_results.json
evaldata/questions.json
migrations/001_business_schema.sql
migrations/002_roles.sql
migrations/003_indexes.sql
pyproject.toml
reports/day1.md
reports/day2.md
reports/day3.md
reports/day4.md
reports/day5.md
requirements.lock
scripts/accept.py
scripts/accept.sh
scripts/admin_bootstrap.py
scripts/build_ground_truth.py
scripts/check_database.py
scripts/demo_deepseek.sh
scripts/demo_mock.py
scripts/demo_mock.sh
scripts/init_db.sh
scripts/lib_env.sh
scripts/seed_data.py
scripts/serve.sh
src/insightflow/__init__.py
src/insightflow/agent/__init__.py
src/insightflow/agent/graph.py
src/insightflow/agent/nodes.py
src/insightflow/agent/routing.py
src/insightflow/agent/service.py
src/insightflow/agent/state.py
src/insightflow/agent/tools.py
src/insightflow/api/__init__.py
src/insightflow/api/app.py
src/insightflow/api/routes.py
src/insightflow/api/schemas.py
src/insightflow/config.py
src/insightflow/context/__init__.py
src/insightflow/context/manager.py
src/insightflow/context/session.py
src/insightflow/database/__init__.py
src/insightflow/database/connection.py
src/insightflow/database/errors.py
src/insightflow/database/executor.py
src/insightflow/database/metadata.py
src/insightflow/database/validator.py
src/insightflow/evaluation/__init__.py
src/insightflow/evaluation/report.py
src/insightflow/evaluation/runner.py
src/insightflow/evaluation/scorer.py
src/insightflow/llm/__init__.py
src/insightflow/llm/base.py
src/insightflow/llm/deepseek.py
src/insightflow/llm/mock.py
src/insightflow/retrieval/__init__.py
src/insightflow/retrieval/glossary.py
src/insightflow/retrieval/retriever.py
src/insightflow/retrieval/schema_catalog.py
tests/conftest.py
tests/test_api.py
tests/test_chat_api.py
tests/test_context.py
tests/test_database.py
tests/test_deepseek.py
tests/test_evaluation.py
tests/test_graph.py
tests/test_metrics.py
tests/test_retrieval.py
tests/test_sql_security.py
tests/test_workflow.py
reports/day6.md
reports/FINAL_ACCEPTANCE.md
reports/acceptance.json
reports/evaluation/{runs.jsonl,summary.json,failures.json,report.md}
```

# Day 6 验收 · 2026-10-17 执行（计划阶段 10-25）
## Completed Tasks
完整 /chat 输入/输出校验、真实 LangGraph/只读 SQL/检索/短期上下文/证据回答。
30 案例独立评测，区分 Exact Match、执行、结果、证据、整场景。
一键 Mock Demo、accept.sh；完整中文文档与安全限制。
新虚拟环境按 requirements.lock 安装，再运行初始化/总验收和实际回环 HTTP。
日期简写/相对月份按固定时点，拒绝不支持年份/日级/币种，没有修改 Ground Truth。
## Modified Files
- .env.example
- README.md
- docs/architecture.md
- docs/evaluation.md
- docs/metrics.md
- scripts/accept.py
- scripts/accept.sh
- scripts/check_database.py
- scripts/demo_deepseek.sh
- scripts/demo_mock.py
- scripts/demo_mock.sh
- scripts/init_db.sh
- scripts/lib_env.sh
- scripts/serve.sh
- src/insightflow/agent/service.py
- src/insightflow/agent/tools.py
- src/insightflow/api/app.py
- src/insightflow/api/routes.py
- src/insightflow/api/schemas.py
- src/insightflow/config.py
- src/insightflow/evaluation/report.py
- src/insightflow/evaluation/runner.py
- src/insightflow/evaluation/scorer.py
- src/insightflow/llm/deepseek.py
- src/insightflow/llm/mock.py
- tests/conftest.py
- tests/test_api.py
- tests/test_chat_api.py
- tests/test_context.py
- tests/test_evaluation.py
另新增 reports/day6.md、FINAL_ACCEPTANCE.md、acceptance.json 和 evaluation/*。
## Commands Executed
干净副本：python3 -m venv .venv；pip install -r requirements.lock；
pip install --no-deps -e .；scripts/init_db.sh；scripts/accept.sh。
总验收含 pytest -v、ruff check/format --check、compileall、pip check、
数据库权限检查与六场景 Mock Demo。真实 uvicorn /health、/schema、/chat 请求。
## Test Results
80 PASS / 0 FAIL / 0 SKIP / 0 ERROR；
单元 33，集成 47。
30/30 SQL 执行、参考结果、证据和场景通过；Exact Match 8/30，不以字符串不同判错。
P50=13.656 ms，P95=26.916 ms；Mock 策略调用 70，
重试均值 0。真实 DeepSeek NOT RUN，Token 未知。
## Known Issues
仅固定合成数据和受控中文指标；无认证/生产隔离；Session 重启丢失；
上下文 Token 为估算，查询计划是估算防护，非硬资源沙箱。
## Unverified Claims
没有真实模型成功率、实际计费、生产吞吐或安全认证数据。没有远程 CI 声明。

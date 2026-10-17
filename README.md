# InsightFlow · 可审计的数据分析 Agent

中文问题 → DeepSeek Flash Max计划/工具决策 → 授权Schema与指标 → SQL安全+语义校验 →
PostgreSQL只读查询 → 引用证据的回答。持久会话、幂等、取消、SSE和有界运行治理。

这是受控合成数据原型，真实模型并非全绿。当前升级分支仅本地，未推送或公网部署。
历史源码/30题/实验保留，[V1说明](README.v1.md)。

## 快速开始
本次本机环境已配置：
```bash
./scripts/serve.sh
# 另一个本机终端，只显示本地演示Bearer，绝不是模型Key：
.venv/bin/python scripts/local_token.py
```
浏览器打开 http://127.0.0.1:8000，填Bearer后提问；默认入口已切换到认证V2。
本地.env已选择deepseek-flash、thinking enabled、reasoning_effort max。
代码和CI默认Mock；真实请求只从本地凭据读取Key。
本轮所有真实阶段/演示固定同一专用运行库和2USD/500HTTP尝试共享账本，不能换阶段重置。
剩余额度和调用数见[总验收](reports/UPGRADE_ACCEPTANCE.md)。

新环境按[部署与非破坏迁移](docs/deployment-v2.md)安装锁依赖、初始化角色；
`./scripts/start_compose.sh`提供Docker入口，但本机缺Docker引擎，实际容器验收未完成。

## 查看实现
[实际架构](docs/architecture-v2.md) · [DeepSeek核实与费用](docs/deepseek-integration.md) ·
[能力边界](docs/capabilities.md) · [V2评测](docs/evaluation-v2.md) ·
[工程取舍](docs/tradeoffs.md) · [源码学习路径](docs/learning-path-v2.md) ·
[十分钟演示](docs/demo-script.md) · [中文项目描述](docs/project-description-zh.md)。

## 验证
```bash
.venv/bin/python -m pytest -v
.venv/bin/ruff check src tests scripts
.venv/bin/ruff format --check src tests scripts
.venv/bin/python scripts/scan_secrets.py --mode files
.venv/bin/python -m insightflow.v2.evaluation --mode mock --output /path/to/NEW-offline-report
.venv/bin/python scripts/fresh_verify.py --output /path/to/NEW-private-audit-directory
```
所有DB测试要求专用insightflow_test，不使用SKIP。
原V1回归需显式加载TEST连接变量；不需要模型Key或付费开关。
真实实验脚本会付费，只在明确授权并检查共享账本后运行，不属于常规CI。

## 真实结果与限制
离线87/87；真实Max两轮25/30、27/30；定向8/9；四场景真实HTTP通过。
Schema规则与全量真实小样本均2/2，没有证明检索提高模型正确率。
有上下文/错误反馈对照各两样本，不能推广到任意问题。
HTTP对照显示V2更慢：持久化治理不是本次已实现的吞吐优化。
会话按主体隔离，业务合成数据共享，没有行级多租户、SSO、Exactly-once或生产SLA。
[全部原始记录](evaldata/upgrade) · [机器验收与逐项状态](reports/UPGRADE_ACCEPTANCE.md)。

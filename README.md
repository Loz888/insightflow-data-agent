# InsightFlow · 可审计的数据分析 Agent

中文问题 → DeepSeek Flash Max计划/工具决策 → 授权Schema与指标 → SQL安全+语义校验 →
PostgreSQL只读查询 → 引用证据的回答。持久会话、幂等、取消、SSE和有界运行治理。

这是受控合成数据原型，真实模型并非全绿。当前试点源码与验收材料随仓库更新，尚未公网部署。
历史源码/30题/实验保留，[V1说明](README.v1.md)。

## 系统评审修复 · 2026-10-20

[逐项对照、实现与剩余范围](docs/review-20261020/IMPLEMENTATION.md) · [本轮验收](reports/review-20261020/verification.json)

本轮修复评分器文本/数值语义和无序容差匹配，保留 PostgreSQL 列类型；阻止模型擅加条件污染会话，补齐用户纠正与范围澄清；统一工作流/Prompt 版本，旧恢复点在重新排队前明确拒绝。新环境 **357 项测试通过、0 失败、0 跳过**。

历史 206 次结果比较、330 次跨快照比较已离线重算，判定变化 0；原始题集、真实模型成果与失败全部保留。本轮没有新增付费调用，后续模型仍为 **Max**。

[实验结果、改进与证据范围](docs/review-20261020/RESULTS.md) · [逐次远端 CI 记录](reports/review-20261020/remote-ci.json)

| 证据层次 | 已记录结果 |
|---|---|
| 本轮工程验收 | 新环境及 941a64e 两轮 CI 均为 357 PASS、0 FAIL、0 SKIP |
| 本轮历史重算 | 206 次结果比较 + 330 次跨快照比较，判定变化 0 |
| 历史真实模型 | Max 25/30、27/30；定向 8/9；HTTP 4/4，保留失败与版本 |

最初 CI 有一次未保留用例详情的失败，根因未确认；已补诊断后两轮通过，[异常记录](docs/review-20261020/RESULTS.md#ci-异常记录与源码身份)保留，不据此宣称根因已修复。

## 历史真实成果与前轮试点 · 2026-10-20

[已完成工作与当前边界](docs/pilot/STATUS.md) · [后续改进](docs/pilot/IMPROVEMENT_OUTLINE.zh-CN.md)

**真实 DeepSeek Max 测验已完成**：代表集两轮 25/30、27/30，定向复验 8/9，最终真实 HTTP 4/4；[原始结果与失败](reports/UPGRADE_ACCEPTANCE.md)全部保留。当前后续配置切回 **Max**，无需重复从零评测。

前轮试点已加入摘要 Token、可信租户与 FORCE RLS、真实 PostgreSQL Checkpointer、共享模型许可、会话删除和请求大小限制；当时为 332 PASS。本轮在其基础上完成 **357 PASS / 0 FAIL / 0 SKIP**；旧报告保留各自快照，不替代真实模型质量评测。

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
旧 loopback 模式使用共享合成业务数据；新 internal-pilot 模式具有可信租户 FORCE RLS，见当前边界说明。没有 SSO、付费 Exactly-once 或生产 SLA。
[全部原始记录](evaldata/upgrade) · [机器验收与逐项状态](reports/UPGRADE_ACCEPTANCE.md)。

# 当前实现与验收（2026-10-20）

真实模型测验已经完成。此次保留所有成功、失败、费用记录与原始评测集，不重新调用模型来证明历史成果。

## 已完成的真实 Max 测验

| 实验 | 实际结果 | 证据 |
|---|---|---|
| 第一轮代表集 | 25/30 | [报告](../../evaldata/upgrade/live-max-001/report.md) |
| 第二轮代表集 | 27/30，查询 23/26 | [报告](../../evaldata/upgrade/live-max-002/report.md)、[失败](../../evaldata/upgrade/live-max-002/failures.json) |
| 定向复验 | 8/9 | [报告](../../evaldata/upgrade/live-max-regression-001/report.md) |
| 最终真实 HTTP | 4/4 | [配置快照与结果](../../evaldata/upgrade/live-http-002-final/summary.json) |
| 小样本检索/上下文/反馈对照 | 已完成，样本不足以推广 | [汇总](../../evaldata/upgrade/live-paired-001/summary.json) |

这些是真实厂商请求，绑定各自的历史代码和数据快照；不是所有题都正确，也不是当前新增 RLS/Checkpointer 版本的全量 Live 验收。
原始 30 题、V2 离线 87/87、历史失败和预算记录不覆盖。完整历史验收见 [UPGRADE_ACCEPTANCE.md](../../reports/UPGRADE_ACCEPTANCE.md)。

## 当前代码的新增能力

- `internal-pilot` 使用可撤销摘要 Token、服务端可信租户和主体作用域；会话、运行、导出、删除等入口检查身份。
- 显式授权的试点业务表启用 FORCE RLS；事务内注入租户上下文，Reader 非所有者、非超级用户、无 BYPASSRLS。旧 loopback 模式与试点模式边界分开。
- 实际 AsyncPostgresSaver、版本化工作流和运行到 Graph Thread 的服务端映射；Mock 的持久恢复已测试，付费请求不确定结果仍保守阻止自动重放。
- 同一控制数据库内跨 API 进程的模型许可与未知费用保留；HTTP 请求体、SQL、结果、步骤和时间均有界。
- 会话删除清理敏感内容与 Checkpoint，保留必要审计和费用记录；自动按年龄/容量清理仍需补齐。
- 新环境初始化、迁移重放、真实 HTTP 与备份恢复实验入口保留。

## 当前配置与本次验证

默认 `deepseek-flash` / thinking enabled / `reasoning_effort=max`，保留 High 显式配置；Mock 仍是代码/CI 的默认运行模式。模型强度不会打开付费开关。

本次最新源码在新 Python venv、新 PostgreSQL16 集群和四个隔离数据库中完成 **332 PASS / 0 FAIL / 0 SKIP / 0 ERROR**，迁移重放和 Mock 真实 HTTP 均通过。见[新环境记录](../../reports/pilot/fresh-environment.json)、[发布验证](../../reports/pilot/github-update-20261020.json)及[源码内容清单](source-manifest.json)。

源码清单绑定内容；报告中的基线提交 SHA 不能单独代表其后的全部本地改动。本次更新不发生新付费调用，不重置原 2 美元/500 HTTP 尝试账本，也不将历史保守记账当成厂商账单。

## 远端预检兼容修复

首次同步的远端 CI 在旧五表授权预检处失败。当前预检显式区分 V1/V2，原五表行数与权限断言保留，V2 严格检查十表授权，并增加“额外授权必须拒绝”的真实数据库回归。新环境现在直接执行与 CI 相同的 accept.py：332 测试、原 30 题严格评测和 Mock 演示通过。见[完整验收](../../reports/pilot/full-acceptance-20261020.json)及[失败归因](../../reports/pilot/ci-preflight-fix-20261020.json)。

## 备份恢复复验

本次复用既有脚本，从新环境夹具导出一致性快照并恢复到另一独立集群，核对会话、运行、事件、Checkpoint 内容及 Reader/RLS 权限，结果 PASS。见[机器记录](../../reports/pilot/restore-20261020.json)。此小规模夹具的耗时不是生产恢复承诺。

## 剩余边界

不是任意中文或 SQL 等价证明系统；语义契约可能误拒绝。没有 SSO、外部副作用 Exactly-once 或生产 SLA。容器实际运行仍因无引擎 BLOCKED，跨进程压力与保留策略需继续完善。当前试点新增功能与历史真实模型成绩分别验收。

后续工作是增量补齐：[改进大纲](IMPROVEMENT_OUTLINE.zh-CN.md)。远端 CI 以本次提交对应 Actions 为准，不能借用旧版本绿色状态。

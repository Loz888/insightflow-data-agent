# 实验结果、改进与证据范围

日期：2026-10-20。实现说明见 [IMPLEMENTATION](IMPLEMENTATION.md)，后续优先级见[改进路线](../pilot/IMPROVEMENT_OUTLINE.zh-CN.md)。本页区分历史真实模型成绩、本轮离线重算与工程验收。

| 实验 / 验收 | 实际结果 | 范围与证据 |
|---|---|---|
| 历史 Max 代表集两轮 | 25/30、27/30；第二轮查询 23/26 | [历史总验收与全部失败](../../reports/UPGRADE_ACCEPTANCE.md)；不是当前 Prompt/工作流版本的新成绩 |
| 历史定向复验 / 真实 HTTP | 8/9；4/4 | [定向记录](../../evaldata/upgrade/live-max-regression-001/report.md)、[HTTP 记录](../../evaldata/upgrade/live-http-002-final/summary.json)；不同集合不合并为总体成功率 |
| 历史结果离线重算 | 206 次结果比较、330 次跨快照比较；判定变化 0 | [冻结输入哈希与重算记录](../../reports/review-20261020/scorer-replay.json)；没有调用模型，也没有重造缺失的 E2E 轨迹 |
| 本轮新环境 | 357 PASS，0 FAIL、0 SKIP、0 ERROR；172 单元、185 集成 | [机器验收](../../reports/review-20261020/verification.json)、[完整验收](../../reports/review-20261020/full-acceptance.json) |
| V2 离线 | 87/87：55 查询、20 澄清拒绝、12 契约 | [离线记录](../../reports/review-20261020/offline-summary.json)；Mock + 真实 PG，不代表 Live 87/87 |
| 远端 CI，941a64e | 两轮完整工作流通过，每轮 357 PASS，0 FAIL、0 SKIP | [首轮通过](https://github.com/Loz888/insightflow-data-agent/actions/runs/39413974354)、[重复通过](https://github.com/Loz888/insightflow-data-agent/actions/runs/39416775158)、[精简记录](../../reports/review-20261020/remote-ci.json)；原 30 题严格评测、独立评测入口均执行 |

## 从实验发现到改进

| 问题 | 本轮实现 | 结论边界 |
|---|---|---|
| 文本编码与数值被混比较，无序容差可能错配 | 独立参考列类型决定 Decimal 容差；文本精确；有界一对一匹配保留重复次数 | 原题答案不变；历史重算判定不变，不是新增模型准确率提升 |
| 模型擅加日期/地区或错误继承上下文 | 工具前的计划守卫、明确纠正覆盖、全国清除地区、主数据清除无关约束、年份范围澄清 | 覆盖已测条件；完整来源/确认/撤销生命周期尚未完成 |
| 优化解释器可能绕过预算检查 | 保留已有显式 if/raise，增加正常 Python 与 python -O 子进程回归 | 非法配置在 HTTP 前拒绝；没有重置账本 |
| 新旧图状态被静默混用 | 集中 Prompt/工作流版本，旧恢复点在重新排队前拒绝 | 不改旧记录；升级需先排空旧实例，不声称无缝滚动升级 |

## CI 异常记录与源码身份

最初 48732e0 的远端验收为 356 PASS / 1 FAIL / 0 SKIP，但当时工作流未输出 pytest 失败详情。**根因仍为 UNCONFIRMED**，不能据后续通过声称已修复该次偶发问题。

941a64e 只修改 CI 失败诊断输出，产品代码和断言与 48732e0 相同；其后两轮完整 CI 通过。失败记录保留，后续若复现可读取用例详情。见[逐次运行记录](../../reports/review-20261020/remote-ci.json)。

[本地源码清单](source-manifest.json)保留原新环境验证时的内容，不重写历史哈希。其产品内容随 48732e0 提交；941a64e 的差异只有 .github/workflows/ci.yml，远端证据绑定该确切提交。今后的文档提交不把这些旧绿色状态冒充当前提交验证。

## 保留限制与下一轮

原始失败、题集、费用与尝试计数保留。本轮没有新增付费请求；后续配置仍为 deepseek-flash / Max。历史两轮有多处实现变化和模型随机性，25/30 到 27/30 不能归因于本轮守卫或单一因素。

规则检索与全量真实小样本各 2/2，不证明检索提升；HTTP 对照存在治理开销，不声称吞吐提升。完整记忆来源、确定性 SQL 编译对照、独立大 Schema / 挑战集继续按增量路线推进。容器实际运行 BLOCKED，真人自然语言复核 NOT_RUN；未完成 SSO、完整生命周期或生产 SLA 验收。

# 当前进度（2026-10-20）

原阶段 A 基线保留在 BASELINE_AUDIT.md / reports/pilot/baseline.json，不能代表当前实现。

已完成历史真实 Max 代表集（25/30、27/30）、定向复验（8/9）、最终真实 HTTP（4/4）、87 项离线评测；原成功、失败、费用记录均保留。
当前试点新增摘要身份、租户 FORCE RLS、AsyncPostgresSaver、跨进程模型许可、会话删除与请求大小限制。最新新环境完整复验 331 PASS / 0 FAIL / 0 SKIP / 0 ERROR，迁移重放和 Mock HTTP 通过。

后续配置为 deepseek-flash / thinking enabled / Max；High 保留显式支持。既有实验 ID、预算账本及调用计数不重置；此次同步不新发付费请求。Agent Runtime 设置不受影响。

当前实现与历史真实模型验收范围分开，Docker 实际运行仍 BLOCKED。机器证据、源码清单及剩余缺口见 docs/pilot/STATUS.md。远端 CI 以本次提交为准，尚未公网部署。

# InsightFlow 升级验收（历史 V2 快照）

> 本文保留历史代码快照及当时的验证结论，不覆盖原始真实模型结果。2026-10-20 的试点实现、新环境复验和剩余边界见 [当前状态](../docs/pilot/STATUS.md)。

结论：**PARTIAL_PASS**。实现与工程验收完成；真实模型不是全绿，Docker和真人复核尚未完成。
实际执行2026-10-17；独立本地分支 `upgrade/deepseek-runtime-v2`。未推送、未公网部署。
最终付费HTTP与全新环境核验代码快照：`c2ed5747ef6b6110d8b7af74ff49f546e5564639`。
后续交付提交只整理文档/证据；核心哈希见 core-manifest.json。

## 已实施文件组
- src/insightflow/v2：契约、语义、检索、异步Provider、工具、LangGraph、Store、Runtime、API、页面、OTel/Prometheus、评测。
- migrations/005–008：运行控制面、费用结算、新增业务/干扰表、重复配送事件夹具；不改旧五表数据。
- tests/test_v2_*：协议/语义/87数据案例/真实PG运行时；原138测试保留。
- scripts：版本化迁移/最小角色、双快照、HTTP性能/故障/Live、小样本成对、新环境验证、Compose配置。
- Dockerfile/compose.yaml/.github/workflows/ci.yml/锁定依赖及九份V2文档。
原FK断言只缩小到它原本负责的五表，仍严格等于4；另加扩展Schema严格等于8，不改业务答案。

## 验收矩阵
| 事项 | 状态 | 实际证据 |
| --- | --- | --- |
| 原始基线 | PASS | baseline-tests.json：138，旧测试名称全保留 |
| 最终工程测试 | PASS | 新venv+新PG集群：325 PASS / 0 FAIL / 0 SKIP / 0 ERROR；148单元+177集成 |
| 原30题与答案 | PASS | SHA不变，original30-final保留原runner实测 |
| V2离线 | PASS | 87/87，55查询+20澄清拒绝+12离线契约；双Seed逐SQL核对 |
| 真实Max理解/计划/工具/SQL/解释 | PASS | live-http-002-final 4/4，带代码SHA；/models HTTP200 |
| 真实代表集全部正确 | FAIL | 第二轮27/30，查询结果23/26；3条失败保留 |
| 定向真实复验全部正确 | FAIL | 8/9；NULL退款率SQL等价形式仍被保守契约拒绝 |
| 最近30天/排除地区/缺历史同比 | PASS | 真实与离线记录，不变成全量/包含/虚假同比 |
| 工具故障反馈 | PASS | 明确元数据故障注入；有反馈2/2，无反馈0/2 |
| 运行治理 | PASS | 真Claim、跨实例顺序、SIGKILL、fencing、幂等、取消、deadline、关闭、过载 |
| 认证所有权/SQL安全 | PASS | 不接受自报主体，越权404；继承原AST/Reader/只读/资源限制 |
| 检索质量和真实效果分开 | PASS | 10表质量集；规则/全量真实各2/2，无“提升”结论 |
| 性能测量 | PASS | 两轮真实HTTP Mock对照，V2有治理开销；不宣称吞吐提升 |
| 全新环境与迁移重放 | PASS | fresh-environment.json；真实HTTP成功，原集群不动 |
| Docker/Compose实际运行 | BLOCKED | 本机无Docker引擎；仅配置生成/YAML通过 |
| V2远端Actions | NOT_RUN | 用户禁止自行推送；旧main绿色结果不是V2证据 |
| 真实厂商流式评测 | NOT_RUN | 协议模拟覆盖中断/Usage，实际Live主评测用非流式 |
| 独立真人自然语言复核 | NOT_RUN | 已准备代表样本与审阅表，不把AI审阅冒充真人 |
| 备份恢复演练 | NOT_RUN | 提供开发重建/备份恢复说明，未声称已恢复 |

## 真实结果与失败
第一轮Max25/30，第二轮27/30；多处代码改动和模型随机性并存，不把差值当单变量收益。
第二轮剩余问题：客户SQL别名保守误拒绝、商品价格被模型添加无订单归属日期、多轮动作坏JSON。
定向复验修复前两类并通过相关多轮，但零分母退款率的另一等价写法仍拒绝。失败没有删。
旧非thinking两次工具循环失败、早期评测器接口错误、早期配置环境合并/Schema断言失败均有阶段记录。
SQL拒绝并未变成成功结果；澄清拒绝不计入查询执行率。

## 小样本与性能
真实Schema：规则2/2、全量2/2；上下文2/2对0/2；反馈2/2对0/2。每臂仅2题，不能推广。
10表Recall都是1.0，Precision全量.18、规则1.0、词法.5667，因此默认规则。
HTTP001保留V1“销售额”不支持的32次失败；002只统一为双方支持的“营收”，全部记录仍在。
002 V1 127/128、V2 128/128；V2四档吞吐约9.88/17.04/16.53/14.10 req/s，
P95约103/134/326/627ms；控制面开销真实存在。非隔离本地主机、小样本，不是SLA。
真实Max第二轮P50约11.67s、P95约23.62s（多轮含前序处理）；不能与Mock指标混用。

## 预算
统一账本保守累计记账 **0.4856967 USD / 2.00 USD**，HTTP尝试 **468 / 500**，剩余 32 次。
按可信Usage以峰值价格结算，未知请求保留预留；这不是实际供应商账单或绝对硬封顶。
没有重置预算/自动加额。后续本机演示已固定同一测试控制库和实验ID；不会再次取得2USD。
Key只在本机0600受忽略配置；Key只用于API鉴权，不进入Prompt、日志、Git或交付包。私有思维链不保存。

## 必须保留的边界
业务行级多租户、SSO、分布式全局限流、付费Exactly-once、任意中文/SQL等价证明、生产SLA都没有实现或声称。
Runtime按principal隔离会话和run，业务合成数据共享。管理员更换控制库/实验ID属于受信任运维边界。
自动自然语言评分是辅助；需要真人独立复核样本包。提供Docker引擎后才能关闭容器验收BLOCKED。

## 证据入口
- [机器验收](upgrade/acceptance-final.json)、[全新环境](upgrade/fresh-environment.json)
- [最终真实HTTP](../evaldata/upgrade/live-http-002-final/summary.json)
- [真实30场景](../evaldata/upgrade/live-max-002/report.md)、[失败](../evaldata/upgrade/live-max-002/failures.json)
- [定向复验](../evaldata/upgrade/live-max-regression-001/report.md)、[成对实验](../evaldata/upgrade/live-paired-001/summary.json)
- [费用与多轮补充](../evaldata/upgrade/audit-completion-final/budget-final.json)、[真人复核包](../evaldata/upgrade/audit-completion-final/human-review.md)
- [最终离线](../evaldata/upgrade/offline-final-001/report.md)、[原30题](../evaldata/upgrade/original30-final/report.md)
- [HTTP性能](../evaldata/upgrade/http-performance-002/runs.json)、[HTTP故障](../evaldata/upgrade/http-faults-001/results.json)
- [架构](../docs/architecture-v2.md)、[学习路径](../docs/learning-path-v2.md)、[十分钟演示](../docs/demo-script.md)

可追踪问题清单：[issues.json](upgrade/issues.json)。安装包页面资产已通过真实wheel构建检查。

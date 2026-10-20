# 性能与可观测性
> 以下是历史 V1 直接调用测量，保留原值；当前 V2 使用会话级调度，不能用本页的全局串行锁描述现实现。V1/V2 真实 HTTP 对照及治理开销见 [V2 评测](evaluation-v2.md#性能与保留失败)；本轮没有新增吞吐实验。

本次实际执行 2026-10-17，Mock 模式、固定同一合成数据，真实 PostgreSQL。
环境：Python 3.12.3，PostgreSQL 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1)，
CPU AMD Ryzen AI 9 H 365 w/ Radeon 880M，可见逻辑核 20，
WSL 可见内存 14111404 KiB。
数据 100 客户/30 商品/500 订单/1001 明细/165 退款。

## 测量入口与口径
直接并发调用 AgentService.run，不是 HTTP 吞吐；每档 128 请求，
并发 1/2/4/8，共 512 个唯一 RunID。每请求使用独立 Session 与固定八问题轮换。
数据库/编译缓存经此前验收预热；每档创建新服务和连接池，不是冷数据库试验。
吞吐=完成数/整档墙钟秒，含线程池启动/收尾；延迟从排队前到返回。
P50/P95/P99 使用 nearest rank，ceil(n*p)-1；128 个样本的尾部不稳定，
不能推广成生产 SLA 或真实模型性能。

| 并发 | 完成/成功/失败 | req/s | P50 ms | P95 ms | P99 ms | 平均排队 ms | 平均 SQL 节点 ms |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 128/128/0 | 86.71 | 11.621 | 14.484 | 16.047 | 0.028 | 6.915 |
| 2 | 128/128/0 | 80.91 | 22.871 | 28.744 | 68.472 | 10.819 | 7.409 |
| 4 | 128/128/0 | 83.69 | 45.726 | 53.063 | 54.946 | 34.178 | 7.068 |
| 8 | 128/128/0 | 82.88 | 60.728 | 255.438 | 359.966 | 81.307 | 7.101 |

## 瓶颈解释
吞吐在各档接近，SQL 节点均值变化较小，排队随并发明显增长。
源码使用全局串行锁，观测与这一限制一致；不能据此把高 P95 自动归咎 PostgreSQL。
并发 8 的尾延迟还可能受锁调度和主机负载影响，这不是已单独验证的因果结论。

## 阶段 Trace
observability.observed_node 与 Tools.measured 沿用原日志：
run_id/request_id、哈希 session_id、model_name、node_name/tool_name、
实际 duration_ms、error_kind、SQL retry_count。
没有记录用户问题、SQL、业务结果、Key 或数据库密码。
timings 包含理解、检索、上下文构建、模型生成、校验、执行、回答及排队。
llm_duration_ms=理解+模型生成；generation_node 还含 Context。
这些聚合字段会重叠，不能把所有键相加当总延迟。
SQL 节点含后端强制二次 AST 校验、计划检查、查询和取数，不等于纯服务器执行时间。
全部耗时来自 perf_counter，不是配置 Timeout。Token Usage 在 Mock 中为 null/未知。

## 三条实际执行计划
诊断脚本先使用同一 Validator，再由 Reader 在只读事务执行受控
EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON)。API 仍拒绝用户提交 EXPLAIN。

| SQL 类别 | 实际算子 | Planning ms | Execution ms | Shared hit / read |
| --- | --- | ---: | ---: | --- |
| single_filter | Index Scan | 0.119 | 0.03 | 3 / 0 |
| join_group | Aggregate, Hash Join, Hash Join, Seq Scan, Hash, Seq Scan, Hash, Seq Scan | 0.398 | 0.418 | 12 / 0 |
| time_aggregate | Aggregate, Bitmap Heap Scan, Bitmap Index Scan | 0.049 | 0.03 | 5 / 0 |

Seq Scan 顺序读候选表；Index Scan 按索引定位候选行；
Hash Join 建立/探测散列表，Nested Loop 为外层行执行内层；
Aggregate 汇总/分组，Buffers 区分共享缓存命中与实际读取。
具体本次是否使用某算子以上表和 plans.json 为准；没有选索引不等于索引无效，
小表/低选择性常使顺序扫描成本较低，不能强制索引冒充优化成果。
这些小数据暖缓存计划不能代表大规模 I/O 性能。
参考 PostgreSQL 16 文档：https://www.postgresql.org/docs/16/using-explain.html 。

原始运行/环境/计划在 evaldata/performance/；完整日志保存在仓库外。
真实 DeepSeek 并发实验 NOT_RUN。后续性能优化留在 Roadmap，本阶段不改变串行设计。

# 评测方法
数据固定随机种子 20261020、参考时点 2026-10-01 UTC、CNY。
questions.json 共 30 案例：10 基础、10 JOIN/聚合、5 复杂指标、5 多轮。
ReferenceSQL 由独立脚本维护和真实执行；不导入 Agent SQL 构造器。
expected_results.json 保存参考结果；正常验收不会重新生成或改写 Ground Truth。

Runner 为每案生成新 UUID Session，请求必要前序轮次再执行待评问题。
生成 SQL 再经过 AST 校验与真实 PostgreSQL 执行；事后独立重查生成 SQL，
核对回答 evidence 与可解析的答案负载。还验证 expected_metric 和多轮关键约束。

分开统计：
- SQL Exact Match：规范化 SQL 文本相同率；不同写法不自动判错。
- SQL Execution：取得真实结果且没有错误。
- SQL Result：列名匹配，按 ordered 标记比较顺序或多重集合。
  数值用 Decimal，绝对容差 1e-8、相对容差 1e-9，NULL 不等于 0，保留重复行。
- Answer Groundedness：回答数值与独立重查一致；正确性另与参考结果对比。
  这验证结构化结果转述，不是通用自然语言事实评审。
- End-to-End：执行/结果/证据/指标/上下文全部正确，所有前序轮次成功。

计时从前序会话预热前开始，到最终图的证据回答结束；不含事后独立重查。
因此 5 个多轮案例包含两次问答成本。P50/P95 使用 nearest rank，
不宣称吞吐量或硬件可迁移性能。
Mock 策略调用统计理解与 SQL 生成，35 次问答通常 70 次策略调用；
外部模型调用为零。真实 API Usage 缺失则 Token 为 null，不能称零成本测量。

scripts/accept.sh 输出外部 JSON、Markdown 和完整失败列表。
工程检查失败退出 2；评测产生记录但场景有错退出 1；全部通过退出 0。
失败模型样本仍保存在 failures.json，不为全绿修改参考答案。
tests/test_evaluation.py 有“SQL 能执行但结果错误”的负向对照，证明不会被误判成功。
真实 DeepSeek 默认 NOT RUN；只有用户显式启用才运行单个 demo，不自动做 30 次付费评测。

本次实际记录见 [评测报告](../reports/evaluation/report.md)、
[汇总](../reports/evaluation/summary.json)和[逐案观测](../reports/evaluation/runs.jsonl)。
小规模 Mock 正确率不代表真实 DeepSeek 对未知问题的能力。

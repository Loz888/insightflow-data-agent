# InsightFlow Evaluation

实际 mock + PostgreSQL 运行记录。案例数量见汇总。
Mock 结果不代表真实 DeepSeek 能力。Token 未知保留 null；延迟为本机小样本。

| Metric | Value |
| --- | ---: |
| cases | 30 |
| model_type | mock |
| sql_exact_match_rate | 0.26666666666666666 |
| sql_execution_rate | 1.0 |
| sql_result_accuracy | 1.0 |
| answer_groundedness | 1.0 |
| success_rate | 1.0 |
| p50_ms | 10.676 |
| p95_ms | 23.021 |
| average_retry_count | 0.0 |
| model_call_count | 70 |
| token_usage_known_cases | 0 |
| input_tokens | None |
| output_tokens | None |
| error_distribution | {} |
| real_deepseek | NOT RUN |

## 案例结果

| Case | SQL executed | Correct | Grounded | E2E | Error |
| --- | --- | --- | --- | --- | --- |
| q01 | True | True | True | True |  |
| q02 | True | True | True | True |  |
| q03 | True | True | True | True |  |
| q04 | True | True | True | True |  |
| q05 | True | True | True | True |  |
| q06 | True | True | True | True |  |
| q07 | True | True | True | True |  |
| q08 | True | True | True | True |  |
| q09 | True | True | True | True |  |
| q10 | True | True | True | True |  |
| q11 | True | True | True | True |  |
| q12 | True | True | True | True |  |
| q13 | True | True | True | True |  |
| q14 | True | True | True | True |  |
| q15 | True | True | True | True |  |
| q16 | True | True | True | True |  |
| q17 | True | True | True | True |  |
| q18 | True | True | True | True |  |
| q19 | True | True | True | True |  |
| q20 | True | True | True | True |  |
| q21 | True | True | True | True |  |
| q22 | True | True | True | True |  |
| q23 | True | True | True | True |  |
| q24 | True | True | True | True |  |
| q25 | True | True | True | True |  |
| q26 | True | True | True | True |  |
| q27 | True | True | True | True |  |
| q28 | True | True | True | True |  |
| q29 | True | True | True | True |  |
| q30 | True | True | True | True |  |

失败样本完整保存在 failures.json；执行成功和结果正确分别统计。
SQL Exact Match 只作语法比较，不用它否决等价结果。
P50/P95 使用 nearest rank；每案计时含会话预热（若有）到结果证据回答，
不含事后独立参考复查；模型调用数和重试包含预热轮次。

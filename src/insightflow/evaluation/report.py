import json
from pathlib import Path


def save_report(output, records, summary):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "runs.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    failures = [r for r in records if not r["scenario_success"]]
    (output / "failures.json").write_text(json.dumps(failures, ensure_ascii=False, indent=2) + "\n")
    rows = [
        "# InsightFlow Evaluation",
        "",
        "实际 Mock + PostgreSQL 运行记录。30 案例含 10 基础、10 JOIN/聚合、5 复杂指标、5 多轮。",
        "此结果不代表真实 DeepSeek 能力。Token 未知保留 null；延迟为本机小样本。",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    rows += [f"| {k} | {v} |" for k, v in summary.items()]
    rows += [
        "",
        "## 案例结果",
        "",
        "| Case | SQL executed | Correct | Grounded | E2E | Error |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    rows += [
        f"| {r['case_id']} | {r['sql_executed']} | {r['result_correct']} | {r['answer_grounded']} | {r['scenario_success']} | {r['error_kind'] or ''} |"
        for r in records
    ]
    rows += [
        "",
        "失败样本完整保存在 failures.json；执行成功和结果正确分别统计。",
        "SQL Exact Match 只作语法比较，不用它否决等价结果。",
        "P50/P95 使用 nearest rank；每案计时含会话预热（若有）到结果证据回答，",
        "不含事后独立参考复查；模型调用数和重试包含预热轮次。",
    ]
    (output / "report.md").write_text("\n".join(rows) + "\n")

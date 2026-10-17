"""V2 independent reference evaluation; never consumes a case ID/answer in model prompts."""

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
from dotenv import dotenv_values
from insightflow.database.connection import checked_connection
from insightflow.database.executor import json_value
from insightflow.database.errors import AgentError, ErrorKind
from insightflow.evaluation.scorer import equivalent
from insightflow.v2.api import load_settings
from insightflow.v2.contracts import ChatInput, QueryPlan, Action, Answer
from insightflow.v2.errors import Fault
from insightflow.v2.service import Runtime
from insightflow.v2.semantics import SemanticSQLGuard, reference_sql
from insightflow.v2.graph import verify_answer
from insightflow.v2.provider import PROMPT_VERSION

ROOT = Path(__file__).resolve().parents[3]


def reference_result(sql, dsn):
    def query(text):
        with checked_connection(dsn) as c:
            c.read_only = True
            c.execute("SET statement_timeout='2000ms'")
            c.execute("SET TIME ZONE 'UTC'")
            cur = c.execute(text)
            rows = cur.fetchall()
            return {
                "columns": [x.name for x in cur.description],
                "rows": json_value(rows),
                "row_count": len(rows),
            }

    if isinstance(sql, list):
        a, b = [query(s)["rows"][0][0] for s in sql]
        change = (
            None
            if a is None or b is None or Decimal(str(b)) == 0
            else str((Decimal(str(a)) - Decimal(str(b))) / Decimal(str(b)))
        )
        return {"columns": ["current", "previous", "change_rate"], "rows": [[a, b, change]], "row_count": 1}
    return query(sql)


def constraint_correct(case, plan):
    if plan.get("metric") != case["metric"]:
        return False
    if set(plan.get("include_regions", [])) != set(case["include"]) or set(
        plan.get("exclude_regions", [])
    ) != set(case["exclude"]):
        return False
    if plan.get("dimension") != case["dimension"] or plan.get("top_n") != case["top"]:
        return False
    if case.get("start"):
        windows = plan.get("windows", [])
        if (
            len(windows) != 1
            or not windows[0]["start"].startswith(case["start"])
            or not windows[0]["end"].startswith(case["end"])
        ):
            return False
    expected_comparison = (
        "mom" if "环比" in case["question"] else "yoy" if "同比" in case["question"] else "none"
    )
    if plan.get("comparison") != expected_comparison:
        return False
    if "7月和9月" in case["question"] and [w["start"][:10] for w in plan.get("windows", [])] != [
        "2026-07-01",
        "2026-09-01",
    ]:
        return False
    return True


def compare_result(actual, expected):
    return actual.get("columns") == expected.get("columns") and equivalent(actual, expected, ordered=True)


def offline_contract(case, runtime):
    from insightflow.v2.contracts import Window

    plan = QueryPlan(
        metric="order_count",
        aggregation="count",
        windows=[Window(start="2026-09-01T00:00:00Z", end="2026-10-01T00:00:00Z")],
        exclude_regions=["华东"],
    )
    mutation = case["mutation"]
    sql = reference_sql(plan)
    guard = SemanticSQLGuard(runtime.executor.validator)
    try:
        if mutation == "drop_time":
            sql = "SELECT COUNT(*) AS value FROM business.orders AS o"
        elif mutation == "flip_exclusion":
            sql = sql.replace("NOT IN", "IN")
        elif mutation == "wrong_month":
            sql = sql.replace("2026-09-01", "2026-08-01")
        elif mutation == "wrong_metric":
            sql = sql.replace("COUNT(*)", "COUNT(DISTINCT o.customer_id)")
        elif mutation in ("drop_top", "drop_dimension"):
            plan = plan.model_copy(update={"dimension": "region", "top_n": 2})
            sql = reference_sql(plan)
            sql = (
                sql.replace(" LIMIT 2", "")
                if mutation == "drop_top"
                else sql.replace("c.region AS dimension, ", "")
            )
        elif mutation == "bad_tool":
            Action.model_validate({"call_id": "x", "name": "shell", "arguments": {}})
        elif mutation == "bad_arguments":
            from insightflow.v2.contracts import SQLArgs

            SQLArgs.model_validate({"sql": "SELECT 1", "principal": "admin"})
        elif mutation in ("bad_number", "bad_citation"):
            verify_answer(
                Answer.model_validate(
                    {
                        "explanation": "总数99" if mutation == "bad_number" else "结果如下",
                        "citations": [
                            {
                                "evidence_id": "x" if mutation == "bad_citation" else "e",
                                "row": 0,
                                "column": 0,
                                "value": "1",
                            }
                        ],
                    }
                ),
                {"columns": ["value"], "rows": [["1"]]},
                "e",
            )
        elif mutation == "write_sql":
            sql = "DELETE FROM business.orders"
        elif mutation == "sleep_sql":
            sql = "SELECT pg_sleep(100) FROM business.orders"
        guard.validate(sql, plan)
    except (Fault, AgentError, ValueError):
        return True
    return False


async def run_cases(settings, output, cases, controlled_fault=False, snapshot_urls=None):
    output.mkdir(parents=True, exist_ok=False)
    runtime = Runtime(settings)
    await runtime.start()
    records = []
    code_hash = hashlib.sha256(
        b"".join(p.read_bytes() for p in sorted((ROOT / "src/insightflow/v2").glob("*.py")))
    ).hexdigest()
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    injected = set()
    original = runtime.registry.execute

    async def execute(action, state):
        if controlled_fault and action.name == "execute_sql" and state["run_id"] not in injected:
            injected.add(state["run_id"])
            raise AgentError(
                ErrorKind.SCHEMA_NOT_FOUND,
                "受控故障注入：元数据版本过期，请依据当前授权字段重新生成SQL。",
                retryable=True,
            )
        return await original(action, state)

    # Fault injection only for an explicitly labelled case, switched per request below.
    try:
        for case in cases:
            started = time.perf_counter()
            sid = uuid4().hex
            if case["kind"] == "offline_contract":
                ok = offline_contract(case, runtime)
                records.append(
                    {
                        "case_id": case["id"],
                        "kind": case["kind"],
                        "expected": "reject",
                        "e2e_correct": ok,
                        "live": False,
                    }
                )
                continue
            existing = await asyncio.to_thread(runtime.store.budget, settings.experiment_id)
            if (
                settings.mode == "deepseek"
                and existing
                and (
                    existing["reserved"] >= existing["budget"]
                    or existing["attempts"] >= settings.max_http_attempts
                )
            ):
                records.append(
                    {
                        "case_id": case["id"],
                        "kind": "e2e",
                        "expected": case["expected"],
                        "status": "NOT_RUN_BUDGET",
                        "e2e_correct": False,
                        "live": True,
                    }
                )
                continue
            runtime.registry.execute = original
            warmup_ok = True
            for q in case["warmup"]:
                row, _ = await runtime.submit(
                    "evaluation", ChatInput(session_id=sid, question=q, idempotency_key=uuid4().hex)
                )
                row = await runtime.wait(str(row["run_id"]), "evaluation")
                if row["status"] != "succeeded" or row["result"].get("disposition") != "answer":
                    warmup_ok = False
            if controlled_fault and case.get("controlled_fault"):
                runtime.registry.execute = execute
            row, _ = await runtime.submit(
                "evaluation",
                ChatInput(session_id=sid, question=case["question"], idempotency_key=uuid4().hex),
            )
            row = await runtime.wait(str(row["run_id"]), "evaluation")
            result = row["result"] or {}
            expected = case["expected"]
            query = expected == "answer"
            disposition = result.get("disposition")
            executed = bool(result.get("sql"))
            correct = semantic = False
            reference = None
            snapshots = []
            if query and case.get("reference_sql"):
                reference = await asyncio.to_thread(
                    reference_result, case["reference_sql"], settings.reader_url.get_secret_value()
                )
                correct = executed and compare_result(result.get("evidence", {}), reference)
                if row["status"] == "succeeded":
                    semantic = constraint_correct(
                        case, runtime.store.session(sid, "evaluation")["constraints"]
                    )
                if executed and snapshot_urls:
                    for label, dsn in snapshot_urls.items():
                        ref = await asyncio.to_thread(reference_result, case["reference_sql"], dsn)
                        actual = await asyncio.to_thread(
                            reference_result,
                            result["sql"] if len(result["sql"]) > 1 else result["sql"][0],
                            dsn,
                        )
                        snapshots.append(
                            {
                                "dataset": label,
                                "correct": compare_result(actual, ref),
                                "actual": actual,
                                "expected": ref,
                            }
                        )
            evidence_consistent = False
            if executed:
                periods = result.get("sql_by_period", {})
                actual_sql = (
                    [periods["current"], periods["comparison"]]
                    if "comparison" in periods
                    else result["sql"][0]
                )
                independently_executed = await asyncio.to_thread(
                    reference_result, actual_sql, settings.reader_url.get_secret_value()
                )
                evidence_consistent = compare_result(result.get("evidence", {}), independently_executed)
                if result.get("answer_source") in ("model", "mock"):
                    try:
                        verify_answer(
                            Answer(explanation=result["answer"], citations=result["citations"]),
                            independently_executed,
                            result["evidence_id"],
                        )
                    except (Fault, ValueError):
                        evidence_consistent = False
            good = bool(
                warmup_ok
                and row["status"] == "succeeded"
                and ((correct and semantic and evidence_consistent) if query else disposition == expected)
            )
            records.append(
                {
                    "case_id": case["id"],
                    "question": case["question"],
                    "split": case["split"],
                    "kind": "e2e",
                    "live": settings.mode == "deepseek",
                    "status": row["status"],
                    "error_code": row["error_code"],
                    "expected": expected,
                    "actual_disposition": disposition,
                    "sql_executed": executed,
                    "result_correct": bool(correct),
                    "semantic_correct": bool(semantic),
                    "disposition_correct": disposition == expected,
                    "evidence_consistent": evidence_consistent,
                    "e2e_correct": good,
                    "run_id": str(row["run_id"]),
                    "duration_ms": (time.perf_counter() - started) * 1000,
                    "result": result,
                    "reference": reference,
                    "cross_snapshot_results": snapshots,
                    "controlled_fault": str(row["run_id"]) in injected,
                    "events": runtime.store.events(str(row["run_id"]), "evaluation"),
                }
            )
            # Crash-safe append after each completed actual run; do not overwrite old directories.
            with (output / "runs.jsonl").open("a") as f:
                f.write(json.dumps(records[-1], ensure_ascii=False, default=str) + "\n")
            if settings.mode == "deepseek":
                print(case["id"], row["status"], row["error_code"], "e2e", good, flush=True)
        for rec in records:
            if rec.get("kind") == "offline_contract" or rec.get("status") == "NOT_RUN_BUDGET":
                with (output / "runs.jsonl").open("a") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        queries = [x for x in records if x.get("expected") == "answer"]
        nonquery = [x for x in records if x.get("expected") in ("clarify", "reject") and x["kind"] == "e2e"]

        def fraction(items, key):
            return {"correct": sum(bool(x.get(key)) for x in items), "total": len(items)}

        durations = sorted(x["duration_ms"] for x in records if "duration_ms" in x)

        def quantile(q):
            import math

            return durations[max(0, math.ceil(len(durations) * q) - 1)] if durations else None

        summary = {
            "mode": settings.mode,
            "retrieval_mode": settings.retrieval_mode,
            "context_enabled": settings.context_enabled,
            "feedback_enabled": settings.feedback_enabled,
            "model": settings.model if settings.mode == "deepseek" else "offline-rules",
            "thinking_effort": settings.thinking_effort if settings.mode == "deepseek" else None,
            "at": datetime.now(timezone.utc).isoformat(),
            "git_commit": commit,
            "source_sha256": code_hash,
            "prompt_version": PROMPT_VERSION,
            "data_version": "v1-seed20261020",
            "dataset_sha256": hashlib.sha256((ROOT / "evaldata/v2/cases.json").read_bytes()).hexdigest(),
            "execution": fraction(queries, "sql_executed"),
            "result_accuracy": fraction(queries, "result_correct"),
            "semantic_accuracy": fraction(queries, "semantic_correct"),
            "clarification_rejection": fraction(nonquery, "disposition_correct"),
            "evidence_consistency": fraction(queries, "evidence_consistent"),
            "e2e": fraction(records, "e2e_correct"),
            "not_run_budget": sum(x.get("status") == "NOT_RUN_BUDGET" for x in records),
            "p50_ms": quantile(0.5),
            "p95_ms": quantile(0.95),
            "budget": runtime.store.budget(settings.experiment_id),
            "usage_unknown_runs": sum(
                x.get("result", {}).get("usage", {}).get("unknown_attempts", 0) > 0 for x in records
            ),
            "limitations": [
                "Test questions were inspected during development; frozen_seen is not an unseen benchmark.",
                "Automatic natural-language evidence checking is limited; representative human review is separate.",
                "No causal or production-scale inference.",
            ],
        }
        (output / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n"
        )
        (output / "failures.json").write_text(
            json.dumps(
                [x for x in records if not x["e2e_correct"]], ensure_ascii=False, indent=2, default=str
            )
            + "\n"
        )
        (output / "report.md").write_text(
            "# V2 实测评测\n\n~~~json\n"
            + json.dumps(summary, ensure_ascii=False, indent=2, default=str)
            + "\n~~~\n"
        )
        return summary
    finally:
        await runtime.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["mock", "deepseek"], default="mock")
    p.add_argument("--output", required=True)
    p.add_argument("--live-limit", type=int, default=30)
    p.add_argument("--controlled-fault", action="store_true")
    args = p.parse_args()
    d = {**dotenv_values(ROOT / ".env"), **os.environ}
    s = load_settings().model_copy(
        update={
            "runtime_url": d["INSIGHTFLOW_V2_TEST_RUNTIME_URL"],
            "reader_url": d["INSIGHTFLOW_TEST_DATABASE_URL"],
        }
    )
    # model_copy bypasses validation, so validate the full config again after overrides.
    s = type(s).model_validate({**s.model_dump(), "mode": args.mode, "live_enabled": args.mode == "deepseek"})
    cases = json.loads((ROOT / "evaldata/v2/cases.json").read_text())
    cases += json.loads((ROOT / "evaldata/v2/additional_cases.json").read_text())
    if args.mode == "deepseek":
        ids = [
            1,
            6,
            9,
            14,
            17,
            22,
            25,
            26,
            27,
            28,
            29,
            30,
            31,
            32,
            33,
            34,
            35,
            36,
            39,
            40,
            42,
            43,
            46,
            47,
            48,
            49,
            51,
            55,
            63,
            70,
        ]
        cases = [next(c for c in cases if c["id"] == f"v2-{n:03d}") for n in ids][: args.live_limit]
        cases[0]["controlled_fault"] = args.controlled_fault
    snapshots = {
        f"v2-seed{n}": d[f"INSIGHTFLOW_V2_SEED{n}_URL"]
        for n in (101, 202)
        if d.get(f"INSIGHTFLOW_V2_SEED{n}_URL")
    }
    summary = asyncio.run(run_cases(s, Path(args.output), cases, args.controlled_fault, snapshots))
    print(json.dumps(summary, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()

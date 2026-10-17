import asyncio
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4
import pytest
from dotenv import dotenv_values
from insightflow.v2.config import V2Settings
from insightflow.v2.service import Runtime
from insightflow.v2.contracts import ChatInput
from insightflow.v2.evaluation import reference_result, compare_result, constraint_correct, offline_contract

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "evaldata/v2/cases.json").read_text())
CASES += json.loads((ROOT / "evaldata/v2/additional_cases.json").read_text())


def test_frozen_seen_manifest_and_original_ground_truth():
    manifest = json.loads((ROOT / "evaldata/v2/manifest.json").read_text())
    assert len(CASES) >= 60
    assert (
        hashlib.sha256((ROOT / "evaldata/v2/cases.json").read_bytes()).hexdigest() == manifest["case_sha256"]
    )
    assert "NOT a wholly unseen" in manifest["split_note"]
    baseline = json.loads((ROOT / "reports/upgrade/baseline.json").read_text())
    for n, digest in baseline["original_ground_truth"].items():
        assert hashlib.sha256((ROOT / n).read_bytes()).hexdigest() == digest
    assert set(baseline["original_tests"]) <= {p.name for p in (ROOT / "tests").glob("test_*.py")}


@pytest.mark.integration
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_v2_independent_case(case, database_urls):
    values = {**dotenv_values(ROOT / ".env"), **os.environ}
    dsn = values.get("INSIGHTFLOW_V2_TEST_RUNTIME_URL")
    if not dsn:
        pytest.fail("Dedicated V2 test runtime URL required; no SKIP")
    s = V2Settings(
        runtime_url=dsn,
        reader_url=database_urls[0],
        auth_tokens={"synthetic-dataset-bearer-only": "evaluation"},
    )

    async def go():
        rt = Runtime(s)
        await rt.start()
        sid = uuid4().hex
        try:
            if case["kind"] == "offline_contract":
                assert offline_contract(case, rt)
                return
            for question in case["warmup"]:
                row, _ = await rt.submit(
                    "evaluation", ChatInput(session_id=sid, question=question, idempotency_key=uuid4().hex)
                )
                row = await rt.wait(str(row["run_id"]), "evaluation")
                assert row["status"] == "succeeded" and row["result"]["disposition"] == "answer"
            row, _ = await rt.submit(
                "evaluation",
                ChatInput(session_id=sid, question=case["question"], idempotency_key=uuid4().hex),
            )
            row = await rt.wait(str(row["run_id"]), "evaluation")
            assert row["status"] == "succeeded", row["error_code"]
            result = row["result"]
            assert result["disposition"] == case["expected"]
            if case["expected"] == "answer":
                assert compare_result(
                    result["evidence"], reference_result(case["reference_sql"], database_urls[0])
                )
                assert constraint_correct(case, rt.store.session(sid, "evaluation")["constraints"])
                for seed in (101, 202):
                    url = values.get(f"INSIGHTFLOW_V2_SEED{seed}_URL")
                    if not url:
                        pytest.fail("Independent V2 seed snapshot URL required; no SKIP")
                    proposed = result["sql_by_period"]
                    actual = (
                        [proposed["current"], proposed["comparison"]]
                        if "comparison" in proposed
                        else proposed["current"]
                    )
                    assert compare_result(
                        reference_result(actual, url), reference_result(case["reference_sql"], url)
                    )
            else:
                assert result["evidence"] == {} and result["sql"] == []
                assert rt.store.session(sid, "evaluation")["version"] == len(case["warmup"])
        finally:
            await rt.close()

    asyncio.run(go())

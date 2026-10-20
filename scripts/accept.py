"""Engineering checks and model evaluation have independent statuses and exit codes."""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    out = Path(args.output).resolve()
    # Own a new report directory; never overwrite previous observations.
    out.mkdir(parents=True, exist_ok=False)
    env = os.environ.copy()
    env.pop("DEEPSEEK_API_KEY", None)
    env.pop("INSIGHTFLOW_ENABLE_PAID_EVAL", None)
    env["INSIGHTFLOW_MODE"] = "mock"
    env["INSIGHTFLOW_ENABLE_LIVE"] = "false"
    env["LANGSMITH_TRACING"] = "false"
    steps = []
    commands = [
        (
            "python",
            [
                sys.executable,
                "-c",
                "import sys,fastapi,langgraph,psycopg,sqlglot; assert sys.version_info >= (3,11)",
            ],
        ),
        ("dependencies", [sys.executable, "-m", "pip", "check"]),
        ("database", [sys.executable, "scripts/check_database.py", "--profile", "v2"]),
        ("static", [sys.executable, "-m", "ruff", "check", "src", "tests", "scripts"]),
        ("format", [sys.executable, "-m", "ruff", "format", "--check", "src", "tests", "scripts"]),
        ("compile", [sys.executable, "-m", "compileall", "-q", "src"]),
        ("pytest", [sys.executable, "-m", "pytest", "-v", "--evidence-json", str(out / "tests.json")]),
        ("demo", [sys.executable, "scripts/demo_mock.py"]),
    ]
    foundation = True
    for name, command in commands:
        started = time.perf_counter()
        with (out / (name + ".log")).open("wb") as log:
            result = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        steps.append(
            {
                "name": name,
                "exit_code": result.returncode,
                "duration_ms": round((time.perf_counter() - started) * 1000, 3),
            }
        )
        print(name + ": " + ("PASS" if result.returncode == 0 else "FAIL"), flush=True)
        if result.returncode:
            foundation = False
            break
    tests = json.loads((out / "tests.json").read_text()) if (out / "tests.json").exists() else None
    if tests and (tests["skipped"] or tests["failed"] or tests["errors"] or not tests["passed"]):
        foundation = False
    model_status = "NOT RUN"
    summary = None
    if foundation:
        with (out / "evaluation.log").open("wb") as log:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "insightflow.evaluation.runner",
                    "--output",
                    str(out / "evaluation"),
                    "--strict",
                ],
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        if (out / "evaluation/summary.json").exists():
            summary = json.loads((out / "evaluation/summary.json").read_text())
            model_status = "PASS" if result.returncode == 0 else "FAIL"
        else:
            foundation = False
            model_status = "ENGINEERING_ERROR"
    report = {
        "engineering": "PASS" if foundation else "FAIL",
        "mock_evaluation": model_status,
        "deepseek_evaluation": "NOT RUN",
        "tests": tests,
        "steps": steps,
        "evaluation": summary,
    }
    (out / "acceptance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    (out / "acceptance.md").write_text(
        "# InsightFlow acceptance\n\n"
        + f"Engineering: {report['engineering']}\n\nMock evaluation: {model_status}\n\nDeepSeek: NOT RUN\n\n"
        + "实际测试条目（含参数化项），不把无测试文件当 SKIP。\n\n"
        + json.dumps(tests, ensure_ascii=False, indent=2)
        + "\n"
    )
    print(json.dumps(report, ensure_ascii=False))
    return 2 if not foundation else (0 if model_status == "PASS" else 1)


if __name__ == "__main__":
    raise SystemExit(main())

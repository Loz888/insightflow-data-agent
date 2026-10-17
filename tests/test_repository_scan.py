from pathlib import Path
import subprocess
import sys


def test_staged_secret_is_rejected_but_metric_decimal_is_not(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts/scan_secrets.py"
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    probe = tmp_path / "probe.txt"
    probe.write_text("DEEPSEEK_API_KEY=" + "sk-" + "A" * 32 + "\n")
    subprocess.run(["git", "add", "probe.txt"], cwd=tmp_path, check=True)
    result = subprocess.run(
        [sys.executable, str(script), "--mode", "staged", "--repo", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1 and "api_key" in result.stdout
    assert "sk-" + "A" * 32 not in result.stdout
    probe.write_text("duration_ms=21.14592734375\n")
    subprocess.run(["git", "add", "probe.txt"], cwd=tmp_path, check=True)
    assert (
        subprocess.run(
            [sys.executable, str(script), "--mode", "staged", "--repo", str(tmp_path)], capture_output=True
        ).returncode
        == 0
    )

"""Scan actual Git blobs, including reachable history, without printing matches."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
from dotenv import dotenv_values
from psycopg.conninfo import conninfo_to_dict

PATTERNS = {
    "api_key": r"\bsk-[A-Za-z0-9_-]{20,}",
    "github_token": r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})",
    "private_key": r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    "personal_path": r"/home/[A-Za-z0-9_.-]+/|DESKTOP-[A-Z0-9]{4,}|[A-Za-z]:[/\\]Users[/\\][^/\s\\]+",
    "phone": r"(?<![A-Za-z0-9.])1[3-9][0-9]{9}(?![A-Za-z0-9.])",
}
SAFE_EMAIL_DOMAINS = {"users.noreply.github.com", "example.invalid", "github.com"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("files", "staged", "head", "history"), default="head")
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args()
    root = Path(args.repo).resolve()

    def git(*params):
        return subprocess.check_output(["git", *params], cwd=root)

    known = []
    if (root / ".env").exists():
        for key, value in dotenv_values(root / ".env").items():
            if value and ("URL" in key or "KEY" in key or "TOKEN" in key or "PASSWORD" in key):
                known.append(value)
                if "AUTH_TOKENS" in key:
                    try:
                        known.extend(json.loads(value).keys())
                    except (ValueError, TypeError, AttributeError):
                        pass
                if "URL" in key:
                    try:
                        known.append(conninfo_to_dict(value).get("password", ""))
                    except Exception:
                        pass
    known += [os.environ.get("DEEPSEEK_API_KEY", "")]
    known = [v for v in known if len(v) >= 16]
    blobs = []
    if args.mode == "history":
        for item in git("rev-list", "--objects", "--all").decode().splitlines():
            sha, _, name = item.partition(" ")
            if git("cat-file", "-t", sha).strip() == b"blob":
                blobs.append((name, git("cat-file", "blob", sha)))
    elif args.mode == "files":
        for name in set(
            filter(
                None, git("ls-files", "--cached", "--others", "--exclude-standard", "-z").decode().split("\0")
            )
        ):
            blobs.append((name, (root / name).read_bytes()))
    else:
        names = (
            git(
                "ls-files" if args.mode == "staged" else "ls-tree",
                *([] if args.mode == "staged" else ["-r", "--name-only", "HEAD"]),
            )
            .decode()
            .splitlines()
        )
        for name in names:
            blobs.append((name, git("show", (":" if args.mode == "staged" else "HEAD:") + name)))
    findings = []
    for name, raw in blobs:
        text = raw.decode("utf-8", errors="replace")
        for category, pattern in PATTERNS.items():
            if re.search(pattern, text):
                findings.append({"file": name, "category": category})
        if any(v in text for v in known):
            findings.append({"file": name, "category": "known_local_secret"})
        for email in re.findall(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text):
            if email.rsplit("@", 1)[1] not in SAFE_EMAIL_DOMAINS:
                findings.append({"file": name, "category": "contact_email"})
        for match in re.finditer(r"postgres(?:ql)?://\S+:\S+@\S+", text):
            if name != ".github/workflows/ci.yml" or not re.search(
                r":ci-(?:admin|owner|reader)-only@", match[0]
            ):
                findings.append({"file": name, "category": "credential_uri"})
    if args.mode == "history":
        emails = git("log", "--all", "--format=%ae%n%ce").decode().splitlines()
        if any(not x.endswith("@users.noreply.github.com") for x in emails):
            findings.append({"file": "commit metadata", "category": "non_private_email"})
    print(f"Scanned {len(blobs)} {args.mode} blobs; findings={len(findings)}")
    for item in findings:
        print(item["file"] + ": " + item["category"])
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())

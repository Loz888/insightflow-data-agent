"""Generate private local Docker configuration; never print secrets."""

import json
import os
import secrets
from pathlib import Path

p = Path(".env.compose")
if p.exists():
    raise SystemExit("Existing .env.compose retained; edit locally if needed")
lines = []
for n in ("BOOTSTRAP", "OWNER", "READER", "RUNTIME"):
    lines.append("INSIGHTFLOW_" + n + "_PASSWORD=" + secrets.token_urlsafe(32))
lines.append("INSIGHTFLOW_V2_AUTH_TOKENS='" + json.dumps({secrets.token_urlsafe(32): "local-demo"}) + "'")
lines.extend(["INSIGHTFLOW_V2_MODE=mock", "INSIGHTFLOW_V2_LIVE_ENABLED=false", "DEEPSEEK_API_KEY="])
fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w") as f:
    f.write("\n".join(lines) + "\n")
print(
    "Private .env.compose created. Use local_token.py with --file .env.compose to view only demo bearer token."
)

"""Print only a local demo bearer token, never the model key. Run manually, do not log output."""

from dotenv import dotenv_values
import json

values = dotenv_values(".env")
tokens = json.loads(values.get("INSIGHTFLOW_V2_AUTH_TOKENS", "{}"))
if not tokens:
    raise SystemExit("Run isolated runtime setup first")
print(next(iter(tokens)))

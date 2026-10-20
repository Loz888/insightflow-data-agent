"""Loopback, synthetic benchmark harness. Never calls a paid provider."""

import asyncio
import os
import uvicorn
from insightflow.v2.api import create_app, load_settings
from insightflow.v2.mock import OfflineProvider


class FixedDelay(OfflineProvider):
    async def request(self, task, payload, schema, budget):
        if task == "action" and os.environ.get("PILOT_PAUSE_MARKER"):
            from pathlib import Path

            Path(os.environ["PILOT_PAUSE_MARKER"]).write_text("checkpoint reached before action")
            await asyncio.Event().wait()
        await asyncio.sleep(0.01)
        return await super().request(task, payload, schema, budget)


settings = load_settings()
if settings.mode != "mock" or settings.profile != "internal-pilot":
    raise SystemExit("Owned pilot Mock harness only")
app = create_app(settings, FixedDelay(settings.reference_time))
if __name__ == "__main__":
    uvicorn.run(
        app, host="127.0.0.1", port=int(os.environ["PILOT_HTTP_PORT"]), log_level="error", access_log=False
    )

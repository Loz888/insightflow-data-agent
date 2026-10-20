import asyncio
import os
from uuid import uuid4
import httpx
import psycopg
import pytest
from insightflow.v2.config import V2Settings
from insightflow.v2.identity import token_hash, Identity
from insightflow.v2.api import create_app
from insightflow.database.executor import ReadonlyExecutor
from insightflow.database.metadata import read_catalog
from insightflow.config import Settings

pytestmark = pytest.mark.integration


@pytest.fixture
def pilot():
    # Explicit separate opt-in: refuses silently using the developer's existing dev DB.
    if os.environ.get("INSIGHTFLOW_PILOT_OWNED_LAB") != "true":
        pytest.fail("Pilot integration requires its owned isolated lab; no SKIP")
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    params = conninfo_to_dict(os.environ["INSIGHTFLOW_V2_TEST_RUNTIME_URL"])
    params["dbname"] = "insightflow_dev"
    runtime = make_conninfo(**params)
    owner = os.environ["INSIGHTFLOW_ADMIN_DATABASE_URL"]
    reader = os.environ["INSIGHTFLOW_DATABASE_URL"]
    token_a = "synthetic-pilot-a-" + uuid4().hex
    token_b = "synthetic-pilot-b-" + uuid4().hex
    token_c = "synthetic-pilot-c-" + uuid4().hex
    with psycopg.connect(owner) as c:
        for token, principal, tenant in [
            (token_a, "alice", "a"),
            (token_b, "bob", "b"),
            (token_c, "carol", "a"),
        ]:
            c.execute(
                "INSERT INTO agent_runtime.api_tokens(token_hash,principal,tenant,datasource,expires_at) VALUES(%s,%s,%s,'business',clock_timestamp()+interval '1 hour')",
                (token_hash(token), principal, tenant),
            )
    cfg = V2Settings(
        profile="internal-pilot",
        pilot_tenants=["a", "b"],
        runtime_url=runtime,
        reader_url=reader,
        auth_tokens={},
        mode="mock",
    )
    yield cfg, token_a, token_b, token_c, owner, reader
    with psycopg.connect(owner) as c:
        c.execute(
            "DELETE FROM agent_runtime.api_tokens WHERE token_hash=ANY(%s)",
            ([token_hash(x) for x in [token_a, token_b, token_c]],),
        )


def test_pilot_rls_ownership_same_name_and_revocation(pilot):
    cfg, a, b, c, owner, reader = pilot

    async def run():
        app = create_app(cfg)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://fixture"
            ) as client:
                sid = uuid4().hex

                def headers(t):
                    return {"Authorization": "Bearer " + t}

                body = {"session_id": sid, "idempotency_key": uuid4().hex, "question": "客户数是多少？"}
                results = []
                for token in [a, b, c]:
                    res = await client.post("/v2/chat", headers=headers(token), json=body)
                    assert res.status_code == 200, res.text
                    row = res.json()
                    assert row["status"] == "succeeded", row
                    results.append(row)
                values = [int(x["result"]["evidence"]["rows"][0][0]) for x in results]
                assert values == [40, 60, 40]
                assert len({x["run_id"] for x in results}) == 3
                assert all(x["session_id"] == sid for x in results)
                rid = results[0]["run_id"]
                for token in [b, c]:
                    for suffix in ["", "/trace", "/events"]:
                        assert (
                            await client.get("/v2/runs/" + rid + suffix, headers=headers(token))
                        ).status_code == 404
                    assert (
                        await client.post("/v2/runs/" + rid + "/cancel", headers=headers(token))
                    ).status_code == 404
                for token in [b, c]:
                    assert (
                        await client.get("/v2/sessions/" + sid + "/export", headers=headers(token))
                    ).json()["session"]["version"] == 1
                    # Same external name is that user's own session, never Alice's result.
                    own = (await client.get("/v2/sessions/" + sid + "/export", headers=headers(token))).json()
                    assert all(str(x["run_id"]) != rid for x in own["runs"])
                unique = uuid4().hex
                private = {**body, "session_id": unique, "idempotency_key": uuid4().hex}
                deleted_run = (await client.post("/v2/chat", headers=headers(a), json=private)).json()[
                    "run_id"
                ]
                assert (await client.delete("/v2/sessions/" + unique, headers=headers(b))).status_code == 404
                assert (await client.delete("/v2/sessions/" + unique, headers=headers(a))).status_code == 200
                assert (await client.delete("/v2/sessions/" + unique, headers=headers(a))).status_code == 200
                assert (await client.get("/v2/runs/" + deleted_run, headers=headers(a))).status_code == 404
                assert (
                    await client.get("/v2/sessions/" + unique + "/export", headers=headers(a))
                ).status_code == 404
                assert (await client.get("/v2/schema", headers=headers(a))).status_code == 200
                oversized = await client.post("/v2/runs", headers=headers(a), content=b"x" * 17000)
                assert oversized.status_code == 413
                spoof = {**body, "tenant": "b", "datasource": "other", "principal": "bob"}
                assert (await client.post("/v2/runs", headers=headers(a), json=spoof)).status_code == 422
                replay = await client.post("/v2/chat", headers=headers(a), json=body)
                assert replay.json()["run_id"] == rid and replay.json()["replayed"]
                assert (
                    await client.post("/v2/chat", headers=headers(a), json={**body, "question": "订单数？"})
                ).status_code == 409
                # SQL, metrics and events do not expose the private token or another tenant's rows.
                events = (await client.get("/v2/runs/" + rid + "/events", headers=headers(a))).text
                assert a not in events and b not in events and "token_hash" not in events
                with psycopg.connect(owner) as conn:
                    conn.execute(
                        "UPDATE agent_runtime.api_tokens SET revoked_at=clock_timestamp() WHERE token_hash=%s",
                        (token_hash(a),),
                    )
                assert (await client.get("/v2/runs/" + rid, headers=headers(a))).status_code == 401

    asyncio.run(run())


def test_pilot_sql_context_reset_and_injection(pilot):
    cfg, a, b, c, owner, reader = pilot
    catalog = read_catalog(reader)
    executors = []
    try:
        for tenant, expected in [("a", 40), ("b", 60)]:
            ex = ReadonlyExecutor(Settings(database_url=reader, tenant_id=tenant, pool_size=1), catalog)
            executors.append(ex)
            for _ in range(3):
                assert ex.execute("SELECT COUNT(*) AS value FROM business.customers")["rows"] == [[expected]]
                with ex.pool.connection() as conn:
                    assert conn.execute("SELECT current_setting('insightflow.tenant_id',true)").fetchone()[
                        0
                    ] in (None, "")
                for sql in [
                    "SELECT set_config('insightflow.tenant_id','b',true)",
                    "SET ROLE insightflow_owner",
                    "SELECT * FROM agent_runtime.api_tokens",
                    "SELECT * FROM business.pilot_secret",
                ]:
                    with pytest.raises(Exception):
                        ex.execute(sql)
        # No trusted context means zero rows; role cannot disable RLS or become owner.
        with psycopg.connect(reader) as conn:
            assert conn.execute("SELECT count(*) FROM business.customers").fetchone() == (0,)
            assert conn.execute(
                "SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"
            ).fetchone() == (False, False)
            with pytest.raises(psycopg.Error):
                conn.execute("SET ROLE insightflow_owner")
    finally:
        for ex in executors:
            ex.close()


def test_scope_unambiguous():
    assert Identity("c", "a:b", "business").scope != Identity("b:c", "a", "business").scope


def _gate_worker(dsn, rid, tenant, url, start, queue):
    import urllib.request
    from insightflow.v2.store import Store
    from insightflow.v2.errors import Fault

    store = Store(dsn)
    try:
        start.wait(20)
        try:
            permit = store.acquire_model_permit("synthetic-test", "flash", tenant, rid, 2, 1, 60)
        except Fault as exc:
            queue.put({"status": exc.code})
            return
        # Actual local HTTP receipt, not just a semaphore counter in this process.
        request = urllib.request.Request(url, headers={"X-Test-Tenant": tenant})
        with urllib.request.urlopen(request, timeout=10) as response:
            response.read()
        # Simulate response/usage uncertainty. Remote receipt does not free admission immediately.
        store.finish_model_permit(permit, False)
        queue.put({"status": "received_unknown", "permit": permit})
    finally:
        store.close()


def test_global_gate_multiple_processes_and_uncertain_hold(pilot):
    import multiprocessing
    import threading
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from insightflow.v2.store import Store
    from insightflow.v2.contracts import ChatInput
    from insightflow.v2.errors import Fault

    cfg, a, b, c, owner, reader = pilot
    store = Store(cfg.runtime_url.get_secret_value(), namespace_sessions=True)
    row, _ = store.enqueue(
        "gate-fixture-" + uuid4().hex,
        ChatInput(session_id=uuid4().hex, question="controlled fake provider", idempotency_key=uuid4().hex),
        30,
        60,
    )
    counts = {"active": 0, "peak": 0, "received": 0}
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            with lock:
                counts["active"] += 1
                counts["received"] += 1
                counts["peak"] = max(counts["peak"], counts["active"])
            time.sleep(0.25)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"unknown usage")
            with lock:
                counts["active"] -= 1

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    ctx = multiprocessing.get_context("spawn")
    start = ctx.Event()
    queue = ctx.Queue()
    workers = []
    try:
        for i in range(8):
            process = ctx.Process(
                target=_gate_worker,
                args=(
                    cfg.runtime_url.get_secret_value(),
                    str(row["run_id"]),
                    "a" if i % 2 == 0 else "b",
                    f"http://127.0.0.1:{server.server_port}",
                    start,
                    queue,
                ),
            )
            process.start()
            workers.append(process)
        start.set()
        results = [queue.get(timeout=30) for _ in workers]
        for process in workers:
            process.join(10)
            assert process.exitcode == 0
        assert counts["received"] == 2 and counts["peak"] <= 2
        assert sum(x["status"] == "received_unknown" for x in results) == 2
        assert sum(x["status"] == "GLOBAL_MODEL_BUSY" for x in results) == 6
        with store.pool.connection() as connection:
            held = connection.execute(
                "SELECT outcome,extract(epoch FROM held_until-clock_timestamp()) AS remaining FROM agent_runtime.model_permits WHERE run_id=%s",
                (row["run_id"],),
            ).fetchall()
        assert len(held) == 2 and all(x["outcome"] == "uncertain" and x["remaining"] > 30 for x in held)
        with pytest.raises(Fault, match="GLOBAL_MODEL_BUSY"):
            store.acquire_model_permit("synthetic-test", "flash", "a", str(row["run_id"]), 2, 1, 60)
    finally:
        for process in workers:
            if process.is_alive():
                process.terminate()
                process.join(5)
        server.shutdown()
        server.server_close()
        thread.join(5)
        with store.pool.connection() as connection:
            connection.execute("DELETE FROM agent_runtime.model_permits WHERE run_id=%s", (row["run_id"],))
        store.close()

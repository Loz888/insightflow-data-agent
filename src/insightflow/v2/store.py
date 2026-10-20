"""Short transactions only. Session leases fence completion across processes.
Queued work has durable ordering; process-lost work is marked interrupted, never auto-billed again.
"""

import hashlib
import json
from uuid import uuid4, UUID
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool
from insightflow.v2.errors import Fault

TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}


class Store:
    def __init__(self, dsn, limit=4, namespace_sessions=False):
        self.namespace_sessions = namespace_sessions
        self.pool = ConnectionPool(
            dsn,
            min_size=0,
            max_size=limit,
            timeout=2,
            kwargs={
                "autocommit": True,
                "connect_timeout": 3,
                "row_factory": dict_row,
                "options": "-c search_path=pg_catalog,agent_runtime -c statement_timeout=2500 -c lock_timeout=1500",
            },
            open=True,
        )
        self.pool.wait(timeout=5)
        with self.pool.connection() as c:
            row = c.execute(
                "SELECT current_user AS name,rolsuper,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=current_user"
            ).fetchone()
            if row["name"] != "insightflow_runtime" or any(
                row[n] for n in ("rolsuper", "rolcreatedb", "rolcreaterole")
            ):
                self.pool.close()
                raise ValueError("Runtime requires dedicated restricted role")

    def _event(self, c, rid, stage, payload=None):
        # Callers supply allowlisted structural summaries; never prompts, keys or raw rows.
        c.execute(
            "INSERT INTO agent_runtime.events(run_id,stage,payload) VALUES (%s,%s,%s)",
            (rid, stage, Jsonb(payload or {})),
        )

    def _sid(self, sid, principal):
        if not self.namespace_sessions:
            return sid
        return "p-" + hashlib.sha256(json.dumps([principal, sid]).encode()).hexdigest()

    def enqueue(self, principal, body, seconds, ttl):
        sid = self._sid(body.session_id, principal)
        rid = str(uuid4())
        digest = hashlib.sha256(
            json.dumps({"session": body.session_id, "question": body.question}, sort_keys=True).encode()
        ).hexdigest()
        with self.pool.connection() as c, c.transaction():
            c.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                (principal + ":" + body.idempotency_key,),
            )
            c.execute(
                "UPDATE agent_runtime.runs SET idempotency_key=NULL WHERE principal=%s AND idempotency_key=%s AND expires_at<clock_timestamp() AND status IN ('succeeded','failed','cancelled','interrupted')",
                (principal, body.idempotency_key),
            )
            old = c.execute(
                "SELECT * FROM agent_runtime.runs WHERE principal=%s AND idempotency_key=%s",
                (principal, body.idempotency_key),
            ).fetchone()
            if old:
                if old["request_hash"] != digest:
                    raise Fault("IDEMPOTENCY_CONFLICT", "幂等键对应不同请求内容。")
                old["session_id"] = body.session_id
                return old, False
            c.execute(
                "INSERT INTO agent_runtime.sessions(session_id,principal,public_session_id) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                (sid, principal, body.session_id),
            )
            session = c.execute(
                "SELECT principal,deleted_at FROM agent_runtime.sessions WHERE session_id=%s FOR UPDATE",
                (sid,),
            ).fetchone()
            if session["principal"] != principal or session["deleted_at"] is not None:
                raise Fault("NOT_FOUND", "会话不可访问。")
            row = c.execute(
                "INSERT INTO agent_runtime.runs(run_id,principal,session_id,idempotency_key,request_hash,question,status,deadline,expires_at) VALUES (%s,%s,%s,%s,%s,%s,'queued',clock_timestamp()+(%s*interval '1 second'),clock_timestamp()+(%s*interval '1 second')) RETURNING *",
                (rid, principal, sid, body.idempotency_key, digest, body.question, seconds, ttl),
            ).fetchone()
            self._event(c, rid, "queued")
            row["session_id"] = body.session_id
            return row, True

    def get(self, rid, principal):
        with self.pool.connection() as c:
            row = c.execute(
                "SELECT r.*,COALESCE(s.public_session_id,r.session_id) AS session_id FROM agent_runtime.runs r JOIN agent_runtime.sessions s ON s.session_id=r.session_id WHERE r.run_id=%s AND r.principal=%s AND s.deleted_at IS NULL",
                (rid, principal),
            ).fetchone()
            if not row:
                raise Fault("NOT_FOUND", "运行不可访问。")
            return row

    def session(self, sid, principal):
        with self.pool.connection() as c:
            row = c.execute(
                "SELECT session_id,principal,version,constraints,history FROM agent_runtime.sessions WHERE session_id=%s AND principal=%s AND deleted_at IS NULL",
                (self._sid(sid, principal), principal),
            ).fetchone()
            if not row:
                raise Fault("NOT_FOUND", "会话不可访问。")
            row["session_id"] = sid
            return row

    def claim(self, rid, principal, owner, lease):
        with self.pool.connection() as c, c.transaction():
            run = c.execute(
                "SELECT * FROM agent_runtime.runs WHERE run_id=%s AND principal=%s", (rid, principal)
            ).fetchone()
            if not run:
                raise Fault("NOT_FOUND")
            session = c.execute(
                "SELECT * FROM agent_runtime.sessions WHERE session_id=%s FOR UPDATE", (run["session_id"],)
            ).fetchone()
            if session["deleted_at"] is not None:
                raise Fault("NOT_FOUND")
            if run["status"] != "queued":
                return None
            if (
                session["lease_until"]
                and session["lease_until"]
                > c.execute("SELECT clock_timestamp() AS server_now").fetchone()["server_now"]
            ):
                return None
            if session["active_run"]:
                lost = str(session["active_run"])
                c.execute(
                    "UPDATE agent_runtime.runs SET status='interrupted',error_code='LEASE_EXPIRED',finished_at=clock_timestamp() WHERE run_id=%s AND status='running'",
                    (lost,),
                )
                self._event(c, lost, "interrupted", {"code": "LEASE_EXPIRED"})
            first = c.execute(
                "SELECT run_id FROM agent_runtime.runs WHERE session_id=%s AND status='queued' ORDER BY sequence LIMIT 1",
                (run["session_id"],),
            ).fetchone()
            if not first or str(first["run_id"]) != str(rid):
                return None
            c.execute(
                "UPDATE agent_runtime.sessions SET active_run=%s,lease_owner=%s,lease_until=clock_timestamp()+(%s*interval '1 second') WHERE session_id=%s",
                (rid, owner, lease, run["session_id"]),
            )
            c.execute(
                "UPDATE agent_runtime.runs SET status='running',started_at=clock_timestamp() WHERE run_id=%s",
                (rid,),
            )
            self._event(c, rid, "running", {"base_version": session["version"]})
            return session

    def heartbeat(self, rid, owner, lease):
        with self.pool.connection() as c, c.transaction():
            row = c.execute(
                "UPDATE agent_runtime.sessions SET lease_until=clock_timestamp()+(%s*interval '1 second') WHERE active_run=%s AND lease_owner=%s AND lease_until>clock_timestamp() RETURNING session_id",
                (lease, rid, owner),
            ).fetchone()
            run = c.execute(
                "SELECT cancel_requested,status FROM agent_runtime.runs WHERE run_id=%s", (rid,)
            ).fetchone()
            if not row or not run or run["status"] != "running":
                raise Fault("LEASE_LOST")
            return run["cancel_requested"]

    def cancel(self, rid, principal):
        with self.pool.connection() as c, c.transaction():
            row = c.execute(
                "SELECT status FROM agent_runtime.runs WHERE run_id=%s AND principal=%s FOR UPDATE",
                (rid, principal),
            ).fetchone()
            if not row:
                raise Fault("NOT_FOUND")
            if row["status"] == "queued":
                c.execute(
                    "UPDATE agent_runtime.runs SET status='cancelled',cancel_requested=true,error_code='CANCELLED',finished_at=clock_timestamp() WHERE run_id=%s",
                    (rid,),
                )
                self._event(c, rid, "cancelled")
            elif row["status"] == "running":
                c.execute("UPDATE agent_runtime.runs SET cancel_requested=true WHERE run_id=%s", (rid,))
            return row["status"]

    def complete(self, rid, principal, owner, status, result=None, plan=None, base_version=None, error=None):
        if status not in TERMINAL:
            raise ValueError("invalid final state")
        with self.pool.connection() as c, c.transaction():
            run = c.execute(
                "SELECT * FROM agent_runtime.runs WHERE run_id=%s AND principal=%s", (rid, principal)
            ).fetchone()
            if not run:
                raise Fault("NOT_FOUND")
            session = c.execute(
                "SELECT * FROM agent_runtime.sessions WHERE session_id=%s FOR UPDATE", (run["session_id"],)
            ).fetchone()
            # Session row lock always precedes run lock, matching claim/heartbeat.
            run = c.execute("SELECT * FROM agent_runtime.runs WHERE run_id=%s FOR UPDATE", (rid,)).fetchone()
            if run["status"] in TERMINAL:
                return False
            if run["status"] == "running":
                if (
                    str(session["active_run"]) != str(rid)
                    or str(session["lease_owner"]) != str(UUID(str(owner)))
                    or session["lease_until"]
                    <= c.execute("SELECT clock_timestamp() AS server_now").fetchone()["server_now"]
                ):
                    raise Fault("LEASE_LOST", "旧进程无法提交新会话事实。")
            if run["cancel_requested"]:
                status = "cancelled"
                result = None
                plan = None
                error = "CANCELLED"
            if (
                run["deadline"]
                <= c.execute("SELECT clock_timestamp() AS server_now").fetchone()["server_now"]
                and status == "succeeded"
            ):
                status = "failed"
                result = None
                plan = None
                error = "DEADLINE"
            if status == "succeeded" and plan is not None:
                if session["version"] != base_version:
                    raise Fault("VERSION_CONFLICT")
                history = [
                    *session["history"],
                    {"metric": plan["metric"], "windows": plan["windows"], "evidence_run": str(rid)},
                ][-4:]
                c.execute(
                    "UPDATE agent_runtime.sessions SET constraints=%s,history=%s,version=version+1,updated_at=clock_timestamp() WHERE session_id=%s",
                    (Jsonb(plan), Jsonb(history), run["session_id"]),
                )
            c.execute(
                "UPDATE agent_runtime.runs SET status=%s,result=%s,error_code=%s,finished_at=clock_timestamp() WHERE run_id=%s",
                (status, Jsonb(result) if result is not None else None, error, rid),
            )
            c.execute(
                "UPDATE agent_runtime.sessions SET active_run=NULL,lease_owner=NULL,lease_until=NULL WHERE active_run=%s AND lease_owner=%s",
                (rid, owner),
            )
            self._event(c, rid, status, {"code": error} if error else {})
            return True

    def event(self, rid, stage, payload=None):
        with self.pool.connection() as c:
            self._event(c, rid, stage, payload)

    def events(self, rid, principal, after=0):
        self.get(rid, principal)
        with self.pool.connection() as c:
            return c.execute(
                "SELECT event_id,stage,payload,at FROM agent_runtime.events WHERE run_id=%s AND event_id>%s ORDER BY event_id LIMIT 100",
                (rid, after),
            ).fetchall()

    def recover(self):
        # Startup/reaper handles expired owners and orphan queued requests; no automatic model replay.
        with self.pool.connection() as c, c.transaction():
            sessions = c.execute(
                "SELECT * FROM agent_runtime.sessions WHERE active_run IS NOT NULL AND lease_until<clock_timestamp() FOR UPDATE SKIP LOCKED"
            ).fetchall()
            for s in sessions:
                rid = s["active_run"]
                c.execute(
                    "UPDATE agent_runtime.runs SET status='interrupted',error_code='PROCESS_LOST',finished_at=clock_timestamp() WHERE run_id=%s AND status='running'",
                    (rid,),
                )
                self._event(c, rid, "interrupted", {"code": "PROCESS_LOST"})
                c.execute(
                    "UPDATE agent_runtime.sessions SET active_run=NULL,lease_owner=NULL,lease_until=NULL WHERE session_id=%s",
                    (s["session_id"],),
                )
            rows = c.execute(
                "UPDATE agent_runtime.runs SET status='interrupted',error_code='QUEUE_ORPHANED',finished_at=clock_timestamp() WHERE status='queued' AND deadline<clock_timestamp() RETURNING run_id"
            ).fetchall()
            for row in rows:
                self._event(c, row["run_id"], "interrupted", {"code": "QUEUE_ORPHANED"})

    def reserve(self, experiment, budget, max_attempts, rid, amount, input_rate=None, output_rate=None):
        attempt = str(uuid4())
        with self.pool.connection() as c, c.transaction():
            c.execute(
                "INSERT INTO agent_runtime.experiments(experiment_id,budget) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                (experiment, budget),
            )
            c.execute(
                "UPDATE agent_runtime.experiments SET budget=LEAST(budget,%s) WHERE experiment_id=%s",
                (budget, experiment),
            )
            row = c.execute(
                "UPDATE agent_runtime.experiments SET reserved=reserved+%s,attempts=attempts+1 WHERE experiment_id=%s AND reserved+%s<=budget AND attempts<%s RETURNING reserved",
                (amount, experiment, amount, max_attempts),
            ).fetchone()
            if not row:
                raise Fault("EXPERIMENT_BUDGET", "共享实验预算已耗尽，停止新付费请求。")
            c.execute(
                "INSERT INTO agent_runtime.model_attempts(attempt_id,run_id,experiment_id,reservation,input_rate,output_rate) VALUES (%s,%s,%s,%s,%s,%s)",
                (attempt, rid, experiment, amount, input_rate or "0.30", output_rate or "1.20"),
            )
        return attempt

    def settle(self, attempt, outcome, usage=None):
        from decimal import Decimal

        with self.pool.connection() as c, c.transaction():
            row = c.execute(
                "SELECT * FROM agent_runtime.model_attempts WHERE attempt_id=%s FOR UPDATE", (attempt,)
            ).fetchone()
            if not row or row["usage_known"]:
                return
            charged = None
            if usage is not None:
                charged = (
                    Decimal(usage[0]) * row["input_rate"] + Decimal(usage[1]) * row["output_rate"]
                ) / Decimal(1000000)
                if charged > row["reservation"]:
                    # Unexpected usage cannot silently create fresh budget.
                    c.execute(
                        "UPDATE agent_runtime.experiments SET reserved=budget WHERE experiment_id=%s",
                        (row["experiment_id"],),
                    )
                    usage = None
                    charged = None
                    outcome = "USAGE_BOUND_VIOLATION"
                else:
                    c.execute(
                        "UPDATE agent_runtime.experiments SET reserved=reserved-%s WHERE experiment_id=%s",
                        (row["reservation"] - charged, row["experiment_id"]),
                    )
            c.execute(
                "UPDATE agent_runtime.model_attempts SET outcome=%s,usage_known=%s,input_tokens=%s,output_tokens=%s,charged=%s WHERE attempt_id=%s",
                (
                    outcome,
                    usage is not None,
                    usage[0] if usage else None,
                    usage[1] if usage else None,
                    charged,
                    attempt,
                ),
            )

    def budget(self, experiment):
        with self.pool.connection() as c:
            row = c.execute(
                "SELECT * FROM agent_runtime.experiments WHERE experiment_id=%s", (experiment,)
            ).fetchone()
            return row

    def export_session(self, sid, principal):
        session = self.session(sid, principal)
        with self.pool.connection() as c:
            rows = c.execute(
                "SELECT run_id,status,result,error_code,created_at,finished_at FROM agent_runtime.runs WHERE principal=%s AND session_id=%s ORDER BY sequence DESC LIMIT 100",
                (principal, self._sid(sid, principal)),
            ).fetchall()
            return {"session": session, "runs": rows, "limit": 100, "order": "newest first"}

    def delete_session(self, sid, principal):
        internal = self._sid(sid, principal)
        with self.pool.connection() as c, c.transaction():
            row = c.execute(
                "SELECT * FROM agent_runtime.sessions WHERE session_id=%s AND principal=%s FOR UPDATE",
                (internal, principal),
            ).fetchone()
            if not row:
                raise Fault("NOT_FOUND")
            if row["deleted_at"] is not None:
                return True
            if c.execute(
                "SELECT 1 FROM agent_runtime.runs WHERE session_id=%s AND status IN ('queued','running') LIMIT 1",
                (internal,),
            ).fetchone():
                raise Fault("SESSION_BUSY")
            threads = [
                x["thread_id"]
                for x in c.execute(
                    "SELECT t.thread_id FROM agent_runtime.graph_threads t JOIN agent_runtime.runs r USING(run_id) WHERE r.session_id=%s AND r.principal=%s",
                    (internal, principal),
                ).fetchall()
            ]
            # Fixed table names only. Identity/tombstone and checkpoint deletion share one transaction.
            for table in ["checkpoint_writes", "checkpoint_blobs", "checkpoints"]:
                c.execute("DELETE FROM agent_checkpoints." + table + " WHERE thread_id=ANY(%s)", (threads,))
            c.execute(
                "UPDATE agent_runtime.runs SET question='',result=NULL WHERE session_id=%s AND principal=%s",
                (internal, principal),
            )
            c.execute(
                "UPDATE agent_runtime.events SET payload='{}'::jsonb WHERE run_id IN (SELECT run_id FROM agent_runtime.runs WHERE session_id=%s AND principal=%s)",
                (internal, principal),
            )
            c.execute(
                "UPDATE agent_runtime.sessions SET history='[]'::jsonb,constraints='{}'::jsonb,deleted_at=clock_timestamp() WHERE session_id=%s",
                (internal,),
            )
            c.execute(
                "INSERT INTO agent_runtime.lifecycle_audit(principal,session_digest,action) VALUES(%s,%s,'delete_sensitive_session_state')",
                (principal, hashlib.sha256(sid.encode()).hexdigest()),
            )
            return True

    def acquire_model_permit(self, provider, model, tenant, rid, global_limit, tenant_limit, hold_seconds):
        permit = str(uuid4())
        with self.pool.connection() as c, c.transaction():
            c.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                ("model-gate:" + provider + ":" + model,),
            )
            row = c.execute(
                "SELECT count(*) AS total,count(*) FILTER(WHERE tenant=%s) AS own FROM agent_runtime.model_permits WHERE provider=%s AND model=%s AND held_until>clock_timestamp()",
                (tenant, provider, model),
            ).fetchone()
            if row["total"] >= global_limit or row["own"] >= tenant_limit:
                raise Fault("GLOBAL_MODEL_BUSY", retryable=True)
            c.execute(
                "INSERT INTO agent_runtime.model_permits(permit_id,provider,model,tenant,run_id,held_until) VALUES(%s,%s,%s,%s,%s,clock_timestamp()+(%s*interval '1 second'))",
                (permit, provider, model, tenant, rid, hold_seconds),
            )
            return permit

    def finish_model_permit(self, permit, confirmed):
        with self.pool.connection() as c:
            if confirmed:
                c.execute(
                    "UPDATE agent_runtime.model_permits SET held_until=clock_timestamp(),outcome='confirmed_return' WHERE permit_id=%s AND outcome='uncertain'",
                    (permit,),
                )
            # Unconfirmed requests keep the full timeout + uncertainty period, not just local TTL.

    def assert_owner(self, rid, owner):
        with self.pool.connection() as c:
            ok = c.execute(
                "SELECT EXISTS(SELECT 1 FROM agent_runtime.sessions s JOIN agent_runtime.runs r ON r.run_id=s.active_run WHERE r.run_id=%s AND s.lease_owner=%s AND s.lease_until>clock_timestamp() AND s.deleted_at IS NULL AND r.status='running' AND NOT r.cancel_requested AND r.deadline>clock_timestamp()) AS ok",
                (rid, owner),
            ).fetchone()["ok"]
            if not ok:
                raise Fault("LEASE_LOST")

    def thread(self, rid, principal, base_version):
        tid = "pilot-v1-" + hashlib.sha256(json.dumps([principal, str(rid)]).encode()).hexdigest()
        with self.pool.connection() as c, c.transaction():
            c.execute(
                "INSERT INTO agent_runtime.graph_threads(run_id,principal,thread_id,workflow_version,base_version) VALUES(%s,%s,%s,'pilot-graph-v1',%s) ON CONFLICT DO NOTHING",
                (rid, principal, tid, base_version),
            )
            row = c.execute(
                "SELECT * FROM agent_runtime.graph_threads WHERE run_id=%s AND principal=%s", (rid, principal)
            ).fetchone()
            if not row or row["workflow_version"] != "pilot-graph-v1" or row["base_version"] != base_version:
                raise Fault("VERSION_CONFLICT")
            return row["thread_id"]

    def resume(self, rid, principal, seconds):
        with self.pool.connection() as c, c.transaction():
            initial = c.execute(
                "SELECT session_id FROM agent_runtime.runs WHERE run_id=%s AND principal=%s", (rid, principal)
            ).fetchone()
            if not initial:
                raise Fault("NOT_FOUND")
            session = c.execute(
                "SELECT deleted_at FROM agent_runtime.sessions WHERE session_id=%s AND principal=%s FOR UPDATE",
                (initial["session_id"], principal),
            ).fetchone()
            if not session or session["deleted_at"] is not None:
                raise Fault("NOT_FOUND")
            run = c.execute(
                "SELECT * FROM agent_runtime.runs WHERE run_id=%s AND principal=%s FOR UPDATE",
                (rid, principal),
            ).fetchone()
            if not run:
                raise Fault("NOT_FOUND")
            if run["status"] != "interrupted":
                if run["status"] in ("queued", "running", "succeeded"):
                    return None
                raise Fault("RESUME_DENIED")
            if run["cancel_requested"] or run["resume_count"] >= 2:
                raise Fault("RESUME_DENIED")
            if c.execute(
                "SELECT 1 FROM agent_runtime.model_attempts WHERE run_id=%s LIMIT 1", (rid,)
            ).fetchone():
                raise Fault("RESUME_UNCERTAIN")
            row = c.execute(
                "UPDATE agent_runtime.runs SET status='queued',error_code=NULL,finished_at=NULL,resume_count=resume_count+1,deadline=clock_timestamp()+(%s*interval '1 second') WHERE run_id=%s RETURNING *",
                (seconds, rid),
            ).fetchone()
            self._event(c, rid, "resume_requested", {"count": row["resume_count"]})
            return row

    def close(self):
        self.pool.close()

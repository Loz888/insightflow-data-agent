"""Pilot identity is server-owned. Only SHA-256 of high-entropy bearer tokens is stored.
No positive cache: revocation/expiry is checked on every request.
"""

import hashlib
import json
from dataclasses import dataclass
from insightflow.v2.errors import Fault


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True)
class Identity:
    principal: str
    tenant: str
    datasource: str

    @property
    def scope(self):
        # Ambiguous concatenation cannot merge identities. Legacy principals do not match.
        return "pilot:" + token_hash(json.dumps([self.tenant, self.principal], separators=(",", ":")))


def authenticate(store, token, registered_tenants):
    if not 24 <= len(token) <= 512:
        raise Fault("UNAUTHENTICATED")
    with store.pool.connection() as c:
        row = c.execute(
            "SELECT principal,tenant,datasource FROM agent_runtime.api_tokens WHERE token_hash=%s AND revoked_at IS NULL AND expires_at>clock_timestamp()",
            (token_hash(token),),
        ).fetchone()
    if not row or row["tenant"] not in registered_tenants or row["datasource"] != "business":
        raise Fault("UNAUTHENTICATED")
    return Identity(**row)

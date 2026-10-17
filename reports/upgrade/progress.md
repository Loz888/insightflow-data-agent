# Upgrade progress
- Baseline:138/138; original Ground Truth hash unchanged.
- V2.0 first offline:82/82, full original data + 2 separate Seed snapshots.
- First real Flash Max run:25/30 E2E; 4 protocol failures + 1 reject/clarify mismatch retained.
- Protocol field errors now get bounded schema-only feedback, invalid tool names fail closed.
- V2.1 adds5 queries, relevant shipping table +4 distractors, duplicate-event fan-out control, zero/NULL cases.
- Retrieval quality:full/rules/lexical all recall1.0; precision .18/1.0/.5667. Default chooses rules, lexical remains experimental; no invented retrieval improvement.
- Original schema FK assertion now explicitly scopes original5 tables (still exactly4); new assertion checks exactly8 across extended schema. No business answer changed.
- Docker engine absent; fresh local PG+venv validation in progress. No push/deploy.

## Final checkpoint — 2026-10-17
Code c2ed574 accepted in a NEW cluster/venv:325 PASS/0FAIL/0SKIP,148unit+177integration.
Original30=30/30 unchanged; V2offline87/87; realMax27/30; targeted8/9; finalHTTP4/4.
Paired n2: selected/full2/2, context2/2vs0/2, feedback2/2vs0/2. Remaining failures retained.
Shared budget0.4856967USD accounted /2USD;468/500 attempts, no reset. Paid work stopped.
Docker blocked; V2remoteCI and independent human sign-off not run. No push/public deployment.

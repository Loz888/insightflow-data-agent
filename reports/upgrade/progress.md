# Upgrade progress
- Baseline:138/138; original Ground Truth hash unchanged.
- V2.0 first offline:82/82, full original data + 2 separate Seed snapshots.
- First real Flash Max run:25/30 E2E; 4 protocol failures + 1 reject/clarify mismatch retained.
- Protocol field errors now get bounded schema-only feedback, invalid tool names fail closed.
- V2.1 adds5 queries, relevant shipping table +4 distractors, duplicate-event fan-out control, zero/NULL cases.
- Retrieval quality:full/rules/lexical all recall1.0; precision .18/1.0/.5667. Default chooses rules, lexical remains experimental; no invented retrieval improvement.
- Original schema FK assertion now explicitly scopes original5 tables (still exactly4); new assertion checks exactly8 across extended schema. No business answer changed.
- Docker engine absent; fresh local PG+venv validation in progress. No push/deploy.

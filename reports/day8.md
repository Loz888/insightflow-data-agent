# Day8 · 实际执行 2026-10-17（计划 10-27）
## Completed Tasks
四实验模式、同安全后端、独立 Recall@5 标注、120 条真实观测与失败保留。
完善 FK/同名字段/未授权表噪声/术语同义词测试；
权威 Context 与历史隔离，覆盖继承、覆盖、指标切换、增长、失败历史和模糊指代。
## Modified Files
config、agent/nodes/service、retrieval/retriever/glossary、llm/mock、
evaluation/ablation、evaldata/retrieval_labels 与 ablation/*、专项测试和两份消融说明。
## Commands Executed
scripts/accept.sh；python -m insightflow.evaluation.ablation --output evaldata/ablation。
## Test Results
106 PASS / 0 FAIL / 0 SKIP / 0 ERROR。
完整 Mock 30/30；四模式共 120 次，真实保留 10 个追问失败。
Baseline/RetrievalOnly 各 25/30；ContextOnly/Full 各 30/30。
Recall@5 分别 0.344444、
0.833333、
0.411111、1.000000。
## Known Issues
Mock 不读 Schema 文本，不能用这组实验判断真实 LLM 的 RAG 收益。
Context 大小为估算；Recall 包含理解失败，不能独立解释为检索器精准率。
## Unverified Claims
真实模型消融 NOT_RUN。没有预设 Full 必须优于其他模式；未改变原 Ground Truth。

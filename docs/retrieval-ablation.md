# Retrieval 消融
模式：Baseline 固定最小 orders Schema、无历史；RetrievalOnly 动态检索、无历史；
ContextOnly 固定相同 orders Schema、有历史；Full 检索与历史均开启。
所有模式共用相同 Validator、reader、只读事务、计划/超时/输出限制和两次 SQL 修正预算。

30 个同问题、同数据、同 Mock 版本、同 Prompt 基础模板。
独立相关表标注由开发者维护 ReferenceSQL 的物理表引用抽取并审查，
保存在 evaldata/retrieval_labels.json，包含原数据哈希；未使用 Agent 输出构造标签。
原 questions.relevant_tables 有较宽泛业务关联，不用于制造更高召回，也未改写。
K=5；实际选择少于 K 时按真实选择计算。Recall@5 每案为召回相关表数/标注相关表数，
再对 30 案例平均；理解失败无选择记 0，因此该口径同时受到 Context 成功与否影响。
同时报告平均选择表数，不能仅因选择更多表就宣称更准确。

- baseline: Recall@5=0.344444, 结果正确率=0.833333, 平均选择表数=0.833。
- retrieval_only: Recall@5=0.833333, 结果正确率=0.833333, 平均选择表数=1.567。
- context_only: Recall@5=0.411111, 结果正确率=1.000000, 平均选择表数=1.000。
- full: Recall@5=1.000000, 结果正确率=1.000000, 平均选择表数=2.000。

Mock 的 SQL 规则不使用 Schema 文本，所以检索开启没有提高相同 Context 条件下的 SQL 正确率。
这既不能证明 RAG 无用，也不能证明真实 LLM 得到提升。
Full 与 ContextOnly 均 30/30，Baseline 与 RetrievalOnly 均 25/30；
差异来自五个追问失去结构化历史，不是检索造成的 LLM 能力变化。
实际 120 条观测、10 个失败、耗时与上下文估算见 evaldata/ablation/。
真实模型消融 NOT_RUN。

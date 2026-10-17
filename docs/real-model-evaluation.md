# 真实模型评测
当前状态 **REAL_MODEL_EVALUATION = NOT_RUN**。没有 API 付费请求，不能提供真实正确率、
Token、成本或延迟。已实现可运行流程和本地 HTTP 模拟验收。

12 个代表案例由 evaldata/real_model/cases.json 引用原始 30 案例与 SHA-256：
基础过滤、聚合、JOIN、时间、退款和多轮。原参考 SQL/答案不改动。
Prompt 版本 insightflow-v2-202610；当前默认 deepseek-flash，
可配置官方 Chat API 列出的 deepseek-v4-pro；实际在线可用性本次未验证。
官方文档：https://api-docs.deepseek.com/api/create-chat-completion/ 。

真实入口：
python -m insightflow.evaluation.real_model --output <新的独立输出目录>
需要用户自己显式设置 INSIGHTFLOW_ENABLE_PAID_EVAL=1 和 INSIGHTFLOW_ENABLE_LIVE=true，
以及 Key、测试库、保守价格、MaxModelCalls/输出 Token/超时/费用预留预算。
程序不设置授权开关。未授权/无 Key 只输出 NOT_RUN，不调用 SDK 网络。

一个 Provider 的 HTTP 尝试总数涵盖理解、SQL 生成、所有案例和网络重试；
SDK 内置重试关闭，429/网络/5xx 最多两次可配置退避重试，仍受同一总调用预算。
SQL 修正预算与 API 重试分开，模型错误不会再进入 SQL 无限重试。
默认 3 次 HTTP、1024 输出 Token、15 秒；上限 100 次、4096 Token、30 秒，
保守费用预留默认 0.05 USD，上限 1 USD。必须使用正确的模型价格上界；
这不是精确计费封顶，未知 Usage 不当成零成本。

分类 MODEL_AUTH_ERROR、MODEL_RATE_LIMIT、MODEL_TIMEOUT、MODEL_UPSTREAM_ERROR、
MODEL_INVALID_RESPONSE、MODEL_OUTPUT_TRUNCATED、MODEL_BUDGET_EXHAUSTED。
使用 SDK 异常类型与 status_code/finish_reason，拒绝空 JSON、额外字段和截断内容。
只有返回可信非负且总和一致的 Usage 才统计 prompt/completion/total Token；
任一尝试用量不明时整个聚合保持 unknown。

失败记录额外包含八类 failure_category、节点轨迹、业务口径与约束差异，
不暴露 Key、数据库密码或原始上游异常。Mock 与真实目录隔离。
报告会分别显示 SQL/结果/证据/整场景表现；小样本不能推广为真实企业 BI 能力。

# Day7 · 实际执行 2026-10-17（计划 10-26）
## Completed Tasks
复用现有 Provider，增加严格付费门控、七类 SDK 错误、finish_reason/空响应校验、
可信 prompt/completion/total Usage、有限退避、每实验共享 HTTP 硬预算。
SQL 重试不再重复重试已经耗尽 API 内部重试的模型错误。
12 案例真实模式入口与八类失败证据已实现。
## Modified Files
llm/deepseek.py、database/errors.py、agent/nodes/service、
evaluation/runner/failure/real_model、模型测试、门控脚本与真实模式说明/案例引用。
## Commands Executed
ruff format/check；scripts/accept.sh（含完整 pytest/compileall/pip check/Demo/30 案例）；
显式移除付费开关后运行 real_model 入口。
## Test Results
95 PASS / 0 FAIL / 0 SKIP / 0 ERROR。
HTTP Mock 验证 401/403/429/503、超时、空/坏/额外字段 JSON、截断、
重试次数、调用预算、请求前费用预留、未知/已知 Usage。
30 案例 Mock 通过；原 30 Ground Truth 字节哈希未改变。
## Real Model
REAL_MODEL_EVALUATION = NOT_RUN。未设置付费授权，未发送真实 API。
evaldata/real_model 的空 runs 和 NOT_RUN 汇总如实保存，不虚构准确率/Token/延迟。
## Known Issues
费用控制是保守预留和请求/Token 硬限制，非精确计费限额。
仅当前官方模型配置值通过本地参数检查，在线可用性本次未测试。
## Unverified Claims
不宣称真实模型能力、费用或生产性能。

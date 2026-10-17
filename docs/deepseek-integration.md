# DeepSeek 接入核实与真实证据

核实日期：2026-10-17。直接读取官方文档及带本地凭据的GET /models，未公开凭据。

| 事项 | 本次选择 |
| --- | --- |
| 官方接口 | https://api.deepseek.com，Chat Completions |
| 请求模型 | deepseek-flash；官方当前映射 DeepSeek-V4.1-Flash-1017 |
| 用户指定模式 | thinking.type=enabled，reasoning_effort=max |
| 输出上限 | 默认8192，受请求/项目预算约束；不使用供应商的大默认值 |
| 输入 | 结构化计划、授权Schema与口径、脱敏工具反馈 |
| 输出协议 | JSON object + Pydantic；这是结构化action，不是原生Function Calling |
| 客户端 | 可复用异步httpx客户端，TLS验证开启，禁止重定向，端点不接受用户参数 |

官方来源：[价格与模型](https://api-docs.deepseek.com/quick_start/pricing/)、
[Chat Completion](https://api-docs.deepseek.com/api/create-chat-completion/)、
[Thinking](https://api-docs.deepseek.com/guides/thinking_mode/)、
[工具调用](https://api-docs.deepseek.com/guides/tool_calls/)、
[JSON](https://api-docs.deepseek.com/guides/json_mode/)。
官方支持JSON、工具及流式；strict工具模式是beta端点能力，本实现没有宣称使用它。
流式协议支持有本地模拟测试，真实付费主评测使用非流式JSON；SSE是应用阶段事件。
只读取最终content；reasoning_content被丢弃，不存储或展示私有思维链。
供应商模型名是别名，不是不可变快照锁；请求与当日官方映射均有记录。

## 预算与Usage
本轮只有一个费用作用域：专用测试运行库 + upgrade-v2-20261017。
所有Live迭代、成对实验、HTTP和后续本地演示共享2USD及500次HTTP尝试上限。
不允许换阶段、数据库或experiment_id重新取得本轮额度；管理员配置是信任边界。
本机.env已设置同一测试控制库、DeepSeek Flash和Max；代码/CI默认仍是Mock。
每个请求独立限制模型尝试12、工具10、SQL修正2、图26步、总时长180秒，
不是Provider服务几个请求后就用尽的三次生命周期预算。

按核实的Flash峰值/cache-miss输入0.30 USD/M、输出1.20 USD/M做保守计价。
请求前以完整UTF-8字节上界+协议余量估算输入，连同输出上限在持久账本中原子预留。
这不是模型Tokenizer，也不是实测Usage。只有合法非负且总量一致的实测Usage才能结算释放多余预留。
缺失Usage、连接中断或取消后的未知消费保留整笔预留，不能当零。
缓存折扣、非高峰价格不用于放宽预留；本地账本不等于供应商实际账单绝对硬封顶。

## 错误与生命周期
401/403不重试；429/5xx/传输超时/中断有限重试，退避带抖动；统一共享尝试次数、Token和deadline。
SDK自动重试不存在。坏JSON/字段错误只有一次有界结构反馈；非法工具名终止，不能以重试绕过权限。
空响应、截断、坏字段、流未完整结束均不执行未验证SQL。配置使用Pydantic/显式异常，python -O不可绕过。
配置异常隐藏输入内容，Key从本地受忽略0600配置读取，不要求发到聊天。

## 真实运行记录
- live-smoke-001/002：早期非thinking协议失败，完整保留，不算Max能力证据。
- live-smoke-003-max：真实Max查询成功，且自然出现工具前置条件错误后的恢复。
- live-max-001：30场景25成功，4协议失败+1澄清/拒绝偏差。
- live-max-002：同组30场景27成功，原问题和评分未改。
- live-max-regression-001：9项8成功，零分母退款率的一种SQL写法仍被保守契约拒绝。
- live-http-002-final：最后源码快照的真实HTTP四场景；源码SHA见summary。
- live-paired-001：两样本/臂的真实成对实验。
所有路径在 evaldata/upgrade；摘要及最终费用见 UPGRADE_ACCEPTANCE。

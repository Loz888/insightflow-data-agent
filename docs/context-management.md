# 上下文与记忆
- Graph State：单次 LangGraph invoke 的问题、计划、检索结果、SQL、执行证据和失败/重试。
- Conversation History：同 Session 最近至多 4 次成功回答；较旧工具输出先删除。
- Context Window：发送给 SQL 生成 Provider 的结构化上下文；预算默认估算 6000 Token。
  使用 ceil(UTF-8 字节数/3) 标为估算，没有调用模型 tokenizer，不能描述成准确 Token。
- 关键约束：指标、UTC 月份、地区、CNY 币种单独保存，与非权威历史分开；
  裁剪不能删关键约束或指标定义，预算容不下则 BUDGET_EXHAUSTED。
- Retrieval Index：真实允许表/列/类型/FK 与人工业务术语，按关键词、字段和所需指标排序、
  选择，再闭合 JOIN 关系；只注入必要表，不把完整库 Schema 冒充检索。
- Long-term Memory：未实现。无跨 Session 学习或长期保存。

显式 SessionStore 在单个进程内保存，TTL 30 分钟，最多 128 Session。
同进程调用用锁串行化，避免同会话覆盖；多进程/重启不恢复，也不提供认证或租户隔离。
不同 Session 的约束与历史不会混入彼此 Prompt；错误回答不写入会话。
“那华东地区呢”继承月份与指标；新月份或地区覆盖旧值；
“全部地区”清除地区，“所有月份”清除月份。无法可靠解释的指标或指代请求澄清。

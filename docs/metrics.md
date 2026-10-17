# 业务指标与时间口径
参考时点固定为 2026-10-01 00:00:00 UTC。全部订单时间按 UTC，金额币种为 CNY，NUMERIC/Decimal。
日期区间左闭右开；“9月”指 2026-09-01 至 2026-10-01。相对时间仅按该参考时点解析。

- GMV：所有非 cancelled 订单的明细 quantity×unit_price 总额，包含 pending。
- Paid Revenue：status=paid 的订单原始销售金额，尚未扣退款。
- Refund Amount：该订单批次产生的 status=succeeded 退款金额，以订单 ordered_at 归属期统计，退款时间不决定分母月份。
- Order Count：指定范围的订单数；“已支付订单数”额外要求 paid。
- Refunded Order Rate：有正数成功退款的已支付订单数 / 已支付订单数。
- Refund Amount Rate：成功退款金额 / 同批次已支付订单销售金额。
- Average Order Value：已支付销售金额 / 已支付订单数。
- 净收入如需计算：Paid Revenue−Refund Amount；不是默认 Paid Revenue。
- 分母为零返回 NULL（证据不足），不编造零百分比。

订单有多条明细和多次退款；先分别按 order_id 聚合后再连接，或用相关子查询。
禁止直接把明细与原始退款多对多连接后求和。
商品类/商品排名按已支付明细销售金额；退款指标不支持商品类别归因（退款无商品粒度），请求澄清。

“上月”为 2026-09，“本月”为 2026-10，不使用机器当前日期。日级区间、季度、其他年份、美元与净收入尚不支持，明确请求澄清。

多月份区间与跨月比较本版不支持；明确请求澄清，不能只取第一个月。此边界已有回归测试。

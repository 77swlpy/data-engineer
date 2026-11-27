# Pipeline 设计说明（A 方案 · 批量精简版）

范围：score≤3 且正文非空，共 14,445 条。主键用 source_row_id（原始行号），不用 review_id——它重复 789 组、1,603 行，重复组内 order_id 不同，按它去重会丢 814 行。缓存只复用结果，原文按行回填，不删记录。

Prompt 用 A 方案原文直抽，写入七类定义和四条边界；batch=20、temperature=0、关闭思考、max_tokens=2500。三个决定各有明确收益：关闭思考让 reasoning tokens 从 39 降到 0；Prompt 从 5,581 字符压到约 1,100，固定开销被 20 条摊薄；单条 token 从 1,355 降到 161.6。

校验结构、类别、范围、证据逐字匹配和同类重复，不合格进 failed，不混入成功；每批落盘，checkpoint 支持续跑。132 条实测 F1 0.9579，属 in-sample。全量未运行；推算 723 次请求、233 万 tokens、约 6 分钟。
# 准确率评估报告（DeepSeek 真实 API，冻结 Prompt A-compact）

## 1. 执行事实
- 模型 deepseek-flash，batch=20，thinking disabled，max_tokens=2500。
- 132 条人工标注各跑一次（7 次请求），132 条返回；其中 130 条通过证据校验，2 条证据引文不匹配。
- 未对 14,445 条全量运行。

## 2. 指标（仅 130 条通过校验的样本）
| 指标 | 数值 |
|---|---|
| 完全类别集合一致 | 119 / 130 = 91.54% |
| micro precision | 0.9737 |
| micro recall | 0.9427 |
| micro F1 | 0.9579 |

分类别（TP/FP/FN）：
delivery_late 33/0/0；missing_item 27/0/0；quality_defect 32/1/4；
wrong_product 26/2/0；seller_communication 19/1/4；packaging 9/0/0；other 2/0/1。

## 3. 失败与偏倚
- 失败 2 条：模型改写引文导致 evidence 不匹配，已从指标中剔除，未静默计入成功。
- 最大短板仍是 seller_communication 的召回；quality_defect 漏在"使用痕迹/轻微瑕疵"。
- **in-sample 警告**：A-compact 的边界规则源自这 132 条标注，随后又在同批上评测，指标偏乐观，不能当作泛化准确率；对外应另抽 200-300 条未见样本复测。

## 4. 与前两版对照
| 配置 | tokens/条 | micro F1 | 有效/请求 |
|---|---|---|---|
| 完整 Prompt 逐条 | 1,355 | 0.9533 | 127/132 |
| 完整 Prompt batch10 | 659 | 未评 | 20/20 |
| 精简 Prompt batch20 + 关思考 | 161.6 | 0.9587 | 130/132 |

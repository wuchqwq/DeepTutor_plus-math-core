# ack-only 的实际根因与最小待决策方案

本结论来自已保存的实际 state、selector 请求/响应及 publication 回执；没有新增模型调用。逐条原始 ID 与回执见 [root_cause_chain.json](root_cause_chain.json)，其输入均在450文件证据包内。

| 实际运行 | canonical 状态 | 送给 selector 的 offer | 实际选择与最终正文 |
|---|---|---|---|
| v2 S1 | aligned；matched=artifact_fb25443eaa34f31dc6d60c08；validated=[] | 12个，全部 orientation，全部文本为 ack | grant_ids=[]；accepted正文为 ack |
| v2 S4 | 原 source identity matched=artifact_9a49636c63aee4fba96c5985；另一个真实 validated artifact=artifact_f04c36d8514bb94865b96fae | 7个，全部 orientation，全部文本为 ack | grant_ids=[]；accepted正文为 ack |
| v3 S8 五轮 | aligned A → aligned B → unresolved → unresolved → aligned B；真实方法 confirmation resolved | 每轮分别12/3/7/7/7个，全部 orientation，全部文本为 ack | 每轮 grant_ids=[]；五条最终正文全部 ack |

这里没有 grant ID 选择错误、越界选择或 renderer 意外吞掉 result。selector 返回空选择符合协议；就算选上已有 orientation，renderer 仍只会输出同一句 ack。因此仅修改 selector 提示词、强制它选 IDs 或增加 fallback，无法解决教学缺口。

三个责任环节分别是：

1. **数学内容支持尚未形成。** 原 reviewed source 只有 qualified/not_checkable。literal 对齐证明了学生字符串与 source 一致，不能证明该公式真伪。真实原生复用检查能够验证平方恒等式；条件化 Q 公式则返回 not_checkable。S4 的真实新增 verified artifact 与已匹配的原 source artifact 不是同一个 ref，不能把一个 artifact 的证据转移给另一个。
2. **现有 capability 没有适用的数学教学 grant。** `capability.py:176` 的 verified 子集要求 applicable、matched、verification_status=verified 同时成立；本轮不满足。随后只构造 orientation，并从支持绑定中只取 result。`support.py` 注册的 operation 支持仅为一元有理线性变形，真实 probe 对本题平方表达式返回 outside_bounded_rational_linear_scope。expand/substitute 等已有工具执行成功本身不等于已经有可信的 chosen_operation 支持绑定。
3. **宿主教学 owner 没有在本路线输出教学动作。** `generate_response` 只让模型选择 authority_basis/grant_ids；禁止它生成文字、proof、new acts。`accept_response` 只渲染固定 ack 与 canonical result literals。普通 DeepTutor 的教学模型没有被用作 Math route 的表达 owner。如此设计安全地限制数学发布，但不会自动变成提示、追问或纠错。

能在既有权限内完成的局部接线是：用现有核验器真实返回的 artifact/ToolEvidence 建立可审阅的新 source revision，只为已核验且适用、匹配的具体 identity 走现有 result renderer；不能手写 verified 或扩张核验 scope。这样能让 S4 的具体公式进入回应，却仍不足以处理 S1/S2/S3/S5/S6/S7/S8 的数学教学动作。当前 source 和首轮结果没有被改变。

**需要 Owner 的一项决策：是否批准仅对本题的有限数学操作增加发布支持。** 最小拟议修改由现有 Math Core owner 在 `support.py` 为现有展开/代入工具的真实证据绑定 exact content、premise refs、revision、chosen_operation/operation_options；由现有 host renderer 消费这些已有 act kind，再由既有 teaching/presentation owner 决定提示顺序及固定表达。该修改涉及现有 authority/publication 的支持语义，尚未实施，必须等待决定。

主要风险是把“操作相对前提等价”当成“前提为真”或“完整证明”；另有过早披露风险。应保持逐 relation 的证据和披露 ceiling，未核验可达性继续 unknown，用户索要答案不能覆盖权限。没有提议自然语言完备验证、自由文本回退、新 Guard/Manager/runtime 层、StudentState/RAG/几何、换题或新架构阶段。

本轮已 STOP。draft PR #18 只交付实验接线、真实失败、教学比较与本根因，不实现该权限扩展，不合并。Actions 针对当前 draft HEAD 的 PR-triggered run 查询返回空列表；没有观察到 quota failure，也不填写 NOT_RUN_QUOTA。

# Phase D 首轮真实教学实验：STOP，教学未通过

本轮保留了全部未经教学优化的实际输出。普通 DeepTutor 能给提示和纠错，但存在明确数学错误；Math Core 集成版完成了真实 Provider、canonical alignment、方法确认和受保护 publication，却始终只给学生 acknowledgement。不能据此宣称教学改善或学习效果提升。

完整逐轮教师正文、调用量、回执与复测失败见 [first_round.json](first_round.json)。完整事件、实际 SDK/HTTP 参数、SQLite 导出、截图和日志保存在本任务 `data/phase-d-evidence/`，交付归档及逐文件哈希见 [evidence_manifest.json](evidence_manifest.json)。没有把 runtime home、Catalog 或任何凭据放入归档。

## 执行与公平性

- 实际执行环境：Windows LAPTOP-PIC477JQ；独立 checkout `DeepTutor_phase_d`，分支 `experiment/phase-d-first-round`。原 `F:\demo2\DeepTutor_plus-math-core` 未改动。产品基线 dev `143e41784bdd2c34d765a50c754869ef3a2d9830`。
- 原样首轮 OFF 对照 `thinking-off-v2`：执行 SHA `9f8ace7d837f80772aacc2c8174fd3331ad2e114`，同一个题目、初始学生信息、冻结学生输入、默认 UI language=en，独立 session/home/SQLite/episode。没有换掉失败样本。
- 真实模型是用户标准 Catalog 中的 `deepseek-flash`。所有实际 HTTP 请求固定 temperature=0、top_p=1、thinking.type=disabled、reasoning_effort=none；记录实际 response model、UTC 与 system_fingerprint。这是滚动模型名称，不能证明不可变模型快照。两版可用请求上限相同：S1–S7 每 case 20，S8 每 case 40。每次输出上限 4096；alignment 2048，selector 1024，原生后台调用使用更小的既有上限。
- 集成版额外获得公开声明的完整 AI-reviewed source，包括解题轨迹及答案；原始 source 为 15 qualified、1 not_checkable、0 verified。普通版只有题面、学生信息及原生宿主工具上下文。因此比较的是增加数学信息后的整体方案，不能把差异单独归于编排。评审专用 `grader_notes.md` 没有作为模型输入或 resolver 输入。
- 普通版保留原生工具、memory 和后台调用；首次无历史数据，S8 后续的本 session memory/上下文属于实际运行。调用、token 与额外数学上下文完整记录，没有以相同调用数冒充相同资源。
- 用户亲自配置本任务标准 Catalog；进程 DI 复用该标准 service，未复制 key 或凭据文件。付费及 localhost 独立无界面 Chromium 均已获得用户授权。没有操控现有浏览器、桌面或其他 Agent 应用。

DeepSeek 的 OFF 和 JSON mode 使用实际请求参数，依据 [Chat Completion API](https://api-docs.deepseek.com/api/create-chat-completion) 与 [thinking mode SDK 文档](https://api-docs.deepseek.com/zh-cn/guides/thinking_mode/)。宿主静态 capability flag 把 JSON mode 与 strict JSON schema 混在一起，原 factory 删除了 response_format；实验适配器用 SDK extra_body 传入 json_object，实际 HTTP 已验证。没有静默补全坏 JSON。

## 逐场景三维比较（原样 v2）

所有场景题目均为：实数 x,y 满足 x²+xy+y²=3，求 Q=x²−xy+y² 的范围。学生输入及多轮规则完整保存在 [protocol.json](../protocol.json)。评审正确范围为 [1,9]。

| 场景 | 数学判断和不确定性 | 教学动作和披露 | 表达与下一步 |
|---|---|---|---|
| S1 正确中间步骤 | 普通版正确认可 Q=3−2xy，但把 x²+y²≥2|xy| 与 (x−y)²≥0 错称为等价。集成版内部 literal match 为 aligned，未向学生提供判断。 | 普通版给求 xy 范围的提示，未直接给最终区间。集成版只有 ack。 | 普通版有下一步但给两条路线、用英文回应中文输入。集成版学生不知道下一步。 |
| S2 运算错误 | 普通版开头说“你的这一步是对的”，后面正确指出 +2xy 应为 −2xy，判断矛盾。集成版为 unresolved，未确认或否定数学真伪。 | 普通版定位符号并给下一步；集成版未纠错、未披露。 | 普通版的首句会误导学生；集成版无可执行动作。 |
| S3 概念错误 | 普通版正确区分实数乘积与平方，用 x=2,y=−1 反例。后续仅从 y² 范围直接代入 Q 的提示不足以完成目标。集成版保守 unresolved。 | 普通版给配方提示；集成版未解释 xy 可为负。 | 普通版有行动但指导缺口，并混入无关 embedding 配置通知；集成版无行动。 |
| S4 合法不同解法 | 普通版正确展开平方恒等式。集成版匹配 B 路径，并实际由原生 SymPy claim check 验证了新增候选 identity；这不等于原 reviewed artifacts 获得 verified。 | 普通版接受 B 后，提示却又引入 s,d 对称变量，偏离“不强迫换方法”的意图。集成版没有可见认可或提示。 | 普通版有目标“求 (x−y)² 上界”，但换路线且附带配置通知；集成版仍只有 ack。 |
| S5 小提示请求 | 普通版给出的两个平方非负不等式正确。集成版为 no_math_claim，未凭空将提问当作正确步骤。 | 普通版提示代入 3−xy 后分别解不等式，没有给完整 Q 区间。集成版未给提示。 | 普通版行动明确，英文且提示偏多；集成版不可执行。 |
| S6 明确索要答案 | 普通版先得 −3≤xy≤1，随后把 3−2×1 算成 −3，错误结论 [-3,9]，还错误声称 x=y=1 可达 Q=−3。集成版没有越权给出未经授权答案，也没有解释限制。 | 普通版响应答案意图但答案错误。集成版答案请求没有覆盖 math authority，实际仍 ack。 | 普通版自信、冗长地解释错误结论；集成版未满足请求或提供安全的下一步。 |
| S7 含糊表述澄清 | 普通首轮说 probably 并依据同页题面合理推断猜测，以反例解释 Q 不恒为3；不因未追问自动判失败。集成首轮 no_math_claim，澄清后仍未给数学判断。 | 普通第二轮被宿主 start_turn_rejected，未进入 Provider，不能评价其第二轮教师回应；集成两轮均 completed，但只有 ack。 | 普通首轮可执行但冗长、检查空 workspace 并附配置通知；集成版没有可见澄清或行动。 |
| S8 连续出错后修正 | 普通版连续纠正 2 和 1/3 为 2/3，最后认可正确式；部分错误原因描述不准，还把教师先前给出的 2/3 当作学生已提出的系数。集成 v2 首轮 evidence 含中文导致 A 未匹配，最后连写 >=0 也未匹配，没有实际方法确认。 | 普通版给太多中间推导和重复提示，最后有求上界及可达性的动作。集成 v2 五轮 ack，无纠错和下一步。 | 普通版能继续但长、英文且带推测性批评；集成版无法支持学生继续。 |

## 局部接线复测：保留失败，不替代首轮

| 记录 | 实际结果 | 归因与限制 |
|---|---|---|
| 原 non-OFF S1 两版 | 普通 completed；集成 alignment JSON 截断。 | 集成 completion2048 中 reasoning2024，finish_reason=length；json.loads 失败，尚未 selector/basis/receipt 校验。`math_publication_rejected` 是宿主统一异常标签，不能据此称发布校验失败。旧普通主 loop 两次调用未捕获 wire，但持久化实际 usage 可见；旧轮不能当作 OFF 对照。 |
| OFF v1 集成 S1，8fb99aa5 | 实际 OFF+json_object；完整 JSON 返回但 schema 拒绝。 | occurrence 和 uncertainty 被模型输出为字符串。保留原始提案，补全适配器字段类型说明。 |
| OFF v3 集成 S8，34104a9f | 五个实际 turn 全 completed；真实 Method 2 卡、opaque token 选择及 resolved confirmation；刷新后五个原始 ack 可见。 | 通用提案截取示例让 s=x+y 和最终等式准确匹配。A→B 由原生 Core 确认；两个错误系数仍为 unresolved。所有教师回应仍是 ack，教学 E2E 不 PASS。 |
| OFF v3 普通 S7，34104a9f | 首轮 completed；session API 已返回 active_turns=[]，第二轮仍被宿主拒绝。 | 局部浏览器同步没有解决宿主 admission/recovery 时序；不重发失败 submission，不启动新的运行管理抽象。 |
| OFF v3 集成 S7，34104a9f | 首轮 failed。 | 真实提案同时含 question 和 claims，原生 schema 拒绝。未修补模型输出，未回退普通聊天。 |

首轮 v2：26 次真实浏览器提交、25 个持久化 turn；84 次 SDK 请求和84次实际 HTTP 请求；已观察 usage 共244448 tokens。局部接线复测额外24次 HTTP：v1 S1两次，v3 S8十五次，v3 S7两版七次。全部 OFF 记录合计108次 HTTP，已观察 usage303714 tokens。部分失败后后台请求未观察到 response/usage，费用和 token 未知，不能按0计。旧 non-OFF 探索约8次实际推理请求另列，其中两次普通主 loop 只有持久化 usage 证据。调用增长来自原生工具循环、后台提示/标题、alignment/selector，以及明确保留的接线复测，不是增加样本。

## 必须停住的精确边界

`deeptutor/capabilities/math_turn/output.py:48` 只允许 orientation/result renderer；`:51` 的 result 必须满足 exact verified grounding；`:135` 输出固定 ack 加 canonical result literals。`capability.py` 只给 applicable refs 的 orientation，以及已匹配且独立 verified refs 的 result。当前 source 的 qualified 状态、literal matching 和模型信心不能升级为真理权限；S4 的新增 verified artifact 也不能直接给未匹配的原 source artifact 授权。

因此需要 dot/Owner 决定如何在**现有** Math Core support/grant 边界内提供可发布的 chosen_operation/justification/operation_options 等内容，再由既有 DeepTutor teaching/presentation owner 表达。最小决策是明确可信支持来源、允许的 act/content 关系和 disclosure ceiling。这里没有修改 authority、扩大 orientation 成数学提示、将 qualified 改成 verified，或让自由模型文本绕过 accept_response。对当前 renderer 塞入任意提示将改变 publication 语义，必须 STOP。普通版的纠错首句、错误自检、提示节奏和无关配置通知可由既有 teaching/presentation owner 局部处理，但本轮未提前优化它们。

进一步完成了零 Provider 调用的 [现有机制复用检查](existing_support_probe.json)：`validate_artifact` 对原平方恒等式返回真实 verified/ToolEvidence；对 Q=3−2xy 及 Q−1=(2/3)(x−y)² 返回 asymmetric_free_symbols/not_checkable；`validate_transformation` 对平方表达式返回 outside_bounded_rational_linear_scope。原 source 没有修改，检查结果没有注入任何学生 runtime。

已有 `MathToolAdapter` 可以执行 expand/substitute/check_equivalence；但 `support.py` 没有将这些工具证据注册为 chosen_operation/operation_options 支持，只注册了 exact literal result 和 rational_linear_transform_v1。已有 host renderer 也明确拒绝非 orientation/result act。因此“做一次 SymPy 检查”本身不能授权任意纠错或教学措辞，更不能把有限展开证明当成完整可达性证明。

**唯一待决策项：是否批准本题的有限数学发布支持扩展。** 最小方案是复用现有展开/代入工具的实际证据，在现有 Core support resolver 内绑定 exact 内容、前提 refs、workspace revision 和 allowed act；由既有 host renderer 消费这些 chosen_operation/operation_options，并由 teaching/presentation owner 选择提示顺序和披露上限。可先把真实已核验恒等式按现有 result 路径接通，但这只覆盖局部公式，不足以完成8个教学场景。风险是将操作等价证据误当作数学前提真伪、完整证明或全量披露权限。必须保持逐关系支持、未知可达性和用户索要答案不能越权。此方案尚未实现；不增加 Guard/Manager、runtime 层、自然语言完备验证、StudentState/RAG/几何或新架构阶段。

## 执行证据与验收

- ACTUAL_EXECUTED：标准 Catalog DI 的两版真实容器 start/close；实际数学 draft 检查；全部 v2 浏览器尝试；v3 的真实 S8 方法确认/轨迹/刷新；v1/v3失败；SDK和实际 HTTP参数；SQLite/publication content digest；Node/Python语法检查。
- 实际浏览器为 Chromium153.0.8010.12，Playwright1.57.0；使用本机已有 headless shell1243，与依赖预期构建不同。匹配构建安装失败单列，未冒充安装成功。首次未授权沙箱 spawn EPERM 的失败单列；用户后来只授权此 localhost headless 范围。
- 历史父任务只读审阅属于 AGENT_REPORT_ONLY；本报告的执行结论来自当前工件，不把审阅推断算作执行。
- NOT_RUN：数学权限变更、教学优化与复评、桌面/现有浏览器接管。GitHub Actions 没有执行，本轮未验证其额度，不能虚填 NOT_RUN_QUOTA。
- 没有观察到 math 失败后普通聊天 fallback；受保护 publication 回执保留。runtime 接线可以工作，但所需“可执行教学回应而非 acknowledgement”未满足，最终验收为 **FAIL / STOP_AUTHORITY_DECISION**。

下一步由 dot 独立审阅并向既有 owner 下发局部任务。不得以本轮8样本宣称学习效果显著提高。工件只提交独立 draft PR，不合并。

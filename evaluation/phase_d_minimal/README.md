# Phase D 最小真实教学实验：准备交接

状态：**DRAFT / NOT FROZEN / REAL RUN NOT STARTED**。本轮只完成无需凭据的准备，尚无逐场景教学输出。
目标是网页学生提交→宿主持久化→原生 Core 轨迹/数学依据→宿主教学表达→真实模型→授权发布→学生继续。
首轮保留现有行为；不先优化 teaching/presentation，不新增 Guard、Manager、Gate、StudentState、RAG 或几何。

## 已核验本地事实

- 主机 `LAPTOP-PIC477JQ`，Windows 本地 PowerShell；未使用云容器。
- 原仓库 `F:\demo2\DeepTutor_plus-math-core`：origin 为 `https://github.com/wuchqwq/DeepTutor_plus-math-core.git`；干净，原 HEAD `4b9b08283db3d315b128ea19ad8ec4a89ae69405`。
- 独立 clone `C:\Users\13471\Documents\Codex\2026-10-09\task-2\DeepTutor_phase_d`，branch `experiment/phase-d-first-round`。
- 实时 fetch / ls-remote：dev 精确为 `143e41784bdd2c34d765a50c754869ef3a2d9830`，log 确认 PR #17 merge；原工作区未改。
- 已读产品 AGENTS、`DT_POC_FINAL_CLOSEOUT.md`、`DT_UPSTREAM_V1_6_14_INTEGRATION.md`、native capability/extraction 合同。
- 已读 `F:\demo2\tutor_demo\AGENTS.md`、roadmap 工作区的扩展 AGENTS，以及 V2；数学 oracle runtime pin `76d5d9697186d086fb967e79a9e08e394b0d5474`，planning pin `a2a1905dc41eed3e5a574304993c2747dcb0838c`。
- 特别核对：本地 roadmap 工作区 HEAD `9c572e71f4d48a70c2ced49f382a4ea27e3c764b` 的 V2 与 pinned 文本不同，不能当作同一冻结文件。已另经 `git show a2a1905...:docs/design/DEEPTUTOR_MATH_MIGRATION_ROADMAP_V2.md` 阅读 frozen 版本（Phase D 在 8.2），SHA-256 `6b52026f17752de559f6e3352d13e42825d49a12b25293b58ce2c87e2055beaf`；当前扩展 V2 的 3.1/4/7.4/7.9/8 仅作补充参考。
- 所查目标仓库和相关 roadmap/tutor_demo 工作区没有 `.agents/skills`；未广泛扫描个人文件。tutor_demo 只读参考，不导入其 runtime。
- 工具：Git、Python 3.13.2、Node v24.16.0、npm 11.13.0；rg/gh 未在 PATH，常见 GitHub CLI 安装路径亦无 gh。
- 全局 Python 有 SymPy/pytest/FastAPI/Pydantic/httpx/openai；无 tiktoken/mcp/litellm。已有 integration venv 存在但缺 SymPy，未把它计为完整运行环境。
- CUA 工具说明明确禁用 native desktop；未调用或操控其他 Agent 应用。

## 8 场景与两版可见信息

具体题面、每条实际学生输入、接话与方法卡规则在 [protocol.json](protocol.json)。S1–S6 单轮，S7 两轮，S8 五个数学提交及实际方法确认。
两版同一题面、初始学生信息与意图；首轮至少 13 个数学提交/版，真实追问增加的输入逐字保存，不伪造等长对话。
S8 作为正式首轮浏览器样本，两版独立上下文，避免为截图再挑一条成功样本。

| arm | 首轮保留的路径 | 模型可见信息 |
| --- | --- | --- |
| ordinary | 同 dev 的原 `chat`，Math 路由关闭 | 题面、相同学生原文及该 session 历史；无评审答案、人工解题路径、Math 轨迹或 grants |
| integrated | 显式注入原 `MathTurnCapability`，原 publication 原样 | 提案模型看到 accepted 原文与 reviewed 数学 artifact/path projection；选择模型看到 accepted 原文与 Core-authorized offers/basis |

集成版若获得 reviewed 解题材料而普通版没有，此首轮是**信息增强整体方案对照**，不把收益单独归因于编排。
人工审定 source 是明确列出的运行资源，须记录逐字段投影与哈希；`grader_notes.md` 始终仅供评审，不送进 prompt/resolver。
不要用 oracle 的 CA02 名称、hardcoded revision 或修改 verification flag 为真实任务授予 authority。
现有 CA02 fixture 证明题型覆盖，其 artifacts 主要为 qualified，另有 not_checkable；不能升级为 verified。
独立 home、SQLite、session、episode 和历史，无 journal/memory/mastery/RAG/外部 tools；无法关闭的宿主工具或标题调用如实记录。

## 模型设置和小规模预算建议

优先使用你自行安全配置的标准 provider 路径中的可钉住模型快照；不得读取聊天 key，也不由执行任务复制/注入持续凭据。
若该路径支持 OpenAI，候选 `gpt-4.1-2025-04-14`（非滚动别名），两版与提案/选择/标题均同快照；当前只是建议，未验证账号可访问。
建议 temperature=0、top_p=1、文本输入、无额外 reasoning 设置；同 provider/API 格式/服务档位、单 worker。记录实际 wire 参数，不能只记预期设置。
使用既有 scoped LLM config，generation 当前 selector 固定 max_tokens=1024；alignment 建议 2048，ordinary 每轮输出总预算不超过 4096。
对不同管线记录阶段上限差异，并为每版每学生 turn 给相同聚合资源预算；不通过改 prompt 或放宽 grants 造公平性。
13 个数学提交：ordinary 至少 13 次教学调用，可能再有最多 8 次标题调用；integrated 预计 13 次 alignment + 13 次 selector。
因此预计约 39–47 次 API 调用；方法卡回复/刷新回放不应调用新模型。额外 tool loop、重试与失败都计入。
建议整轮最多 60 次请求、单请求输入 16k/output 4096 上限、单次网络故障至多 1 次重试；模型格式或数学失败不修复后替换首轮结果。
按平均 5k input/1k output、47 次计算约 US$0.85；保守 60×16k input/4096 output 约 US$3.93。建议操作预算 US$5，非你新设的费用硬限制。
上述是 OpenAI 标准价估算（input US$2/M、output US$8/M，2026-10-09 查阅），网关价格不同需替换估算；不假定缓存折扣。
来源：[官方模型快照与价格](https://developers.openai.com/api/docs/models/gpt-4.1)。费用授权已收到，范围为本次对照与必要 E2E，不无限重试或扩展调用。

## 已观察到的接线缺口与最小方案

1. `math_turn` 不在 builtin/default routing；真实 proposal provider 与 reviewed episode resolver 没有默认产品组合。
   最小做法是 evaluation-only 启动脚本调用现有 catalog factory/TurnEngine accepted-route callback，复用现有 SQLite+MemoryCoordinator、host accepted row 与 protected mutation。
   提案适配器仅把 native projection 送到已有 provider factory，再按 `AlignmentProposal` 原 schema 返回；不导入 tests、离线 provider 或旧 tutor_demo。
   必须先确定明确的实验 reviewed source、固定本地实验 learner/question scope 和注册范围；不把源 fixture 自动变成授权源。不新增全局 registry、另一 store 或接受生命周期。
2. 当前 `output.generate_response` 只让真实模型选择 grant_ids；`accept_response` 只输出 acknowledgement 加确切授权 literals。
   这是源码确认的表达限制，尚未做真实教学观测。保持原样完成首轮；如果实际只是 acknowledgement，记录教学失败，不能以链路通畅宣称 Phase D PASS。
   “自由生成 Tutor 回应然后直接发布”会触及现有 authority/publication，**不在本次准备中实施**；后续由 dot 基于真实缺口下发既有 teaching/presentation owner 的局部任务。
3. Playwright 配置存在，但既有 critical-turns audit 依赖 deterministic fixture，不能当真实 Math E2E。
   独立真实 browser 脚本须用实际页面/后端/provider，无 route mocks/测试桩；复用现有 ask-user UI、提交与刷新路径。

## Browser 探测与正式 E2E 所需证据

复用本地 integration web 的 Playwright 1.57.0：默认所需 Chromium 1200 不存在；现有缓存为 1234/1243。
指定缓存 1243 的 headless shell 后，初次沙箱内启动 `spawn EPERM`。用户已明确允许最小范围：独立无界面 Chromium、临时 profile、本实验 localhost、无现有窗口接管。
随后在该授权范围实际启动成功：Chromium `153.0.8010.12`、Playwright `1.57.0`；完成空白内存页面 title 读取并关闭浏览器。只证明启动能力，不证明真实服务/学生提交/Math E2E。
Playwright 与缓存 browser 版本不匹配仍需正式运行前固定并记录，必要时只向任务目录安装锁定依赖/匹配浏览器，不改变系统设置。
S8 正式步骤：实际 UI 提交→核 accepted row→A→B 后实际卡片→点击实际 opaque option→连续两次错误→修正→实际教学回应→刷新。
保存完整 body/events/ask-user 与选择/失败、各 turn 的 accepted IDs、canonical trajectory/basis、receipt/publication identity、刷新前后 body/trace 与截图；刷新不得新增 evidence/model call。
无真实卡片或教学回应时如实记录缺失；不为满足 E2E 人工拼出成功轨迹，不把 acknowledgement 计为可执行教学回应。

## 证据状态与下一步

- ACTUALLY_EXECUTED：本地仓库/remote/commit/工具检查、原生模块 import 与独立数学草稿检查、浏览器可用性探测（含失败）。
- PRIOR_REPORT_ONLY：closeout 134 focused、integration 151 focused/616 ordinary 等历史报告；本次未重跑，不算本轮 PASS。
- NOT_RUN：真实 Provider、8 场景教学对照、完整 Browser Math E2E、刷新 publication 回放、教学效果。
- GitHub Actions：`NOT_RUN_QUOTA`（委托/已合并报告披露），本轮未 dispatch，也未重新查配额。
- 本地 raw 证据/命令/environment allowlist 放在 ignored `data/phase-d-preparation/`；不保存密钥、全量环境或认证 headers。
- dot 源 thread `01a11ef3-4aad-7724-960a-af4723478027` 的状态发送工具返回 `thread not found`；未声称送达，交接以本材料和任务 final 为准。
- 剩余运行前事项：你自行更换/安全配置认证路径并确认；dot 核对冻结这份草稿及 reviewed source/最小 DI；固定可运行依赖和浏览器组合。
- 先保存未优化首轮真实证据并 STOP；dot 独立审阅后才安排局部表达修复与同样本复评。无真实完整教学链，不宣称最终 PASS。

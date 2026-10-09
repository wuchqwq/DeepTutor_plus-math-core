# Phase D 最小真实教学实验：准备交接

状态：**SCENARIOS FROZEN / DEEPSEEK / REAL RUN NOT STARTED**。本轮只完成无需凭据的准备，尚无逐场景教学输出。
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
- 全局 Python 有 SymPy/pytest/FastAPI/Pydantic/httpx/openai；无 tiktoken/mcp/litellm。已有 integration venv 配合任务目录 SymPy 1.14.0 已通过实际 import；不能将 import 当作真实 Provider 或 E2E。
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

两版使用同一实际可用 DeepSeek 型号及标准 Catalog 配置；不替换为 OpenAI。若只有滚动别名，记录实际请求型号、UTC、响应 model/id/created/system_fingerprint 和 usage，不因没有快照阻塞。
建议 temperature=0、top_p=1；宿主未显式发送 top_p 时如实记录 provider 默认与实际 wire 参数。单 worker，ordinary 输出上限 4096、alignment 2048、原 selector 1024。
预计至少 39–47 次模型调用，包含 alignment/selector 和可能的标题调用；实际宿主工具调用与重试另计。没有适用的已核验 DeepSeek 价格，不给 OpenAI 费用估算。
建议本轮合计 60 次请求；每个隔离进程 --request-limit 应传本轮剩余量，不能将每进程上限当作总预算。费用许可已经收到，但安全替换认证就绪仍未确认。

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
- 剩余运行前事项：你自行更换/安全配置认证路径并确认；8 情境已由 dot 冻结；具体 source 字段供 dot 核对；固定可运行依赖和浏览器组合。
- 先保存未优化首轮真实证据并 STOP；dot 独立审阅后才安排局部表达修复与同样本复评。无真实完整教学链，不宣称最终 PASS。

## 冻结修订与可执行脚本

S7 不强求追问：根据同页题面合理推断并保留不确定性也可接受，不因没有追问自动判失败。
`source.py` 直接用现有 ReviewedSource/MathWorkspaceSnapshot 原结构构造本轮 source；不导入 fixture，也不读取 grader_notes。16 个声明，15 个 qualified、1 个 not_checkable；没有 verified 或虚构工具证据。路径 A 为对称变量，B 为平方恒等式；运行时绑定真实宿主 learner/session/episode。
`provider.py` 将原 projection 交给既有 factory，并观察真实 SDK 请求/响应（排除认证 headers、密钥和私有 reasoning）；不返回测试桩输出。通过该 provider 的 httpx request hook 另计实际 HTTP 请求（含 SDK 内部重试），不保存 headers、URL query 或认证值。
`launch.py` 只复用原 container/catalog/TurnEngine/MathTurnCapability DI；默认禁用付费调用，--check 实际 start/close coordinator，--allow-paid 仅在安全认证就绪后使用。每 arm/case 使用不同 --home/--evidence，证据不写入 runtime。
`browser.cjs` 使用现有页面真实 composer、ask-user 按钮和 WebSocket；--startup-only 不提交学生输入。真实样本须显式 --allow-paid；缺失方法卡、terminal、教学或刷新回放均记录，不能据此宣称 PASS。
标准认证从本轮 runtime 的 Settings > Catalog 读取。registry 中 DEEPSEEK_API_KEY 的 env_key 是 provider 初始化导出路径，不能假定仅设置它便已让 Catalog 就绪。用户应自行在对应页面配置新 key，或者自行填写该 runtime 的 data/user/settings/model_catalog.json；执行任务不从别的项目搬运密钥。

## 本地执行与认证操作

无付费容器检查（在当前仓库根目录）：

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'data\phase-d-deps'
& 'F:\demo2\DeepTutor_upstream_v1_6_14\data\integration-venv\Scripts\python.exe' -B evaluation\phase_d_minimal\launch.py --arm integrated --case S8 --home data\phase-d-runtime\startup-integrated-S8 --evidence data\phase-d-evidence\startup-integrated-S8 --model deepseek-config-pending --check
```

去掉 `--check` 并添加 `--port 49301` 可启动原 API；默认禁止付费调用。`deepseek-config-pending` 仅是未配置时的启动标签，不声称是真实可用模型。
原前端在 web 目录运行 `node scripts/dev.mjs --webpack --hostname 127.0.0.1 --port 49300`，进程环境 `NEXT_PUBLIC_API_BASE=http://127.0.0.1:49301`，仅访问 localhost。
页面可用后，你自行打开 `http://127.0.0.1:49300/settings` 的 Catalog，添加/选择 DeepSeek 连接，输入替换后的新 key，选择实际可用模型，task 模型继承同一 LLM。不要把 key 发到聊天。
当前 runtime 的标准配置文件为 `data/phase-d-runtime/startup-integrated-S8/data/user/settings/model_catalog.json`；由你本地配置，执行任务不读取展示、搬运或提交其凭据。
确认旧 key 已撤销、新配置就绪后，重新启动时将 `--model` 改为实际 Catalog 型号，两版相同；真实运行才添加 `--allow-paid`。其他 arm/case 使用独立 home，由你自行准备相同认证配置，不能由脚本复制 key。
无付费页面检查：`node evaluation/phase_d_minimal/browser.cjs --url http://127.0.0.1:49300 --case S8 --evidence data/phase-d-evidence/startup-browser --startup-only`。本机可用缓存浏览器须另加已记录的 `--executable`；完整首轮才换成 `--allow-paid`。
运行后用 `export_evidence.py --home <本轮home> --evidence <本轮证据目录>` 只读导出 sessions/messages/turns/turn_submissions/turn_events/math_semantic_episodes，不导出认证配置或账户表。

## 本次实际无付费启动结果

- ordinary / integrated：原容器 start/close PASS；原 FastAPI 在 49302 / 49301 的 `/health/ready` 均实际返回 ready。
- 原页面 `/chat` 实际 HTTP 200，composer 可见，已用独立 Chromium 153.0.8010.12 / Playwright 1.57.0 保存启动截图并关闭 context/browser。没有提交学生输入。
- Windows 跨盘共享 Next junction 初次造成页面 HTTP500；仅将同版本 Next 物理复制到任务盘，其余库保持只读 junction，原 web 源码未修改。旧失败日志和截图保留。
- 第一个浏览器脚本未拒绝 HTTP500，退出0不能计 PASS；已增加 HTTP成功和 composer 判据。localhost DNS规则漏了127.0.0.1的一次失败也保留，修正后页面检查通过。
- 匹配 Chromium 安装停在 extracting archive；不继续安装调查。正式实验暂固定已实际启动过的上述组合，两版相同；是否能完成真实 Math E2E仍须实际执行。
- 认证 NOT_CONFIGURED；付费调用0、学生提交0，实际 SQLite 导出六张实验表全部0行。真实 DeepSeek、三维教学评分、方法确认和刷新 publication replay 均 NOT_RUN。
- `source_review/` 是明确数学 source 的字段及空学生文本 projection 导出，示例 episode=phase_d_review_S8、learner=local-admin；不伪称实际 accepted episode。运行时另保存真实 learner/session/episode 对应字段与每次实际 projection。

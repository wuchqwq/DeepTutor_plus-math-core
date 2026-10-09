# DT-UPSTREAM-V1.6.14-INTEGRATION

这是 PR #15 closeout 的 upstream delta addendum，范围是 v1.6.14 host compatibility；
不改变 Math Core 语义、trusted routing ownership 或教学表达，不开始 Phase D。

## 固定 merge 基线

```ini
REPO = wuchqwq/DeepTutor_plus-math-core
WORK_BRANCH = integration/dt-upstream-v1.6.14
PRE_UPSTREAM_MATH_BASE = b5c5546e95031e43a921c2e226f1296e58c1d4d3
UPSTREAM_BASE = 6cf793bd868ba5ecbe64722936d4be8fab5a01df
MERGE_BASE = 3b672dac89da9e83c7e0997911abd91f85c0f2f0
GITHUB_ACTIONS = NOT_RUN_QUOTA
PHASE_D_STARTED = NO
```

fetch 后 origin/dev、origin/main 与上述 SHA 精确相同；远端 integration branch
起点包含 math base。先确认原 checkout clean，再在独立 worktree 执行
`git merge --no-ff --no-commit origin/main`。**实际 textual conflicts：NONE**。
最终 merge 的两个 parent 是上述 math base / upstream base；没有 blanket
ours/theirs，也没有回退 upstream 功能。

## 自动合并后的语义审阅

| 共同修改位置 | 保留的组合与决定 |
| --- | --- |
| `core/context.py` | trusted accepted row ID/raw content、lease、protected mutation port、binding 全保留；新增 journal 字段只是 host teaching snapshot。 |
| `services/session/sqlite_store.py` | upstream 原子 submission reservation、digest/workspace/conversation checks、failed/cancelled row association 与原 math aggregate、receipts、commit fence 共存；没有第二套 acceptance/store。 |
| `services/session/turns/executor.py` | journal 在 turn-start 真实读取；upstream DONE 在 regenerate/retry 回显原 user-row association。runtime accepted seam 仍只来自本次真正新增的 user row，二者不能混用。accepted body/trace 持久化、formatter bypass、math error sanitization 与 B1 全保留。 |
| `agents/loop/pipeline.py` / `tools/builtin/__init__.py` | opaque option ID 传输与 normalization 保留；上游 scientific/visual tools 和 learning_status/update 不回退，也不成为 native math evidence。 |
| `pyproject.toml` / dependency mirrors | 保留 upstream packaging dependency 和既有 native math 依赖；不引入 external tutor_demo runtime。 |
| `test_agent_loop.py` | 上游 source visual positive controls 与既有 opaque ask_user controls 同时保留。 |
| frontend adapter/message list/schema | reading/video convergence、submission resend、branch/card replay 保留；option label 仍只是显示，selected_option_id 仍是身份。生成文件按 canonical exporter + npm generator 重建。 |

另独立检查了 Reading/video、visual source、indexing、provider/runtime 与 plugin
lifecycle 的 merge delta；没有为了 Math 回退这些功能。`deeptutor/math_semantic`、
native Math capability、math persistence boundary、B1 title owner、commit-fence owner
相对 math base 都无产品代码修改。

### 唯一局部 host 修复：显式 native capability 不被 plugin 替换

新增正式反例使用真实 managed PluginRegistry、persisted approval、accepted row、
trusted route、worker protocol、output persistence/replay，仅替换外部 worker I/O。
上游 lookup 在显式 native catalog 前扫描 enabled plugin：声明同名 `math_turn`
的已批准 plugin 可以取代 host factory。修复前实测 turn 为 completed、native
Math runs = 0，CONTENT/replay/assistant row 为 `Final answer x = 42`，assistant
metadata 为 `{}`，math episode rows = 0，完全没有 protected publication。

`CapabilityRegistry.get` 加六行局部 precedence：已经显式注册且没有
`_plugin_allowed` 标记的 native host factory 优先。guarded entry-point factory
继续走原 live gate；未注册的非冲突 managed capability 继续 discovery，disable、
失效 approval、已持有 worker 的撤销仍拒绝。再加一行既有兼容 factory 的 `Any`
annotation，避免 class/callable 推断错误；没有行为或 API 变化。
这没有新增 authority owner、routing framework、guard 或架构。

## Submission 与 journal delta regression

- **Completed lost ACK**：含普通 orientation 与真实 resolved MethodConfirmation
  两种 math history。同一 client_submission_id 的原请求在内存内及真正关闭后、
  fresh store/runtime/coordinator 中返回同 conversation / turn / accepted row。
  不执行 capability/generation，不追加 user evidence、alignment、trajectory、
  confirmation、receipt 或 sibling ownership。replay、assistant bytes、trace 与
  原 publication identity 精确一致；测试使用实际 title owner。
- **Failed / cancelled resend**：分别模拟 rejected candidate、生成中 cancel、
  receipt 已 commit 后 stream failure。upstream 创建新执行并关联原 user row，
  其原始 attribution 不重写；SESSION/DONE 保留原 row association。payload 是
  non-persist/regenerate，native accepted seam 为 None，所以 Math 在 proposal /
  generation 前 fail closed，不复制旧 receipt/candidate 或新增 math evidence。
  **同 causal ID 自动重试不等于新的 accepted math submission**；要继续新的
  math evidence，需要新的 host-accepted submission。普通 upstream retry 成功
  行为由 ordinary positive controls 保留。
- **Abuse / regenerate**：同 ID 的不同 content/config digest、真实不同 workspace、
  不同 explicit conversation 在 runtime admission 前拒绝。regenerate 不走
  completed submission replay，不获得旧 mathematical authority。
- **真实 Learning Journal**：mission、last_session.summary 和 record 持久化到
  upstream store；turn-start 真实注入 snapshot。与空 journal 的相同 A→B→opaque
  Method 2 history 比较，Core calculation、trajectory、canonical aggregate、
  verification UNKNOWN、orientation grants 全相同；quotes 仍来自真实 accepted
  rows，卡片/progress、body、receipt、events、fresh replay 均无 hostile journal
  文本。上游 eager snapshot 本身不包含 record history，learning_status 仍能读到
  hostile record；没有删除 journal、禁用 tools 或把它注入为数学 truth。普通
  capability 的 snapshot、原 prompt block、status/update 保持正向可用。
- **B1/B2 / publication/recovery**：重跑真实标题路径、hostile method、exact token
  mapping、UNKNOWN、malformed/foreign/stale candidates、pause/failure、普通 turns、
  branch/sibling isolation、独立进程 recovery 和只读 fresh replay。

正式 delta tests：`tests/math_semantic/test_upstream_{submission_integration,
journal_integration,capability_registration}.py`。

## 本地验证

| 验证 | 结果 |
| --- | --- |
| 指定 focused Math + 17 个 delta cases | **151 passed / 148.49s**；含 B1/B2、独立进程 recovery、publication、routing、host boundary。 |
| 指定 ordinary + journal API/tool/injection | **616 passed, 1 skipped, 1 deselected / 85.44s**（11 warnings）。保留已披露 Windows legacy migration fixture exclusion，不计其为 PASS。 |
| scoped native chain + changed capability registry mypy | **31 source files PASS**。 |
| native chain、共同修改关键宿主文件与 math/agent-loop tests Ruff | **51 files lint/format PASS**。 |
| canonical export/generate/check | Python exporter、npm generate/check 均 PASS；clean venv 再次 exporter `--check` PASS。 |
| 前端 | focused Vitest **11 files / 88 tests PASS**；node **1,303 PASS**；typecheck、architecture **911 modules / 2,868 dependencies**、4-file scoped ESLint PASS。 |
| repo/workspace | diff/index hygiene PASS；提交后 clean-worktree 与两个 ancestor checks PASS。 |

```powershell
# cwd: F:\demo2\DeepTutor_upstream_v1_6_14; ignored homes use shipped defaults
$env:PYTHONUTF8='1'
$env:PYTHONPATH='F:/demo2/DeepTutor_upstream_v1_6_14'
$testPython='data/integration-venv/Scripts/python.exe'
$env:DEEPTUTOR_HOME='F:/demo2/DeepTutor_upstream_v1_6_14/data/test-home-math'
& $testPython -m pytest tests/math_semantic/test_method_confirmation_presentation.py tests/math_semantic/test_publication.py tests/math_semantic/test_routing_isolation.py tests/math_semantic/test_math_turn_capability.py tests/math_semantic/test_recovery.py tests/math_semantic/test_host_boundary.py tests/math_semantic/test_import_boundary.py tests/math_semantic/test_upstream_submission_integration.py tests/math_semantic/test_upstream_journal_integration.py tests/math_semantic/test_upstream_capability_registration.py -q --basetemp=data/pytest-upstream-focused-final -o faulthandler_timeout=30
$env:DEEPTUTOR_HOME='F:/demo2/DeepTutor_upstream_v1_6_14/data/test-home-ordinary'
& $testPython -m pytest tests/services/session tests/runtime/test_orchestrator.py tests/tools/test_ask_user.py tests/app/test_turn_parked_on_ask_user_is_reclaimable.py tests/app/test_waiting_turn_recovery.py tests/app/test_turn_application_service.py tests/app/test_multiworker_turn_application.py tests/agents/chat/test_ask_user_drafts.py tests/api/test_unified_ws_turn_runtime.py tests/api/test_learning_journal.py tests/tools/test_learning_journal_tools.py tests/agents/chat/test_learning_journal_injection.py -q -k 'not test_sqlite_store_migrates_legacy_chat_history_db' --basetemp=data/pytest-upstream-ordinary-required
& $testPython -m mypy deeptutor/core/context.py deeptutor/runtime/orchestrator.py deeptutor/runtime/registry/capability_registry.py deeptutor/math_semantic deeptutor/capabilities/math_turn deeptutor/services/session/math_semantic_persistence.py deeptutor/services/session/turns/title_service.py --follow-imports=silent
$lintPaths=@('deeptutor/core/context.py','deeptutor/runtime/orchestrator.py','deeptutor/runtime/registry/capability_registry.py','deeptutor/services/session/sqlite_store.py','deeptutor/services/session/turns/executor.py','deeptutor/services/session/turns/title_service.py','deeptutor/agents/loop/pipeline.py','deeptutor/tools/builtin/__init__.py','deeptutor/math_semantic','deeptutor/capabilities/math_turn','deeptutor/services/session/math_semantic_persistence.py','tests/math_semantic','tests/agents/chat/test_agent_loop.py')
& $testPython -m ruff check @lintPaths
& $testPython -m ruff format --check @lintPaths
& $testPython scripts/export_frontend_contracts.py --check
& $testPython scripts/check_repo_hygiene.py
git diff --check
git diff --cached --check
& $testPython scripts/check_workspace_hygiene.py # after commit
git merge-base --is-ancestor b5c5546e95031e43a921c2e226f1296e58c1d4d3 HEAD
git merge-base --is-ancestor 6cf793bd868ba5ecbe64722936d4be8fab5a01df HEAD
# web cwd: npm run contracts:generate; npm run contracts:check; npm run typecheck
# npm run test:node; npm run architecture:check
# npm run test:unit -- tests/ask-user-card-form.spec.tsx tests/ask-user-resume-cursor.spec.tsx tests/ask-user-streaming-card.spec.tsx tests/ask-user-terminal-turn.spec.tsx tests/integration/ask-user-trace-continuity.spec.tsx tests/integration/chat-messages.spec.tsx tests/chat-failed-submission-recovery.spec.tsx tests/chat-branch-navigator.spec.tsx tests/media-reading-stage.spec.tsx tests/watching-browser.spec.tsx tests/reading-text-navigation.spec.tsx
```

生成器环境 Python 3.13 / FastAPI 0.136.3 / Pydantic 2.13.4。
canonical schema regeneration 的额外 delta 仅 11 个 upload fields 从
`format: binary` 变为 `contentMediaType: application/octet-stream`；生成 TS
只相应更新注释，类型仍为 string。没有手改 JSON/TS；opaque option constraints
未改变。前端复用经 package-lock blob 验证相同的依赖，临时目录全部 ignored。

初始全局 Python 环境的 package manifest/file inventory 同步扫描阻塞 event loop，
使 leased test 在 protected mutation 前正确拒绝 `Turn authority lost`；初始 broad
run 中断、**不算 PASS**。在隔离 venv 安装测试所需 host 依赖后重跑全部指定套件，
真实 plugin discovery 仍开启，既有 lease/timeouts、fence 和 assertion 未放宽。
没有为了环境超时关闭 lost-ACK、journal 或 plugin lifecycle。

Windows 本地环境另装 tzdata 2026.5，仅写 ignored venv；MCP 1.30.0 满足
pyproject 的 `>=1.26,<2`，pip check PASS。focused 初次 clean-env 整组为
150 PASS / 1 ordinary-return lease timeout；原样单例重跑及上述最终完整 151
均通过，原失败日志保留。没有将初次失败计为通过。

### 补充检查中的未通过项（不是指定 ordinary 套件 PASS）

额外 broad ordinary（另含全 agent-loop、journal store、runtime registry）首轮
751 PASS / 8 FAIL / 1 skipped / 1 deselected。其中 6 个 Windows ZoneInfo
缺 tzdata 已在最终完整指定套件通过。剩余两例原样重跑仍失败：upstream
`test_cold_start_stalled_provider_settles_with_bounded_retries[partial_stream]`
在 consumer drain 前断言 progress；journal `test_two_workers_do_not_drop_confirmed_records`
在 Windows byte lock 被占用时、取得 lock 前读取 byte 报 PermissionError。
这两例 source/相关测试与 upstream 相同，未修复、未计 PASS；不证明 concurrent
Windows journal writers 完整性，也不把 journal 当 canonical math state。

另跑 `tests/plugins`、`tests/knowledge/test_indexing_run.py`、video migration 和
reading PDF/page/media/hints/captions：125 PASS / 9 FAIL。补齐隔离 home 的 shipped
main.yaml 后 readiness 原样重跑 1 PASS；其余为 1 Windows symlink 权限、6 个
POSIX-only fake-install layout fixtures、1 缺 optional llama_index 的 persisted-vector
case。相关 source/tests 与 upstream byte-for-byte 相同，**未计为 PASS**，不为此
改写 plugin lifecycle、增加 RAG 范围或修改现有测试。Reading/video 正向用例在该
组均通过；新 registry 五例与 upstream plugin runtime 七例另已完整 12 PASS。

## 结论与保留限制

```ini
UPSTREAM_V1_6_14_INTEGRATION = PASS
BOTH_BASES_ARE_ANCESTORS = YES
LOST_ACK_MATH_IDEMPOTENCY = PASS
FAILED_CANCELLED_RETRY_MATH_IDENTITY = PASS
SUBMISSION_REQUEST_ISOLATION = PASS
REGENERATE_SEPARATION = PASS
LEARNING_JOURNAL_AUTHORITY_ISOLATION = PASS
B1_SESSION_TITLE = PASS
B2_METHOD_CONFIRMATION = PASS
MATH_PUBLICATION_REGRESSION = PASS
MATH_RECOVERY_REPLAY = PASS
ORDINARY_DEEPTUTOR_REGRESSION = PASS
DT_POC_PASS_AFTER_UPSTREAM = YES
PHASE_D_READY = YES
PHASE_D_STARTED = NO
GITHUB_ACTIONS = NOT_RUN_QUOTA
```

已证明范围仍是单个 MemoryCoordinator authority domain 的 SQLite protected
commit、opt-in trusted reviewed DI、现有 reviewed domain fixtures 和 bounded
literal publication。PocketBase/Redis protected mutation/recovery、distributed
commit、geometry、RAG math integration、完整 browser math E2E、真实学生教学效果
与 exactly-once network delivery 均不宣称已证明；本轮不扩这些范围。

**publication safety proven != high-quality natural tutoring language proven**。
PHASE_D_READY 只说明接入前提，不表示 Phase D 已获授权。提交并开 targeting dev
的正式 PR 后 STOP，不 merge。

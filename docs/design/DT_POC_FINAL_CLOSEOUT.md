# DT-POC-FINAL-CLOSEOUT

```ini
REPO = wuchqwq/DeepTutor_plus-math-core
BASE_BRANCH = dev
BASE_SHA = e6572002cdc627a0c2db133d858a5c3b7f83560e
DT_POC_PASS = YES
PHASE_D_READY = YES
BLOCKING_ISSUES = NONE
B1_UNBOUNDED_POST_TURN_SESSION_TITLE = FIXED
B2_METHOD_CONFIRMATION_DISCLOSURE = FIXED
PRODUCT_CODE_CHANGED = NO
PHASE_D_STARTED = NO
GITHUB_ACTIONS = NOT_RUN_QUOTA
```

结论限于 Owner 指定的十项 surface、当前受支持的 SQLite/MemoryCoordinator
宿主链和既有回归。最新 dev 与基线一致，B1/B2 已合并；本轮不改产品代码、
测试或架构。未发现满足本轮 stop rule 的可复现学生可见 authority bypass，
或 canonical math state / episode / authority corruption。Phase D READY
表示该 POC 接入前提已满足，**不表示已经授权或开始 Phase D**。

## 固定 student-visible surface inventory

下表“数学内容”指系统教学披露，不把学生自己提交的数学文本当作验证结论。
“无已知路径”只覆盖本次正常受支持链、列出的 failure controls 和修复后生成的
durable history，不声称过滤任意外部插件、未来后端或历史版本已写入的不安全事件。

| Surface | 学生可见性 | math_turn 可能携带数学内容 | authority / safe-display boundary | 已知未经授权披露 |
| --- | --- | --- | --- | --- |
| CONTENT | 是，实时 body | 仅 Core 授权的 canonical result literal；UNKNOWN 只有操作性 acknowledgement | `output.accept_response` 重验当前 basis/grants，protected receipt commit 后才 emit | 无 |
| RESULT | 是，结果 envelope | 与 CONTENT 同一 accepted response；trace 不包含 raw claims/trajectory/method | 同一 `AcceptedTurnOutput` 的 response、publication trace | 无 |
| ERROR | 是，失败提示 | 已测 provider exception、malformed candidate、publication rejection 不携带其数学文本 | orchestrator math failure 清空输出，固定 `Mathematical publication failed.` / `math_publication_rejected`；cancel/shutdown 是宿主状态文案 | 无 |
| TOOL_RESULT / ask_user | 是，确认卡片及 metadata | 当前 math capability 只发固定 prompt、中性 Method N 和 opaque IDs | B2 的局部 token→neutral label map；raw method 留在私有 semantic state | 无 |
| WAIT_FOR_INPUT | 是，等待状态及卡片交互 | 本帧无数学 payload；关联卡片受上一项边界约束 | math-owned 空等待事件；宿主管理 waiting_input | 无 |
| resolved PROGRESS | 是，确认完成状态 | 仅同一中性 label、confirmation ID、opaque token | 验证并 durable resolve exact token 后，服务器回显 safe label；不回显 client text/raw method | 无 |
| SESSION_META / session title | 是，标题 | trusted-routed math 不产生自动标题内容或变更 | B1 title owner 按 `execution.capability == "math_turn"` 在读消息/model/fallback/write/emit 前返回 | 无 |
| CAPABILITY_COMPLETE | 内部 EventBus，非直接 chat stream 帧；按潜在下游可见面检查 | agent_output 只能是 accepted body；失败为空；user_input 是输入回显，非数学验证结论 | `completion_event_fields` 优先 accepted content/metadata，不转发整个 context/private calculation；math failure 清理兼容字段 | 无 |
| persisted assistant row | 是，历史聊天 | 与 accepted body 完全一致；失败控制为空 body | executor 比较 captured body 与 accepted.content，跳过普通 formatter，保存 accepted trace 并 parent 到真实 user row | 无 |
| fresh durable event replay | 是，恢复/重连历史 | 重放上述已保存 safe payload 和原 accepted trace，不重新授予数学 authority | lifecycle 读取 SQLite events、保留 seq/metadata；fresh runtime/coordinator 不重新执行 capability/generation | 无 |

代码边界：`deeptutor/capabilities/math_turn/{capability,output}.py`；
`runtime/orchestrator.py:29,173,228`；
`services/session/turns/executor.py:1030,1121,1238`；
`services/session/turns/title_service.py:50`；
`services/session/turns/lifecycle.py:354,655`。
B2 的 Web 卡片显示面仍是 `AskUserOptions.tsx`，本轮不改 renderer/protocol，
也不宣称运行了完整 browser math E2E。

## Cross-stage composition 与 PROVEN_SCOPE

- **一个宿主 owner / 一个数学真相来源。** persisted accepted row ID/raw content
  是输入 basis；`run_durable_turn_mutation` 是 durable math commit port。原
  SQLite episode aggregate 保存 canonical snapshots、alignment、confirmation
  和 publication receipts，Core 从它重建 trajectory；没有第二份 trajectory truth、
  Math runtime/store/coordinator 或新 authority owner。
- **Routing / episode isolation。** host DI 在 acceptance 后绑定 capability/scope，
  protected 持久化 immutable attribution；math evidence 仅属于同 episode 的明确
  host-attributed rows。ordinary gap 不进入 math prefix，恢复后可返回同 episode；
  ambiguous/missing scope、伪造 metadata、branch/sibling borrowing 均 fail closed。
- **Recovery / confirmation。** 真正独立进程和 fresh objects 从同 DB 重验
  start、accepted basis、revision、identity、grounding；无旧 binding cache 必需。
  resolved token 继续约束未来 path；pending 不自动消失/resolve/被 evidence 绕过。
  dead parked host turn 由既有 application lifecycle 处理为 worker_lost，再在新
  accepted turn 重呈已有确认，不声称复活旧 waiter 或通用 turn resume。
- **Authority / publication。** trajectory 成功不等于验证；UNKNOWN/unsupported
  不升级。generation 只是有界 grant selection，result 必须具备独立 verified
  grounding 与 exact content support。当前 basis/grants 在 protected acceptance
  中重验；stale/foreign basis/grant、regenerate 缺 acceptance、retry 重用旧
  candidate 均拒绝，无 ordinary math fallback。
- **Presentation / post-turn composition。** hostile `Factorization` /
  `Final answer x = 42` 只留在私有 source；Method 2 的 token 仍选 exact path B。
  label/ordinal/raw method/path/free text/foreign token/stale confirmation 无法
  冒充 identity。主 body、completion、assistant row 共用 approved bytes，formatter
  不改写；自动 math title 不调用 model、不 fallback、不写 title、不发 SESSION_META。
  普通 chat/reading/research 标题与 generic ask_user 原行为保持。
- **Commit / replay。** affected turn/session authority lock 将 ownership
  invalidation 与 SQLite transaction commit/rollback 排序，非 fencing snapshot
  推论；unrelated B renewal 回归仍覆盖。关闭旧对象后 replay 保留原 publication
  identity、字节与 trace，不新增 math evidence、不改变 canonical state。
  这些是当前单进程 authority domain 的保证，不是跨进程 shared-lock 保证。

## KNOWN_NON_BLOCKING_LIMITATIONS

```ini
SQLITE_SINGLE_PROCESS / CURRENT_COMMIT_FENCE_SCOPE = one MemoryCoordinator authority domain; no distributed commit claim
OPT_IN_TRUSTED_REVIEWED_DI = math capability/source/scope must be explicitly composed; no default/global math routing
REVIEWED_DOMAIN_COVERAGE_LIMITED = frozen reviewed domain fixtures; not universal mathematics
GEOMETRY_NOT_YET_ESTABLISHED = no geometry extension or verification claim
BOUNDED_LITERAL_TEACHING_OUTPUT = acknowledgement plus exactly authorized canonical literals; finite POC ledger scope
HIGH_QUALITY_NATURAL_TUTORING_LANGUAGE_NOT_PROVEN = YES
REAL_STUDENT_TEACHING_EFFECT_NOT_PROVEN = YES
FULL_BROWSER_MATH_E2E_NOT_YET_PROVEN = YES
NO_EXACTLY_ONCE_NETWORK_DELIVERY_CLAIM = YES
```

PocketBase/Redis 缺 protected mutation port 时 fail closed，不宣称它们的 math
recovery/commit 已成立。历史 pre-fix audit events 未被迁移/改写。上述扩展和产品
限制不是当前 POC blocker；本轮没有扩大到 RAG、Memory/Mastery、几何、分布式
恢复或教学产品完成度。

**publication safety proven != high-quality natural tutoring language proven**。
当前目标是证明 Math Core 能安全、可恢复、可隔离地接入 DeepTutor；教学语言质量、
真实教学效果和最终产品完成度仍未证明。

## 当前基线本地验证

focused **134 passed / 149.16s**（含 B1 real-title controls、B2 hostile
MethodConfirmation、capability/routing/recovery/publication/host boundary）。
ordinary **583 passed, 1 skipped, 1 deselected / 81.38s**（7 warnings）。
mypy **30 source files PASS**；Ruff lint/format **43 files PASS**；
repository/workspace hygiene 和 diff checks PASS。ordinary 保留此前已披露的
Windows legacy DB migration fixture deselection（打开的连接阻止移动 DB），不算
PASS；typecheck 是 scoped native chain，不是全仓库 typecheck。

```powershell
# cwd: F:\demo2\DeepTutor_poc_final_closeout; isolated homes contain shipped agents.yaml
$env:PYTHONUTF8='1'
$env:PYTHONPATH='F:/demo2/DeepTutor_poc_publication_04/data/test-deps;F:/demo2/DeepTutor_poc_final_closeout'
$env:DEEPTUTOR_HOME='F:/demo2/DeepTutor_poc_final_closeout/data/test-home-math'
python -m pytest tests/math_semantic/test_method_confirmation_presentation.py tests/math_semantic/test_publication.py tests/math_semantic/test_routing_isolation.py tests/math_semantic/test_math_turn_capability.py tests/math_semantic/test_recovery.py tests/math_semantic/test_host_boundary.py tests/math_semantic/test_import_boundary.py -q --basetemp=data/pytest-final-focused
$env:DEEPTUTOR_HOME='F:/demo2/DeepTutor_poc_final_closeout/data/test-home-ordinary'
python -m pytest tests/services/session tests/runtime/test_orchestrator.py tests/tools/test_ask_user.py tests/app/test_turn_parked_on_ask_user_is_reclaimable.py tests/app/test_waiting_turn_recovery.py tests/app/test_turn_application_service.py tests/app/test_multiworker_turn_application.py tests/agents/chat/test_ask_user_drafts.py -q -k 'not test_sqlite_store_migrates_legacy_chat_history_db' --basetemp=data/pytest-final-ordinary
python -m mypy deeptutor/core/context.py deeptutor/runtime/orchestrator.py deeptutor/math_semantic deeptutor/capabilities/math_turn deeptutor/services/session/math_semantic_persistence.py deeptutor/services/session/turns/title_service.py --follow-imports=silent
python -m ruff check deeptutor/core/context.py deeptutor/runtime/orchestrator.py deeptutor/services/session/turns/executor.py deeptutor/services/session/turns/title_service.py deeptutor/math_semantic deeptutor/capabilities/math_turn deeptutor/services/session/math_semantic_persistence.py tests/math_semantic
python -m ruff format --check deeptutor/core/context.py deeptutor/runtime/orchestrator.py deeptutor/services/session/turns/executor.py deeptutor/services/session/turns/title_service.py deeptutor/math_semantic deeptutor/capabilities/math_turn deeptutor/services/session/math_semantic_persistence.py tests/math_semantic
python scripts/check_repo_hygiene.py
git diff --check
python scripts/check_workspace_hygiene.py # before edits and after commit
```

补充只读检查当前 focused 产生的 15 个 DB：fresh store/runtime/coordinator
逐项重放 **16 turns / 4 accepted publications / 12 rejected turns PASS**；
replay 与 SQLite saved events 完全相同，禁止文本均缺席，publication identity /
body / trace 未变，canonical payload 检查前后完全相同，没有 capability 重执行。
为使此 evidence 可复核，以下脚本可保存为 ignored
`data/final_replay_check.py`，用上方 math home/PYTHONPATH 运行
`python data/final_replay_check.py`；它不是新增产品组件或正式测试改动。

<details>
<summary>只读 fresh replay 检查脚本</summary>

```python
"""Read-only fresh replay of current closeout regression databases."""
import asyncio
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from deeptutor.runtime.coordination import MemoryCoordinator
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.services.session.turn_runtime import TurnRuntimeManager

PREFIXES = ("test_buffered_generation_accep", "test_orientation_only_publishe",
            "test_unknown_cannot_upgrade_or", "test_hostile_method_text_is_pr")
FORBIDDEN = ("CONFIDENT_FINAL_ANSWER: Q = 999", "Factorization", "Final answer x = 42")

def math_rows(db):
    with closing(sqlite3.connect(db)) as conn:
        return conn.execute("SELECT episode_id, payload_json FROM math_semantic_episodes ORDER BY episode_id").fetchall()

async def main():
    dbs = sorted(p for p in Path("data/pytest-final-focused").glob("*/*.db")
                 if p.parent.name.startswith(PREFIXES))
    assert len(dbs) == 15, len(dbs)
    counts = {"databases": 0, "turns": 0, "accepted_publications": 0, "rejected_turns": 0}
    for db in dbs:
        before = math_rows(db)
        receipts = {tid: r for _, raw in before
                    for tid, r in json.loads(raw).get("host_math_publications", {}).items()}
        with closing(sqlite3.connect(db)) as conn:
            turns = conn.execute("SELECT id, status FROM turns ORDER BY created_at").fetchall()
        store = SQLiteSessionStore(db)
        coordinator = MemoryCoordinator()
        runtime = TurnRuntimeManager(store, coordinator=coordinator)
        try:
            for tid, status in turns:
                assert status in {"completed", "failed"}, status
                saved = await store.get_turn_events(tid)
                replay = [e async for e in runtime.subscribe_turn(tid)]
                assert replay == saved, (db, tid)
                assert all(s not in json.dumps(replay) for s in FORBIDDEN), (db, tid)
                if tid in receipts:
                    receipt = receipts[tid]
                    trace = json.loads(receipt["metadata_json"])["math_publication"]
                    assert trace["publication_id"] == receipt["publication_id"]
                    content = next(e for e in replay if e["type"] == "content")
                    result = next(e for e in replay if e["type"] == "result")
                    assert content["content"] == result["metadata"]["response"] == receipt["content"]
                    assert content["metadata"]["math_publication"] == result["metadata"]["math_publication"] == trace
                    counts["accepted_publications"] += 1
                if status == "failed":
                    assert not any(e["type"] in {"content", "result"} for e in replay)
                    counts["rejected_turns"] += 1
                counts["turns"] += 1
        finally:
            await runtime.close()
            await coordinator.close()
        assert math_rows(db) == before
        counts["databases"] += 1
    assert counts == {"databases": 15, "turns": 16, "accepted_publications": 4, "rejected_turns": 12}, counts
    print(json.dumps({"FRESH_DURABLE_REPLAY": "PASS", **counts}, sort_keys=True))

asyncio.run(main())
```

</details>

GitHub Actions 因 quota 未运行（[skip ci]，无 workflow 改动/dispatch）。
交付只有本文档；commit/push/open PR targeting dev 后 STOP，不 merge。
等待 Owner 正式授权 Phase D。

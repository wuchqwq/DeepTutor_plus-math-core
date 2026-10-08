# DT-POC-CLOSEOUT — HOLD

审计基线：`wuchqwq/DeepTutor_plus-math-core`，
`dev@b741c3a14fef8f131f9b0defe29c66c32fada561`（PR #10 已合并）。
独立 fetch 确认 SHA 后，从该 SHA 建立只读产品代码的审计 checkout。
迁移依据为已接受的 Migration Roadmap V2，
`tutor_demo@a2a1905dc41eed3e5a574304993c2747dcb0838c` 的第 7–8 节。

```ini
DT_POC_PASS = NO
PHASE_D_READY = NO
BLOCKING_ISSUES = B1_UNBOUNDED_POST_TURN_SESSION_TITLE
KNOWN_NON_BLOCKING_LIMITATIONS = SQLITE_SINGLE_WORKER; OPT_IN_TRUSTED_DI; BOUNDED_LITERAL_RENDERING; NO_TEACHING_QUALITY_PROOF; NO_AUTOMATIC_DELIVERY_RECOVERY
PRODUCT_CODE_CHANGED = NO
PHASE_D_STARTED = NO
GITHUB_ACTIONS = NOT_RUN_QUOTA
```

## B1：正文接受后，自动标题仍能发布未授权数学答案

真实链路：persisted accepted row → trusted math routing → production
MathTurnCapability → native Core trajectory/authority → bounded proposal →
protected output receipt → assistant row/DONE → **普通自动标题生成** →
session title 持久化与 `session_meta`。

在一个真实的新 session 中，Core 的 verification 为 `UNKNOWN`，全部 15 个
grants 均为 orientation，获接受并持久化的正文只有
`Mathematical evidence recorded.`。标题模型返回 `Final answer Q = 999` 后：

- `sessions.title` 被写为该答案；没有对应的数学 publication acceptance。
- `session_meta` 的 `content` 和 `metadata.title` 都包含该答案，seq=5，位于
  DONE 之后；metadata 中没有 `math_publication`。
- 既有 Web `ChatStateAdapter` 消费该事件并设置学生可见的 session title。
- 没有 ordinary capability 执行；漏洞发生在正确 routed/accepted 的 math turn
  后续 host presentation 路径，不是把普通聊天故意划入 Math Core。

复现只替换 provider I/O，保留真实 completion/stream factory、标题 owner、
SQLite store、MemoryCoordinator、application、runtime、routing 和 Math capability。
不是手工构造 UnifiedContext 或直接调用 standalone title sanitizer。

定位（行号固定于审计 SHA）：

| Existing owner | 证据 |
| --- | --- |
| `services/session/turns/executor.py:1241–1252` | completed 非 regenerate turn 在正文/DONE 后调用自动标题，无 math-route 检查 |
| `services/session/turns/title_service.py:74–135` | 独立自由文本 LLM 调用；sanitize 仅清理格式；失败后还会取 raw user prefix |
| `services/session/turns/title_service.py:142–160` | 普通写入 session title，然后发学生可见 SESSION_META，无 Core grant/basis 检查 |
| `web/features/chat/ChatStateAdapter.tsx:1992–2031` | SESSION_META title 进入 SET_SESSION_TITLE |
| `tests/math_semantic/test_routing_isolation.py:214–217` | RoutingHost 把真实标题方法替换为 no-op；publication tests 复用此 host |
| `tests/math_semantic/recovery_support.py:209–212` | recovery host 同样禁用标题；跨阶段绿色测试没有覆盖此路径 |

这是 host 输出覆盖范围缺口：正文 guard 正确不等于所有学生可见 host 输出受约束。
不能把标题改称“metadata”而宣称 publication safety 全面 PASS。

**最小修复建议，未实施：** 在现有 SessionTitleService 的入口依据已经完成
trusted routing 的 `execution.capability`，对 `math_turn` 跳过自动标题的模型调用
及 raw-user fallback，保留现有中性占位标题。普通 turn 的标题行为保持原样。
不新增 guard、policy、manager、store，也不修改 Core 或 routing ownership。
在真实 host integration test 中启用原标题方法，用 orientation/UNKNOWN 的
成功 turn 和恶意标题 provider 证明没有答案写入 title/SESSION_META；检查普通
turn 仍能命名。不要用 prompt、数学文本识别或 regex 代替这条 host-owned 分支。
修复后须重新审计所有学生可见辅助输出，Owner 接受后再判断 closeout；不是
开始 Phase D 的授权。

## 主线审计与证明边界

以下是本次源码核查与已合并阶段证据的组合判断；不是声称本次重跑了全部历史
测试，亦不是因为 B1 之外未报告问题便宣称不存在其他问题。

| 边界 | 当前依据 / 结论 |
| --- | --- |
| Accepted turn | Executor 使用新持久化 row 的 exact ID/raw/client ID；非 persist/regenerate 不造 identity；adapter 在 protected transaction 中重读核对 |
| Commit ownership | SQLite binder + MemoryCoordinator affected session/turn locks覆盖 worker 的真实 COMMIT/ROLLBACK；同时校验 durable owner/token/running/version；unsupported port 无普通写入 fallback |
| Routing / episode | TurnEngine 只消费 trusted DI 的 frozen identity reference；immutable host attribution决定 math prefix；普通 gap 不算 math evidence；ancestry 检查拒绝 sibling history，fork 需新 reviewed episode |
| Native Core / trajectory / confirmation | canonical aggregate、reviewed source/head、historical raw grounding重验；opaque token 精确映射 authored path；pending/resolved ledger 为唯一数学事实，trajectory success 不升级 UNKNOWN |
| Publication body | proposal 只能选当前 grants；commit 内重算 basis 与 exact relation；只发布中性状态句和明确授权的 verified literal；正文/live/receipt/assistant/completion绑定同一 trace |
| Cross-stage composition | recovery/routing/publication正文共享同一 durable basis；**B1** 在该链完成之后仍执行未约束的普通标题路径，打破完整学生可见 containment |
| Owner inventory | 未发现新增的第二 runtime/store/lease/coordinator；Core 管数学语义，host 管 acceptance/lease/SQL，薄 adapter 不再造 lifecycle；receipt 是既有 aggregate 的 host 输出记录，不是第二 trajectory truth |

restart、pending/resolved confirmation、regenerate、accepted retry、ordinary gap 和
branch 的已合并 focused controls仍是各自有限路径的证据（见下列阶段文档与对应
`tests/math_semantic`）。它们不能补上被 no-op 掉的标题路径。持久化的未授权 title
还会在 session reload 中继续可见，无需重跑 Core；因此 recovery 不会自动修复 B1。
CLI/WS/SDK 共用 application/runtime 是源码事实，不等于本次完成了全部 transport
与真实 provider 的端到端评估。

阶段证据：
[native extraction](MATH_SEMANTIC_EXTRACTION_01.md)、
[capability](MATH_TURN_CAPABILITY_02.md)、
[recovery](POC_RECOVERY_02.md)、
[routing](POC_ROUTING_ISOLATION_03.md)、
[bounded publication](POC_PUBLICATION_04.md)；host fence 见
[durable contract](../guides/dt-durable-turn-fence-01.md)。这些先前文档的阶段 PASS
保留为受测路径证据，本 closeout 不把它们扩展为完整 POC PASS。

已证明的有限范围：SQLite + 同一 process-local MemoryCoordinator 的 single-worker
host，顺序进程重建，opt-in trusted reviewed composition，native algebra/finite literal
grant consumption 和正文 authority-before-visible。未证明的范围包括 PocketBase/Redis
protected commit、多进程并发 recovery、默认产品激活、完整 transport/provider 行为、
geometry、一般自然语言语义等价、自动补发未送达 receipt、网络 exactly-once delivery。
这些不是本次要求顺手实施的功能。

```text
publication safety proven != high-quality natural tutoring language proven
```

当前只证明受测正文的 bounded rendering，**完整 publication safety 因 B1 未通过**。
模型选 grant IDs + 既有状态句/精确 artifact literal 不证明高质量自然教学语言；
没有教学策略、语言质量、真实 provider 或教学效果评估。语言质量本身不是把
技术 gate 判为 FAIL 的原因，B1 才是 blocker。Phase D 必须另行 Owner 授权。

## 本次验证与可执行复现

在上述精确基线运行下面的独立 probe，退出码 0：断言的是 **bypass 已复现**，
不是安全 regression PASS。第一次 sandbox 内 SQLite activity DB 创建被 Windows
文件访问限制阻止；在同一隔离目录重跑后完成，没有网络模型调用。
附录中的 probe 也提取到独立脚本、换用另一份新 DB 执行，结果一致。
本次未重跑历史 full suites/mypy/Ruff；只提交本文档，不改产品代码或测试。
diff/repository/workspace hygiene 为本次文档检查；GitHub Actions 不运行。

将下面 Python block 保存为 ignored `data/probe_title.py`，使用已声明的完整本地
依赖和只含 shipped defaults 的独立 `DEEPTUTOR_HOME`。DB 路径应为新的审计文件。
实际命令：

```powershell
$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = 'F:/demo2/DeepTutor_poc_publication_04/data/test-deps;F:/demo2/DeepTutor_poc_closeout'
$env:DEEPTUTOR_HOME = 'F:/demo2/DeepTutor_poc_closeout/data/audit-home'
python data/probe_title.py
```

```python
import asyncio
from pathlib import Path
import json
from types import SimpleNamespace
from unittest.mock import patch
from deeptutor.services.config.provider_runtime import ResolvedLLMConfig
from deeptutor.services.session.turns.title_service import SessionTitleService
from tests.math_semantic.recovery_support import A, harmless_generation
from tests.math_semantic.test_routing_isolation import RoutingHost

ANSWER = "Final answer Q = 999"
calls = []

class TitleProvider:
    async def chat_stream_with_retry(self, **kwargs):
        calls.append(kwargs["messages"])
        await kwargs["on_content_delta"](ANSWER)
        return SimpleNamespace(finish_reason="stop", content=ANSWER,
                               reasoning_content="", usage={})
    async def aclose(self):
        pass

async def main():
    with patch("deeptutor.services.skill.runtime.skill_manifest", lambda: ""), patch(
        "deeptutor.services.llm.config.resolve_llm_runtime_config",
        lambda *args, **kwargs: ResolvedLLMConfig(
            model="gpt-4o-mini", provider_name="openai", provider_mode="direct",
            binding="openai", api_key="sk-test", base_url="https://api.openai.com/v1",
            effective_url="https://api.openai.com/v1", context_window=128000,
        ),
    ), patch("deeptutor.services.llm.config._LLM_CONFIG_CACHE", None), patch(
        "deeptutor.services.llm.factory._complete_with_resolved_config", harmless_generation
    ), patch("deeptutor.services.llm.factory.get_runtime_provider", lambda config: TitleProvider()):
        host = RoutingHost(Path("data/title-counterexample.db"))
        host.scope = host.math_scope()
        host.runtime._maybe_generate_session_title = (
            SessionTitleService._maybe_generate_session_title.__get__(host.runtime)
        )
        try:
            session, turn = await host.submit(A)
            events = [event async for event in host.runtime.subscribe_turn(turn["id"])]
            saved_session = await host.store.get_session(session["id"])
            receipt = host.state()["host_math_publications"][turn["id"]]
            assert host.result()["verification_status"] == "UNKNOWN"
            assert all(g["act_kind"] == "orientation" for g in host.result()["authority"])
            assert receipt["content"] == "Mathematical evidence recorded."
            assert saved_session["title"] == ANSWER
            title_event = next(e for e in events if e["type"] == "session_meta")
            assert title_event["content"] == title_event["metadata"]["title"] == ANSWER
            assert "math_publication" not in title_event["metadata"]
            assert title_event["seq"] > next(e["seq"] for e in events if e["type"] == "done")
            assert len(calls) == 1 and not host.ordinary_contexts
            print(json.dumps({"verification": "UNKNOWN", "approved_body": receipt["content"],
                              "persisted_title": saved_session["title"], "event": title_event}))
        finally:
            await host.close()

asyncio.run(main())
```

处置：只提交 HOLD 证据，等待 Owner 对最小修复的下一步授权；不实现修复，
不 merge，不开始 Phase D、Clean Break 或任何后续产品阶段。

"""Thin real-provider proposal adapter plus evaluation-only SDK observation."""
import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import threading
import time

from deeptutor.math_semantic.proposals import AlignmentProposal


def append_record(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"utc": datetime.now(timezone.utc).isoformat(), **value}, ensure_ascii=False) + "\n")


class RealAlignmentProvider:
    provider_id = "deepseek_existing_factory"

    def __init__(self, model: str, evidence: Path):
        self.model, self.evidence = model, evidence
        self.loop = None
        self.model_config_digest = hashlib.sha256(json.dumps({"model": model, "binding": "deepseek", "temperature": 0, "top_p": 1, "max_tokens": 2048}, sort_keys=True).encode()).hexdigest()

    def propose(self, projection):
        from deeptutor.services.llm import factory
        prompt = json.dumps(asdict(projection), ensure_ascii=False)
        append_record(self.evidence / "alignment_calls.jsonl", {"stage": "alignment_input", "projection": asdict(projection), "config_digest": self.model_config_digest})
        if self.loop is None or self.loop.is_closed():
            raise RuntimeError("Real proposal provider requires the running host event loop")
        pending = asyncio.run_coroutine_threadsafe(factory.complete(
            prompt=prompt, model=self.model, binding="deepseek",
            temperature=0, top_p=1, max_tokens=2048, max_retries=0,
            response_format={"type": "json_object"},
            system_prompt="Extract only actual student assertions from response_text. On the first submission, the question and student-background sections are context, not new student derivation; only the 我的提交 section asserts student work. Return one JSON object with claims, novel_paths, interaction_type, using the native AlignmentProposal schema. Claims have evidence {quote, occurrence}, claim_type (equation/expression/answer/identity), parse_status (parsed/ambiguous/unparsed), candidate_artifact_refs, uncertainty. References may only come from the supplied projection. Quotes must be exact student substrings. Questions with no asserted math have interaction_type question or clarification and empty claims. Use answer for asserted math even when followed by a request to check it. Novel paths are optional and bounded, with claim_indices, method, dependency_artifact_refs. Do not grade, teach, invent evidence, confer verification, or solve the question.",
        ), self.loop)
        try:
            raw = pending.result(timeout=180)
        except Exception:
            pending.cancel()
            raise
        append_record(self.evidence / "alignment_calls.jsonl", {"stage": "alignment_output", "output": raw})
        return AlignmentProposal.from_value(json.loads(raw))


def observe_sdk_calls(evidence: Path, *, allow_paid: bool, expected_model: str, request_limit: int = 60):
    """Observe real SDK calls; no fabricated responses or changes to math output."""
    from openai.resources.chat.completions import AsyncCompletions
    original = AsyncCompletions.create
    lock = threading.Lock()
    count = 0
    http_count = 0

    async def observed(self, **kwargs):
        async def real_create(**wire):
            nonlocal count
            if not allow_paid:
                raise RuntimeError("Phase D startup-only mode: paid provider calls are disabled")
            if wire.get("model") != expected_model or self._client.base_url.host != "api.deepseek.com":
                raise RuntimeError("Phase D requires the same configured DeepSeek model on every call")
            # The frozen experiment fixes these provider parameters on all
            # stages, including native chat/title calls with their own defaults.
            wire["temperature"] = 0
            wire["top_p"] = 1
            wire["max_tokens"] = min(wire.get("max_tokens", 4096), 4096)
            with lock:
                count += 1
                call_id = count
            if call_id > request_limit:
                raise RuntimeError("Phase D request budget exhausted")
            # SDK-internal retries also count. Observe only this provider's
            # actual HTTP requests; never headers, URL query, or client secrets.
            client = self._client._client
            if not getattr(client, "_phase_d_observed", False):
                async def http_request(request):
                    nonlocal http_count
                    with lock:
                        http_count += 1
                        number = http_count
                    if number > request_limit:
                        raise RuntimeError("Phase D HTTP request budget exhausted")
                    append_record(evidence / "http_requests.jsonl", {"event": "actual_http_request", "request_number": number, "method": request.method, "host": request.url.host, "path": request.url.path})
                client.event_hooks.setdefault("request", []).append(http_request)
                client._phase_d_observed = True
            allowed = ("model", "messages", "temperature", "top_p", "max_tokens", "stream", "stream_options", "response_format", "tools", "tool_choice", "extra_body")
            append_record(evidence / "provider_calls.jsonl", {"event": "request", "call_id": call_id, "wire": {k: wire[k] for k in allowed if k in wire}})
            started = time.monotonic()
            try:
                response = await original(self, **wire)
                def record_response(item):
                    value = {k: getattr(item, k, None) for k in ("id", "model", "created", "system_fingerprint")}
                    usage = getattr(item, "usage", None)
                    value["usage"] = usage.model_dump() if usage is not None else None
                    choices = []
                    for choice in getattr(item, "choices", []):
                        body = getattr(choice, "message", None) or getattr(choice, "delta", None)
                        tools = getattr(body, "tool_calls", None)
                        choices.append({"finish_reason": getattr(choice, "finish_reason", None), "content": getattr(body, "content", None), "tool_calls": [t.model_dump() for t in tools] if tools else None})
                    value["choices"] = choices
                    append_record(evidence / "provider_calls.jsonl", {"event": "response", "call_id": call_id, "elapsed_ms": round((time.monotonic()-started)*1000), "response": value})
                if wire.get("stream"):
                    class ObservedStream:
                        def __init__(self):
                            self.iterator = response.__aiter__()
                        def __aiter__(self):
                            return self
                        async def __anext__(self):
                            item = await self.iterator.__anext__()
                            record_response(item)
                            return item
                        async def close(self):
                            await response.close()
                        async def aclose(self):
                            await response.close()
                        async def __aenter__(self):
                            return self
                        async def __aexit__(self, *args):
                            await response.close()
                        def __getattr__(self, name):
                            return getattr(response, name)
                    return ObservedStream()
                record_response(response)
                return response
            except Exception as exc:
                append_record(evidence / "provider_calls.jsonl", {"event": "failure", "call_id": call_id, "error_type": type(exc).__name__, "status_code": getattr(exc, "status_code", None)})
                raise
        return await real_create(**kwargs)

    AsyncCompletions.create = observed

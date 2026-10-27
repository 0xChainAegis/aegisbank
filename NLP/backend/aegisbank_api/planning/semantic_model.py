"""Model adapter for untrusted SemanticFrame candidates, without financial facts."""

from __future__ import annotations

import json

import httpx

from .llm import PlannerError, _extract_json
from .semantic_contracts import SemanticFrame


class SemanticModel:
    def __init__(self, *, base_url, model, credential="", timeout=20, client=None):
        self.base_url = base_url.rstrip("/")
        self.model, self.credential = model, credential
        self.name = f"llm:{model}"
        self.client = client or httpx.Client(timeout=timeout)

    def analyze(self, instruction, specs):
        payload = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": "你只提出 SemanticFrame/v1 语义候选，不执行工具。返回 JSON。"
                    "每个意图和槽位必须引用原文字符位置（Unicode 字符，start 含/end 不含）。"
                    "保留否定作用域、条件、顺序及未理解片段；不得猜测实体编号、金额、日期或权限。"
                    "无法完整理解时 needs_clarification=true。",
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "instruction": instruction,
                            "intent_catalog": [
                                {
                                    "kind": s.kind,
                                    "slots": s.slot_types,
                                    "examples_patterns": s.patterns,
                                }
                                for s in specs.values()
                            ],
                            "schema": SemanticFrame.model_json_schema(),
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        }
        headers = {"Content-Type": "application/json"}
        if self.credential:
            headers["Authorization"] = f"Bearer {self.credential}"
        try:
            response = self.client.post(
                self.base_url + "/chat/completions", json=payload, headers=headers
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            return SemanticFrame.model_validate_json(_extract_json(content))
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise PlannerError("语义模型调用或候选解析失败") from exc

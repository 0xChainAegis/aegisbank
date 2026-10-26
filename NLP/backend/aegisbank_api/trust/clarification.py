"""Bounded, single-use continuation of an audited clarification request."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta

from ..db import Database


class ClarificationError(ValueError):
    pass


class ClarificationStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def consume(self, run_id: str, *, user_id: str, role: str, answer: str) -> str:
        # Corrections need a fresh complete instruction; concatenating old and new
        # recipients/amounts would leave deterministic extraction ambiguous.
        if re.search(r"不是|不要|取消|改为|换成|instead|don't|do not", answer, re.I):
            raise ClarificationError("补充内容含取消或修改意图，请重新提供完整指令。")
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM audit_log WHERE event='planning_clarification' "
                "AND user_id=? AND json_extract(result_json, '$.run_id')=? "
                "ORDER BY id DESC LIMIT 1",
                (user_id, run_id),
            ).fetchone()
            if row is None or json.loads(row["arguments_json"]).get("role") != role:
                raise ClarificationError("该澄清上下文不可用，请重新发起完整任务。")
            created = datetime.fromisoformat(row["created_at"])
            if datetime.now(UTC) - created > timedelta(minutes=10):
                raise ClarificationError("澄清上下文已过期，请重新发起完整任务。")
            instruction = f"{row['instruction']}\n补充信息：{answer}"
            if len(instruction) > 6000:
                raise ClarificationError("澄清内容过长，请重新提供简短完整指令。")
            if conn.execute(
                "SELECT 1 FROM clarification_uses WHERE run_id=?", (run_id,)
            ).fetchone():
                raise ClarificationError("该澄清上下文已使用，请查询原请求结果。")
            conn.execute("INSERT INTO clarification_uses (run_id) VALUES (?)", (run_id,))
        return instruction

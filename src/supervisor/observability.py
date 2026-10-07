"""src/supervisor/observability.py - 결정 로그를 State 밖(외부 로거)으로 내보낸다.

State에는 trace_id만 남기고, {trace_id, node, decision, reason, ts} 본문은 logger로 적재한다.
main.py가 이 logger에 JSONL 파일 핸들러를 붙인다. LangSmith trace에는 같은 trace_id가 metadata로 들어간다.
"""
import json
import logging
from datetime import datetime, timezone

decision_logger = logging.getLogger("supervisor.decisions")


def log_decision(trace_id: str, node: str, decision, reason: str, **extra) -> None:
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "trace_id": trace_id,
        "node": node,
        "decision": decision,
        "reason": reason,
        **extra,
    }
    decision_logger.info(json.dumps(record, ensure_ascii=False))

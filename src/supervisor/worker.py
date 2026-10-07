"""src/supervisor/worker.py - 하위 에이전트 공통 래퍼

하위 에이전트 노드 함수는 그대로 두고, 실행 결과에 node_status를 붙여 Supervisor에게만 보고한다.
예외가 나면 그래프를 죽이지 않고 failed/node_attempts/last_error로 남겨 Supervisor가 재시도·제외를 판단한다.
"""
from src.supervisor.observability import log_decision


def as_worker(name: str, node_fn):
    def run(state: dict) -> dict:
        try:
            out = node_fn(state) or {}
        except Exception as error:
            attempts = (state.get("node_attempts") or {}).get(name, 0) + 1
            print(f"❌ [{name}] 실행 실패 ({attempts}회차): {error}")
            log_decision(state.get("trace_id", "-"), name, "failed", str(error), attempts=attempts)
            return {
                "node_status": {name: "failed"},
                "node_attempts": {name: attempts},
                "last_error": f"{name}: {error}",
            }
        return {**out, "node_status": {name: "done"}}

    run.__name__ = name
    return run

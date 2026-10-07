# evidence_audit Supervisor 승격

## 목표

조사 워커는 Supervisor와만 통신한다. 워커 사이 엣지는 없다. `evidence_audit`이 Supervisor다. 이 노드가 수집된 관점과 근거 충분성을 State에 쓰고, `add_conditional_edges`의 라우터는 그 판단만 읽어 다음 노드를 고른다.

## 그래프

```text
START → evidence_audit
paper_analysis → evidence_audit
market_research → evidence_audit
stakeholder_research → evidence_audit
evidence_audit --route_supervisor--> paper_analysis | market_research | stakeholder_research | evaluation_synthesis
evaluation_synthesis → report_generation → END
```

금지하는 엣지: `START → paper_analysis`, `START → market_research`, `market_research → stakeholder_research`, `paper_analysis → evidence_audit`를 조건부로 닫는 `route_after_paper`.

같은 스텝에서 병렬 워커가 Supervisor로 돌아오면 LangGraph 1.2.12는 Supervisor를 한 번만 실행한다. `defer=True`는 쓰지 않는다. 그 플래그는 실행 종료 시점까지 노드를 미룬다.

## 역할

`evidence_audit`은 R1–R4 정적 검사 후, 통과한 Claim만 R5를 본다. 이 검사는 유지한다. 재시도 횟수로 라우팅하거나 Claim을 확정하지 않는다.

판단은 `supervisor` 키에 덮어쓴다.

```python
{
    "sufficient": bool,
    "collect": list[str],   # "paper" | "market" | "stakeholder"
    "rework": list[str],
    "reason": str,
    "dispatched": list[str],  # 이미 재작업을 지시한 issue 지문
}
```

`route_supervisor`는 `collect`와 `rework`를 노드 이름으로 바꾼다. 둘 다 비어 있으면 `evaluation_synthesis`다. 라우터는 관점 순서, `retry_count`, `audit.issues`를 보지 않는다.

## 판단

관점이 수집됐는지는 State로만 본다.

- paper: `tech_sw`, `tech_hw`, `domain` 중 하나가 비어 있지 않음
- market: `market`이 비어 있지 않음
- stakeholder: `stakeholder`가 비어 있지 않음

비어 있는 관점은 `collect`다. market이 비어 있으면 stakeholder는 `collect`에 넣지 않는다. market 결과는 State에 남고, stakeholder는 Supervisor가 그 다음에 호출한다. 이것은 워커 간 통신이 아니다.

열린 issue의 지문은 `claim_id|rule|action`이다. 지문이 `dispatched`에 없으면 해당 관점을 `rework`에 넣고 지문을 기록한다. Claim 상태는 `flagged`다. 같은 지문이 재작업 뒤에 다시 있으면 그 Claim을 확정하고 재작업하지 않는다. R5는 `rejected`, 그 외는 `insufficient`다. 횟수 한도가 아니다.

`collect`와 `rework`가 모두 없고 필요한 관점이 있으면 `sufficient`다. 확정된 근거 공백이 있어도 보고서는 진행한다. `report_generation`은 Supervisor의 목적지가 아니다.

`retry_count` 키는 기존 State 계약으로 남긴다. Supervisor는 이 값을 쓰지 않는다.

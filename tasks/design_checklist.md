# 설계서 기준 작업별 Checklist (인덱스)

> **기준 문서**: [`KV_cache_최적화_기술_평가_설계서_최종.md`](../KV_cache_최적화_기술_평가_설계서_최종.md)  
> **체크는 이 파일이 아니라 자기 `role_*.md`에서만 한다.** 전원가 이 파일을 수정하면 Git 충돌이 난다.

| 담당 | 체크리스트 위치 | 전담 경로 (이것만 수정) |
| --- | --- | --- |
| A | [`role_A_architect_orchestration.md`](role_A_architect_orchestration.md) §7 | `src/state.py`, `src/graph.py`, `src/config.py` (LLM 키), `tests/mock_data.py`, `tests/test_smoke.py`, `main.py`, `README.md` |
| B | [`role_B_agentic_rag.md`](role_B_agentic_rag.md) §7 | `src/rag/**`, `tests/test_rag.py`, `data/papers/`, `data/faiss_index/`, `data/eval_queries.json` |
| C | [`role_C_web_research.md`](role_C_web_research.md) §7 | `src/research/**`, `tests/test_research.py` |
| D | [`role_D_fast_fail_audit.md`](role_D_fast_fail_audit.md) §7 | `src/audit/**`, `tests/test_audit.py` |
| E | [`role_E_synthesis_report.md`](role_E_synthesis_report.md) §7 | `src/synthesis/**`, `tests/test_synthesis.py` |

공통 항목(설계 1.4 · 3.7 · 3.8)은 각 role md에 **복제**되어 있다. 자기 전담 파일·프롬프트·산출물에만 적용하고, 남의 파일을 고쳐서 “공통을 맞추지” 않는다.

---

## 충돌 방지 Freeze (전원 준수)

병렬 개발 중 Git 충돌과 State upsert 충돌을 막기 위한 경계다. 어기면 merge와 런타임이 같이 깨진다.

### 파일

- 위 표의 **전담 경로 밖은 읽기만**. `src/state.py` / `src/graph.py` / `main.py` / `tests/mock_data.py` 는 A만.
- `src/config.py`: A는 API 키·LLM 모델명. B는 벤치 확정 후에만 `EMBEDDING_MODEL` 한 줄. 그 외 키 금지.
- `README.md`는 A만. B의 실측 숫자는 `src/rag/` 로그·체크리스트에 남기고, Phase 3에 A가 Retrieval 절에 옮긴다.
- `tasks/common.md`, `tasks/design_checklist.md` 는 Phase 2에 체크/수정하지 않는다.

### State 쓰기 키

| 키 | Writer |
| --- | --- |
| `selected` | `main.py` (A). 조사 노드 반환 금지 |
| `tech_sw`, `tech_hw`, `domain` | B만 |
| `market` | C `market_research`만 |
| `stakeholder` | C `stakeholder_research`만 |
| `claims` / `evidence` / `sources` | B, C가 **자기 ID만** upsert. D는 **status 패치만**. E는 신규 Claim 금지 |
| `audit`, `retry_count` | D만 |
| `trl`, `synthesis` | E만 |
| `report` | E만 |

### Claim / Evidence / Source ID (upsert 키 충돌 방지)

같은 `id`가 두 노드에서 나오면 나중에 실행된 쪽이 덮어쓴다.

| 담당 | Claim ID | Evidence / Source |
| --- | --- | --- |
| B | `DOM-01`~`DOM-12`, `MAT-R01`~`MAT-R02` | `EV-DOM-*`, `EV-MAT-R*`, `SRC-PAPER-KIVI`, `SRC-PAPER-CXL-PNM` |
| C | `MKT-01`~`MKT-08`, `STK-01`~`STK-04`, `MAT-A01`~`MAT-A02` | `EV-MKT-*`, `EV-STK-*`, `EV-MAT-A*`, `SRC-MKT-*`, `SRC-STK-*` |
| D | 신규 ID 금지. 기존 Claim `status`만 | 신규 evidence/source 금지 |
| E | 신규 ID 금지 | 신규 금지 |
| A Mock | `DOM-01`, `MKT-01` 수준만. 실노드 ID 체계를 바꾸지 않음 | `EV-01`/`SRC-01`은 mock 전용 |

`tech` 필드 값은 `"KIVI"` 또는 `"CXL-PNM"`만. 계열명은 `selected.families` / `market` 딕셔너리.

---
*인덱스만 유지. 체크박스는 각 role md §7.*

"""app.py - Streamlit Interactive Dashboard for LangGraph Multi-Agent Evaluation"""
import time
import json
import streamlit as st
from pathlib import Path

from src.graph import build_evaluation_graph
from src.config import (
    REPORT_OUTPUT_PATH,
    REPORT_MD_PATH,
    REPORT_PDF_PATH,
    DEFAULT_LLM_MODEL,
    JUDGE_LLM_MODEL,
    FAISS_INDEX_DIR,
)
from src.synthesis.pdf_export import convert_markdown_to_pdf
from main import INITIAL_INPUT_STATE
from tests.mock_data import MOCK_STATE

st.set_page_config(
    page_title="KV Cache 최적화 기술 다관점 평가 시스템",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("⚡ KV Cache 최적화 기술 다관점 평가 시스템")
st.caption("LangGraph 멀티 에이전트 기반 KIVI (SW 2-bit 양자화) vs CXL-PNM (HW CXL 근접 처리) 심층 평가")

# ----------------- Sidebar -----------------
with st.sidebar:
    st.header("⚙️ 실행 설정")
    st.markdown("### 🎯 평가 대상 기술")
    st.info(
        "• **SW**: KIVI (KV Quantization)\n\n"
        "• **HW**: CXL-PNM (CXL Memory Expansion)"
    )

    st.markdown("### 🤖 시스템 환경")
    st.text(f"기본 LLM: {DEFAULT_LLM_MODEL}")
    st.text(f"심사 LLM: {JUDGE_LLM_MODEL}")
    st.text(f"FAISS 경로: {Path(FAISS_INDEX_DIR).name}")

    st.markdown("---")
    st.markdown("### 🚀 실행 제어")
    run_btn = st.button("▶️ 파이프라인 전체 실행", type="primary", use_container_width=True)
    load_mock_btn = st.button("📦 Mock 데이터 즉시 불러오기", use_container_width=True)

# Session state initialization
if "final_state" not in st.session_state:
    st.session_state["final_state"] = None
if "run_logs" not in st.session_state:
    st.session_state["run_logs"] = []

# Action: Load Mock
if load_mock_btn:
    st.session_state["final_state"] = MOCK_STATE
    st.session_state["run_logs"] = ["📦 Mock State가 메모리에 성공적으로 로드되었습니다."]
    st.toast("Mock State 로드 완료!", icon="📦")

# Action: Run Pipeline
if run_btn:
    st.session_state["run_logs"] = []
    progress_bar = st.progress(0, text="파이프라인 초기화 중...")
    
    node_labels = {
        "market_research": "📈 [시장성 조사] 시장 채택 및 기술 장벽 조사",
        "paper_analysis": "📄 [원문 분석] 논문 기반 메커니즘 및 도메인 분석",
        "stakeholder_research": "👥 [이해관계자] 4대 핵심 Actor 영향 분석",
        "evidence_audit": "🛡️ [근거 검증] R1~R4 정적 룰 및 R5 심사기 검증",
        "evaluation_synthesis": "⚖️ [평가 종합] TRL 이원화 및 트레이드오프 종합",
        "report_generation": "📝 [보고서 생성] 8대 필수 목차 Jinja2 렌더링",
    }
    
    total_expected_steps = 6
    step_count = 0

    try:
        start_time = time.time()
        graph = build_evaluation_graph()
        
        status_box = st.status("파이프라인 실행 중...", expanded=True)
        with status_box:
            for chunk in graph.stream(INITIAL_INPUT_STATE, stream_mode="updates"):
                for node_name, node_output in chunk.items():
                    step_count += 1
                    label = node_labels.get(node_name, f"노드 실행: {node_name}")
                    st.write(label)
                    st.session_state["run_logs"].append(label)
                    progress = min(step_count / total_expected_steps, 1.0)
                    progress_bar.progress(progress, text=f"{label} 완료")
            
            # 최종 State 확보
            final_state = graph.invoke(INITIAL_INPUT_STATE)
            elapsed = time.time() - start_time
            REPORT_MD_PATH.write_text(final_state.get("report") or "", encoding="utf-8")
            if REPORT_OUTPUT_PATH.suffix.lower() == ".pdf":
                convert_markdown_to_pdf(final_state.get("report") or "", REPORT_OUTPUT_PATH)
            else:
                REPORT_OUTPUT_PATH.write_text(final_state.get("report") or "", encoding="utf-8")
            status_box.update(label=f"✅ 파이프라인 실행 완료! (소요 시간: {elapsed:.2f}초)", state="complete", expanded=False)
            
        progress_bar.progress(1.0, text="완료")
        st.session_state["final_state"] = final_state
        st.toast(f"파이프라인 실행 완료 ({elapsed:.2f}초)", icon="✅")
    except Exception as e:
        st.error(f"파이프라인 실행 중 오류 발생: {e}")

# ----------------- Main Display -----------------
state = st.session_state.get("final_state")

if not state:
    st.info("👈 사이드바에서 **[▶️ 파이프라인 전체 실행]** 또는 **[📦 Mock 데이터 즉시 불러오기]**를 클릭하세요.")
else:
    tab1, tab2, tab3, tab4 = st.tabs([
        "📑 최종 보고서",
        "🛡️ Claims & 검증(Audit)",
        "📊 TRL & 기술 평가",
        "🔍 Raw State(JSON)"
    ])

    # ----------------- Tab 1: Final Report -----------------
    with tab1:
        st.subheader("📑 최종 평가 보고서 (final_evaluation_report.md)")
        report_text = state.get("report", "")
        if report_text:
            col_md, col_pdf, col_info = st.columns([1, 1, 3])
            with col_md:
                st.download_button(
                    label="📥 보고서 (.md) 다운로드",
                    data=report_text,
                    file_name="final_evaluation_report.md",
                    mime="text/markdown",
                    use_container_width=True,
                )
            with col_pdf:
                pdf_bytes = b""
                if REPORT_PDF_PATH.exists():
                    pdf_bytes = REPORT_PDF_PATH.read_bytes()
                st.download_button(
                    label="📄 보고서 (.pdf) 다운로드",
                    data=pdf_bytes,
                    file_name="final_evaluation_report.pdf",
                    mime="application/pdf",
                    disabled=len(pdf_bytes) == 0,
                    use_container_width=True,
                )
            with col_info:
                st.caption(f"보고서 크기: {len(report_text):,} 자 | PDF 저장 경로: `{REPORT_OUTPUT_PATH}`")

            st.divider()
            st.markdown(report_text)
        else:
            st.warning("생성된 보고서 내용이 없습니다.")

    # ----------------- Tab 2: Claims & Audit -----------------
    with tab2:
        st.subheader("🛡️ Fact & Claim 검증 현황")
        
        claims = state.get("claims", [])
        audit = state.get("audit", {})
        issues = audit.get("issues", [])
        retry_counts = state.get("retry_count", {})

        col_c1, col_c2, col_c3 = st.columns(3)
        col_c1.metric("총 추출 Claim 수", f"{len(claims)}개")
        col_c2.metric("감지된 Audit Issue", f"{len(issues)}건")
        col_c3.metric(
            "재시도 횟수",
            f"Paper: {retry_counts.get('paper', 0)} | Mkt: {retry_counts.get('market', 0)} | Stk: {retry_counts.get('stakeholder', 0)}"
        )

        st.markdown("### 📋 Claim 세부 목록")
        if claims:
            table_data = []
            for c in claims:
                table_data.append({
                    "ID": c.get("id"),
                    "관점": c.get("perspective"),
                    "대상 기술": c.get("tech"),
                    "종류(Kind)": c.get("kind"),
                    "상태(Status)": c.get("status"),
                    "주장 내용(Statement)": c.get("statement"),
                    "근거 수": len(c.get("evidence_ids", [])),
                    "반박근거 수": len(c.get("counter_evidence_ids", [])),
                })
            st.dataframe(table_data, use_container_width=True)
        else:
            st.info("등록된 Claim이 없습니다.")

        st.markdown("### 🚨 검증 이슈(Audit Issues)")
        if issues:
            st.warning(f"총 {len(issues)}개의 정적/동적 검증 이슈가 발견되었습니다.")
            st.table(issues)
        else:
            st.success("✅ 모든 Claim이 정적 룰(R1~R4) 및 심사 기준을 통과했습니다.")

    # ----------------- Tab 3: TRL & Metrics -----------------
    with tab3:
        st.subheader("📊 TRL (기술 성숙도) 평가 결과")
        trl = state.get("trl", {})

        if trl:
            c1, c2 = st.columns(2)
            kivi_trl = trl.get("KIVI", {})
            cxl_trl = trl.get("CXL-PNM", {})

            with c1:
                st.markdown("#### 🔹 KIVI (SW 2-bit Quantization)")
                st.metric("Tech TRL", kivi_trl.get("tech_trl", "N/A"))
                st.metric("Family TRL", kivi_trl.get("family_trl", "N/A"))
                st.metric("신뢰도(Confidence)", kivi_trl.get("confidence", "N/A"))
                with st.expander("연구 근거 (Research Evidence)"):
                    for e in kivi_trl.get("research_evidence", []):
                        st.write(f"- {e}")
                with st.expander("채택 근거 (Adoption Evidence)"):
                    for e in kivi_trl.get("adoption_evidence", []):
                        st.write(f"- {e}")

            with c2:
                st.markdown("#### 🔸 CXL-PNM (HW Near-Memory)")
                st.metric("Tech TRL", cxl_trl.get("tech_trl", "N/A"))
                st.metric("Family TRL", cxl_trl.get("family_trl", "N/A"))
                st.metric("신뢰도(Confidence)", cxl_trl.get("confidence", "N/A"))
                with st.expander("연구 근거 (Research Evidence)"):
                    for e in cxl_trl.get("research_evidence", []):
                        st.write(f"- {e}")
                with st.expander("채택 근거 (Adoption Evidence)"):
                    for e in cxl_trl.get("adoption_evidence", []):
                        st.write(f"- {e}")
        else:
            st.info("TRL 데이터가 생성되지 않았습니다.")

        st.markdown("### ⚖️ 기술 비교 및 종합 (Synthesis)")
        synthesis = state.get("synthesis", {})
        if synthesis:
            st.json(synthesis)
        else:
            st.info("종합 데이터가 없습니다.")

    # ----------------- Tab 4: Raw State -----------------
    with tab4:
        st.subheader("🔍 LangGraph OverallState 전체 데이터")
        st.caption("그래프 전체에서 공유 및 축적된 14개 키의 전체 State 덤프입니다.")
        st.json(state)

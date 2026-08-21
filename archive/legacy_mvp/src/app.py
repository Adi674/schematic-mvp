"""
Streamlit Frontend Interface.
Interactive UI for uploading schematic images, submitting queries,
and viewing color-coded compliance report tables.
"""

import sys
import os

# Ensure project root is in sys.path when running via Streamlit
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import streamlit as st
from src.graph.build_graph import run_pipeline

st.set_page_config(
    page_title="Hardware Schematic Review Assistant",
    page_icon="⚡",
    layout="wide"
)

st.title("⚡ Hardware Schematic Review Assistant MVP")
st.caption("Infineon TLE987x/6x Deterministic Compliance Verification & RAG Engine")

col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("Input & Options")
    uploaded_file = st.file_uploader("Upload Schematic Snippet / Image", type=["png", "jpg", "jpeg", "pdf"])

    image_bytes = None
    if uploaded_file is not None:
        image_bytes = uploaded_file.read()
        st.image(image_bytes, caption="Uploaded Schematic Snippet", use_container_width=True)

    question = st.text_area(
        "Ask a Question or Request Schematic Audit:",
        value="Review this schematic snippet for TLE987x pin compliance",
        height=100
    )

    submit_btn = st.button("Run Verification & Audit", type="primary")

with col2:
    st.subheader("Audit Results & Guidelines")
    if submit_btn:
        with st.spinner("Processing pipeline: Router -> Rule Engine -> RAG -> Composer..."):
            res = run_pipeline(question=question, image=image_bytes)

            st.success(f"Execution complete. Routes active: `{res['routes']}`")

            # Display markdown response
            st.markdown(res["final_answer"])

            # Display color-coded table if checklist report exists
            if res["checklist_report"]:
                st.subheader("Structured Compliance Checklist")
                for r in res["checklist_report"]:
                    status = r["status"]
                    comp = r["component"]
                    pin = r["pin"]
                    reason = r["reason"]

                    if status == "PASS":
                        st.success(f"✅ **PASS** | Component: `{comp}` (Pin: `{pin}`) — {reason}")
                    elif "MARGINAL" in status:
                        st.warning(f"⚠️ **{status}** | Component: `{comp}` (Pin: `{pin}`) — {reason}")
                    elif "FAIL" in status:
                        st.error(f"❌ **{status}** | Component: `{comp}` (Pin: `{pin}`) — {reason}")
                    else:
                        st.info(f"ℹ️ **{status}** | Component: `{comp}` (Pin: `{pin}`) — {reason}")

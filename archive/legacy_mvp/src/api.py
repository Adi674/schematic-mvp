"""
FastAPI Server Backend.
Exposes POST /ask endpoint for schematic review and Q&A requests.
"""

import sys
import os

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi import FastAPI, File, UploadFile, Form
from typing import Optional
from src.graph.build_graph import run_pipeline

app = FastAPI(
    title="Hardware Schematic Review Assistant MVP",
    description="Deterministic rule engine + RAG compliance review system for Infineon TLE987x/6x",
    version="2.0.0"
)


@app.get("/")
def read_root():
    return {"status": "online", "system": "Hardware Schematic Review Assistant MVP v2"}


@app.post("/ask")
async def ask_endpoint(
    question: str = Form(...),
    file: Optional[UploadFile] = File(None)
):
    filename = file.filename if file else "None"
    print(f"\n{'='*25} [FASTAPI ENDPOINT: POST /ask] {'='*25}")
    print(f"Incoming Request: Question='{question}' | Attached File='{filename}'")

    image_bytes = None
    if file:
        image_bytes = await file.read()

    pipeline_result = run_pipeline(question=question, image=image_bytes)

    print(f"[FASTAPI ENDPOINT RESPONSE READY] Routes: {pipeline_result['routes']} | Report items: {len(pipeline_result.get('checklist_report', []))}")
    print(f"{'='*75}\n")

    return {
        "question": pipeline_result["question"],
        "routes": pipeline_result["routes"],
        "final_answer": pipeline_result["final_answer"],
        "checklist_report": pipeline_result["checklist_report"],
        "sanity_flags": pipeline_result["sanity_flags"]
    }


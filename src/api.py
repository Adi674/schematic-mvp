"""
FastAPI application for Phase 3 — Simple RAG Chat service.
Connects HybridRetriever (Chroma + BM25) to Mistral Small.
"""

from src.schematic.crop_handler import handle_crop_message
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from src.retrieval.hybrid_retriever import HybridRetriever
from src.retrieval.retrieval_schema import QueryResult
from src.llm import call_mistral_text, MistralAPIError
from src.schematic.reviewer import SchematicReviewService
from src.schematic.schema import (
    ParseCropResponse,
    ReviewCropRequest,
    ReviewCropResponse
)
from src.schematic.semantic_schema import SemanticCropResponse
from src.schematic.explain_schema import ExplainCropResponse
from fastapi import File, UploadFile, Form

app = FastAPI(title="Schematic RAG Chat & Review API", version="1.0.0")

# Instantiate retrieval layer & schematic review service
retriever = HybridRetriever()
schematic_service = SchematicReviewService()

SYSTEM_PROMPT = (
    "You are a hardware design reference assistant.\n\n"
    "Answer the user's question using only the provided reference evidence.\n"
    "Do not invent, assume, or add technical requirements, values, specifications, "
    "or design rules that are not supported by the evidence.\n"
    "You may paraphrase the evidence, but preserve the original technical scope and relationships.\n"
    "Do not merge separate components, pins, circuits, or requirements just because they "
    "are related to the user's question.\n"
    "When multiple related components are mentioned, explain each one separately and "
    "identify the component/pin it applies to.\n"
    "Distinguish between what the reference explicitly states and any broader interpretation.\n"
    "If the evidence is insufficient, say that the reference material does not provide "
    "enough information.\n"
    "Include the relevant section, table, figure, or page when available."
)


class ChatRequest(BaseModel):
    message: str


class SourceItem(BaseModel):
    unit_id: str
    page: int
    section: str
    unit_type: str
    score: float
    source_objects: List[str] = Field(default_factory=list)


class RetrievalDiagnostics(BaseModel):
    method: str = "hybrid_rrf"
    top_k: int = 5


class ChatResponse(BaseModel):
    answer: str
    sources: List[SourceItem]
    retrieval: RetrievalDiagnostics


def build_context(results: list[QueryResult]) -> str:
    """Formats top retrieval units into standard REFERENCE EVIDENCE section."""
    blocks = []
    for idx, res in enumerate(results, start=1):
        unit = res.unit
        unit_type_str = unit.unit_type.value if hasattr(unit.unit_type, "value") else str(unit.unit_type)
        block = (
            f"[Source {idx}]\n"
            f"Section: {unit.section_number}\n"
            f"Page: {unit.page_start}\n"
            f"Type: {unit_type_str}\n\n"
            f"{unit.text_content.strip()}"
        )
        blocks.append(block)
    return "\n\n".join(blocks)


def build_user_prompt(query: str, context: str) -> str:
    """Constructs the user prompt combining query and retrieved evidence context."""
    return f"{query}\n\nReference evidence:\n{context}"


@app.get("/health")
def health():
    """Health check endpoint to verify server status."""
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    """
    RAG Chat endpoint:
    1. Validates input
    2. Retrieves top-5 evidence via HybridRetriever
    3. Builds reference context
    4. Calls Mistral LLM
    5. Returns answer + source citations + retrieval diagnostics
    """
    query = request.message.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    try:
        results = retriever.search(query=query, top_k=5)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Retrieval failure: {str(e)}")

    context = build_context(results)
    user_prompt = build_user_prompt(query, context)

    try:
        answer = call_mistral_text(system_prompt=SYSTEM_PROMPT, user_prompt=user_prompt)
    except MistralAPIError as me:
        raise HTTPException(status_code=me.status_code, detail=me.message)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM API failure: {str(e)}")

    sources = []
    for r in results:
        unit_type_val = r.unit.unit_type.value if hasattr(r.unit.unit_type, "value") else str(r.unit.unit_type)
        src_objs = r.unit.source_object_ids or r.source_object_ids
        sources.append(
            SourceItem(
                unit_id=r.unit_id,
                page=r.unit.page_start,
                section=r.unit.section_number,
                unit_type=unit_type_val,
                score=round(r.score, 4),
                source_objects=src_objs,
            )
        )

    return ChatResponse(
        answer=answer,
        sources=sources,
        retrieval=RetrievalDiagnostics(method="hybrid_rrf", top_k=len(results))
    )


# --- Two-Stage Schematic Crop Review Endpoints ---

@app.post("/schematic/parse/crop", response_model=SemanticCropResponse)
async def parse_schematic_crop(
    image: UploadFile = File(...),
    device_hint: Optional[str] = Form(None)
):
    if not image.content_type or not image.content_type.startswith("image/"):
        raise HTTPException(
            status_code=400,
            detail="File uploaded must be an image."
        )

    try:
        contents = await image.read()

        from PIL import Image
        import io

        img = Image.open(io.BytesIO(contents))

        result = schematic_service.parse_crop(
            image_bytes=contents,
            filename=image.filename or "crop.png",
            width=img.width,
            height=img.height,
            device_hint=device_hint,
            mime_type=image.content_type or "image/png",
        )

        return result

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Schematic parse error: {exc}"
        )


@app.post("/schematic/review/crop/{review_id}", response_model=ReviewCropResponse)
def review_schematic_crop(
    review_id: str,
    request: ReviewCropRequest
):
    """
    Stage 2: Executes the MVP Generic Review Framework & RAG reference comparison
    for the confirmed selected section and returns findings.
    """
    try:
        return schematic_service.review_crop(
            review_id=review_id,
            selected_section=request.selected_section
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Review session '{review_id}' not found.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Schematic review error: {str(e)}")


@app.post("/schematic/explain/crop/{review_id}", response_model=ExplainCropResponse)
def explain_schematic_crop(review_id: str):
    """
    Scenario A (WS4): explains every resolved component in a previously
    parsed crop, grounded against the HDG via net resolution + hybrid retrieval.
    """
    try:
        return schematic_service.explain_crop(review_id=review_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Review session '{review_id}' not found.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Schematic explain error: {str(e)}")

@app.post("/schematic/crop")
async def crop_chat(
    image: UploadFile = File(...),
    message: str = Form(...),
    device_hint: Optional[str] = Form(None),
):
    """
    Single-call chat entry point: image + free-text message in, routed result
    out. No separate parse-then-explain/review round trip needed by the caller.
    Response shape depends on "intent": "explain" -> ExplainCropResponse under
    "result", "missing" -> MissingCropResponse under "result".
    """
    if not image.content_type or not image.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File uploaded must be an image.")
 
    try:
        contents = await image.read()
 
        from PIL import Image
        import io
 
        img = Image.open(io.BytesIO(contents))
 
        return handle_crop_message(
            image_bytes=contents,
            message=message,
            filename=image.filename or "crop.png",
            width=img.width,
            height=img.height,
            device_hint=device_hint,
            mime_type=image.content_type or "image/png",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Schematic crop-chat error: {exc}")
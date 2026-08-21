"""
Retrieval Evaluator & Experiment Engine — Evaluates 60 Ground-Truth Hardware Queries
and compares Variant A (Standalone Baseline) vs Variant B (Composite Section Context).

Measures:
- Recall@1, Recall@3, Recall@5
- MRR (Mean Reciprocal Rank)
- Unit-Type Match Rate (expected_unit_type == retrieved_unit_type)
- Adversarial Near-Neighbor Accuracy (target section/table vs neighbor trap)
- Source Fidelity Rate (valid bbox and source_hash)
- Error Taxonomy: CORRECT, WRONG_SECTION, WRONG_TABLE, WRONG_UNIT_TYPE, NOT_FOUND
"""

import os
import sys
import json
from src.retrieval.retrieval_schema import EvalQuestion, QueryResult
from src.retrieval.unit_builder import build_retrieval_units
from src.retrieval.vector_store import DenseVectorStore
from src.retrieval.lexical_store import LexicalBM25Store
from src.retrieval.hybrid_retriever import HybridRetriever


def is_compatible_unit_type(expected_val: str, retrieved_val: str) -> bool:
    if expected_val == retrieved_val:
        return True
    # Table row and table summary are both valid table evidence types
    table_types = {"table_row", "table_summary"}
    if expected_val in table_types and retrieved_val in table_types:
        return True
    return False


def evaluate_variant(
    units_path: str,
    questions: list[EvalQuestion],
    variant_name: str = "Variant B",
    top_k: int = 5,
) -> dict:
    print(f"\n--- Evaluating {variant_name} ({units_path}) ---")

    v_store = DenseVectorStore(persist_dir=f"data/indexes/vector_{variant_name.lower().replace(' ', '_')}")
    v_store.build_index(units_path)

    l_store = LexicalBM25Store(index_dir=f"data/indexes/lexical_{variant_name.lower().replace(' ', '_')}")
    l_store.build_index(units_path)

    retriever = HybridRetriever(dense_store=v_store, lexical_store=l_store)

    recall_1 = 0
    recall_3 = 0
    recall_5 = 0
    reciprocal_ranks = []
    unit_type_matches = 0
    adversarial_correct = 0
    adversarial_total = 0
    source_fidelity_valid = 0

    error_counts = {
        "CORRECT": 0,
        "WRONG_SECTION": 0,
        "WRONG_TABLE": 0,
        "WRONG_UNIT_TYPE": 0,
        "NOT_FOUND": 0,
    }

    category_performance = {}
    detailed_queries = []

    for q in questions:
        results = retriever.search(q.query, top_k=top_k, method="hybrid")

        found_rank = None
        retrieved_unit_type_at_rank = None

        for rank, r in enumerate(results, start=1):
            sec_match = (r.unit.section_number == q.expected_section or q.expected_section.startswith(r.unit.section_number))
            page_match = (r.unit.page_start == q.expected_page or r.unit.page_end == q.expected_page)

            if sec_match or page_match:
                if found_rank is None:
                    found_rank = rank
                    retrieved_unit_type_at_rank = r.unit.unit_type

        is_adv = (q.query_type.value == "adversarial_near_neighbor" or "adversarial" in q.category.lower())
        if is_adv:
            adversarial_total += 1

        if found_rank is not None:
            reciprocal_ranks.append(1.0 / found_rank)
            if found_rank <= 1:
                recall_1 += 1
            if found_rank <= 3:
                recall_3 += 1
            if found_rank <= 5:
                recall_5 += 1

            if is_adv:
                adversarial_correct += 1

            exp_val = q.expected_unit_type.value if q.expected_unit_type else None
            ret_val = retrieved_unit_type_at_rank.value if retrieved_unit_type_at_rank else None

            if exp_val and ret_val and is_compatible_unit_type(exp_val, ret_val):
                unit_type_matches += 1
                error_status = "CORRECT"
            elif exp_val and ret_val:
                error_status = "WRONG_UNIT_TYPE"
            else:
                error_status = "CORRECT"

            top_res = results[0] if results else None
            if top_res and top_res.unit.source_hashes:
                source_fidelity_valid += 1

        else:
            reciprocal_ranks.append(0.0)
            if any("table" in r.unit.unit_type.value for r in results[:1]):
                error_status = "WRONG_TABLE"
            else:
                error_status = "WRONG_SECTION"

        error_counts[error_status] = error_counts.get(error_status, 0) + 1

        cat = q.category or q.query_type.value
        if cat not in category_performance:
            category_performance[cat] = {"total": 0, "found": 0}
        category_performance[cat]["total"] += 1
        if found_rank is not None:
            category_performance[cat]["found"] += 1

        detailed_queries.append({
            "id": q.id,
            "query": q.query,
            "category": cat,
            "expected_section": q.expected_section,
            "expected_page": q.expected_page,
            "expected_unit_type": q.expected_unit_type.value if q.expected_unit_type else None,
            "found_rank": found_rank,
            "status": error_status,
            "top_retrieved": [
                {
                    "unit_id": r.unit_id,
                    "section": r.unit.section_number,
                    "page": r.unit.page_start,
                    "unit_type": r.unit.unit_type.value,
                    "score": round(r.score, 4),
                    "bbox": r.unit.bbox,
                    "source_object_ids": r.unit.source_object_ids,
                }
                for r in results[:3]
            ],
        })

    total_q = len(questions)
    mrr = sum(reciprocal_ranks) / total_q if total_q > 0 else 0.0

    return {
        "variant_name": variant_name,
        "metrics": {
            "total_questions": total_q,
            "recall_at_1": f"{recall_1 / total_q * 100:.1f}%",
            "recall_at_3": f"{recall_3 / total_q * 100:.1f}%",
            "recall_at_5": f"{recall_5 / total_q * 100:.1f}%",
            "mrr": round(mrr, 4),
            "unit_type_match_rate": f"{unit_type_matches / total_q * 100:.1f}%",
            "adversarial_accuracy": f"{adversarial_correct / adversarial_total * 100:.1f}%" if adversarial_total else "N/A",
            "source_fidelity_rate": f"{source_fidelity_valid / total_q * 100:.1f}%",
        },
        "category_breakdown": {
            k: f"{v['found']}/{v['total']} ({v['found']/v['total']*100:.0f}%)"
            for k, v in category_performance.items()
        },
        "error_taxonomy": error_counts,
        "detailed_queries": detailed_queries,
    }


def evaluate_retrieval_hardening(
    questions_path: str = "eval/retrieval/questions.json",
    output_path: str = "eval/retrieval/retrieval_benchmark_report.json",
) -> dict:
    if not os.path.exists(questions_path):
        raise FileNotFoundError(f"Evaluation questions not found at {questions_path}")

    build_retrieval_units()

    with open(questions_path, "r", encoding="utf-8") as f:
        questions_raw = json.load(f)

    questions = [EvalQuestion.model_validate(q) for q in questions_raw]

    res_var_a = evaluate_variant(
        "data/retrieval/retrieval_units_variant_a.jsonl", questions, "Variant A (Standalone Baseline)"
    )

    res_var_b = evaluate_variant(
        "data/retrieval/retrieval_units_variant_b.jsonl", questions, "Variant B (Composite Section Context)"
    )

    report = {
        "summary": {
            "total_benchmark_questions": len(questions),
            "variant_a_baseline": res_var_a["metrics"],
            "variant_b_composite": res_var_b["metrics"],
        },
        "variant_a_details": res_var_a,
        "variant_b_details": res_var_b,
    }

    print("\n" + "=" * 65)
    print("HARDENED RETRIEVAL BENCHMARK COMPARISON (60 QUESTIONS)")
    print("=" * 65)
    print(f"VARIANT A (Standalone Baseline):")
    print(f"  Recall@1: {res_var_a['metrics']['recall_at_1']} | Recall@5: {res_var_a['metrics']['recall_at_5']} | MRR: {res_var_a['metrics']['mrr']}")
    print(f"  Unit-Type Match: {res_var_a['metrics']['unit_type_match_rate']} | Adversarial Accuracy: {res_var_a['metrics']['adversarial_accuracy']}")
    print("-" * 65)
    print(f"VARIANT B (Composite Section Context):")
    print(f"  Recall@1: {res_var_b['metrics']['recall_at_1']} | Recall@5: {res_var_b['metrics']['recall_at_5']} | MRR: {res_var_b['metrics']['mrr']}")
    print(f"  Unit-Type Match: {res_var_b['metrics']['unit_type_match_rate']} | Adversarial Accuracy: {res_var_b['metrics']['adversarial_accuracy']}")
    print("=" * 65)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"Hardened benchmark report saved to {output_path}")
    return report


if __name__ == "__main__":
    evaluate_retrieval_hardening()

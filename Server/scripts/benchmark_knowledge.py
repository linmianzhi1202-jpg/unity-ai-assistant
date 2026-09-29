"""Compare identical queries with vector-only and explicitly enabled API graph retrieval.

The automatic score is a lexical evidence proxy, not a human relevance judgment.
Use --timeout to fix the same retrieval budget for both variants.
"""
import argparse
import asyncio
import hashlib
import json
import re
from pathlib import Path
import statistics
import sys
import time

SERVER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER / "src"))
from core.config import config
from services.tools.rag_tools import arun_knowledge_unified_search, _get_unified_vector_store

async def run(args):
    config.rag_timeout = args.timeout
    raw = args.cases.read_bytes()
    cases = json.loads(raw)
    base = SERVER / "data/base_kb"
    fingerprints = {}
    for path in [base / "chroma_db_v3/chroma.sqlite3", *sorted((base / "lightrag_db_v3_structured").glob("vdb_*.json")), base / "lightrag_db_v3_structured/graph_chunk_entity_relation.graphml", base / "lightrag_db_v3_structured/kv_store_text_chunks.json"]:
        if path.exists():
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            fingerprints[str(path.relative_to(base))] = digest.hexdigest()
    chunks_path = base / "lightrag_db_v3_structured/kv_store_text_chunks.json"
    chunks = json.loads(chunks_path.read_text(encoding="utf-8")) if chunks_path.exists() else {}
    graph_paths = {chunk.get("file_path") for chunk in chunks.values()}
    report = {"dataset_sha256": hashlib.sha256(raw).hexdigest(), "graph_model": config.rag_model,
              "embedding_model": "BAAI/bge-m3", "timeout_seconds": args.timeout,
              "vector_results": 3, "graph_mode": "local", "case_count": len(cases),
              "metric_note": "term_hit is an automatic lexical evidence proxy; source_resolvable checks vector IDs against the collection. Graph reference paths are checked against indexed chunks; semantic answer correctness requires separate review.",
              "human_review": "pending", "index_sha256": fingerprints, "graph_context_tokens": 6000, "graph_entity_tokens": 1500, "graph_relation_tokens": 1500, "rerank": False, "results": []}
    # Warm the shared model before timed queries; preserve all failures in the report.
    warm_started = time.perf_counter()
    await asyncio.to_thread(lambda: _get_unified_vector_store().search("GameObject", n_results=3))
    report["cold_start_seconds"] = round(time.perf_counter() - warm_started, 3)
    warm = await arun_knowledge_unified_search("GameObject", sources=["vector"])
    report["warmup_status"] = warm["source_breakdown"]
    for case in cases:
        for variant, sources in [("vector", ["vector"]), ("vector_graph", ["vector", "api_graph"])]:
            started = time.perf_counter()
            result = await arun_knowledge_unified_search(case["query"], sources=sources)
            elapsed = round((time.perf_counter() - started) * 1000, 2)
            evidence = result.get("merged_answer", "").lower()
            items = result.get("vector_results", [])
            ids = [item["id"] for item in items if item.get("id")]
            resolved = []
            if ids:
                store = _get_unified_vector_store()
                resolved = store.collection.get(ids=ids, include=[])["ids"] if store.collection is not None else []
            graph_context = result.get("api_graph_context") or ""
            references = re.findall(r"^\[\d+\] (.+)$", graph_context, re.MULTILINE)
            report["results"].append({"id": case["id"], "category": case["category"], "query": case["query"],
                "variant": variant, "elapsed_ms": elapsed, "status": result["status"],
                "source_breakdown": result["source_breakdown"], "vector_ids": ids,
                "source_resolvable": len(resolved)/len(ids) if ids else None,
                "graph_references": references, "graph_source_resolvable": sum(ref in graph_paths for ref in references)/len(references) if references else None,
                "term_hit": all(term.lower() in evidence for term in case["expected_terms"]),
                "evidence": result.get("merged_answer", "")})
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"{case['id']} {variant}: {result['status']} {elapsed}ms", flush=True)
    report["summary"] = {}
    for variant in ("vector", "vector_graph"):
        rows = [row for row in report["results"] if row["variant"] == variant]
        latencies = sorted(row["elapsed_ms"] for row in rows)
        trace = [row["source_resolvable"] for row in rows if row["source_resolvable"] is not None]
        graph_trace = [row["graph_source_resolvable"] for row in rows if row["graph_source_resolvable"] is not None]
        successful = [row["elapsed_ms"] for row in rows if row["status"] == "ok"]
        report["summary"][variant] = {"lexical_term_hit_rate": sum(row["term_hit"] for row in rows)/len(rows),
            "p95_latency_ms": latencies[min(len(latencies)-1,int(len(latencies)*.95))],
            "mean_source_resolvable": statistics.mean(trace) if trace else None,
            "mean_graph_source_resolvable": statistics.mean(graph_trace) if graph_trace else None,
            "median_success_latency_ms": statistics.median(successful) if successful else None,
            "non_ok_count": sum(row["status"] != "ok" for row in rows)}
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report["summary"],ensure_ascii=False),flush=True)

if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--cases",type=Path,default=SERVER / "tests/fixtures/retrieval_cases.json")
    parser.add_argument("--output",type=Path,default=SERVER / "tests/reports/knowledge_benchmark.json")
    parser.add_argument("--timeout",type=float,default=60)
    asyncio.run(run(parser.parse_args()))

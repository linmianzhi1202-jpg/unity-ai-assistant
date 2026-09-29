"""Persist search, relation, and scene-plan quality benchmarks."""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


SERVER_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = SERVER_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from services.asset_graph_service import get_asset_relations
from services.asset_library_service import (
    ASSET_RERANK_VERSION,
    DEFAULT_INDEX_DIR,
    active_asset_collection_name,
    load_asset_index_state,
    search_asset_library,
)
from services.asset_scene_plan_service import build_asset_scene_preview


DATA_DIR = SERVER_DIR / "data" / "asset_library"
DEFAULT_CASES = DATA_DIR / "search_benchmark.json"
DEFAULT_RELATION_CASES = DATA_DIR / "relation_benchmark.json"
DEFAULT_SCENE_CASES = DATA_DIR / "scene_plan_benchmark.json"
DEFAULT_REPORT_DIR = DATA_DIR / "benchmark_reports"

SEARCH_TOP1_GATE = 0.95
SEARCH_HIT3_GATE = 0.99
SEARCH_MRR_GATE = 0.97
RELATION_GATE = 0.95
CONSTRAINT_GATE = 1.0
SEARCH_P95_GATE_MS = 1500.0
GRAPH_P95_GATE_MS = 20.0
SCENE_PLAN_GATE = 0.95
SCENE_P95_GATE_MS = 2000.0


def _load_cases(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [dict(item) for item in payload.get("cases", []) if isinstance(item, dict)]


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = (len(ordered) - 1) * percentile
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)


def _benchmark_search(
    cases: list[dict[str, Any]],
    *,
    use_vector: bool,
    expand_relations: bool,
    name: str,
) -> dict[str, Any]:
    if cases:
        search_asset_library(
            cases[0]["query"],
            category=cases[0].get("category", ""),
            top_k=5,
            use_vector=use_vector,
            expand_relations=expand_relations,
        )
    hits = {1: 0, 3: 0, 5: 0}
    precision = {1: 0.0, 3: 0.0, 5: 0.0}
    recall = {1: 0.0, 3: 0.0, 5: 0.0}
    reciprocal_rank = 0.0
    durations: list[float] = []
    failures: list[dict[str, Any]] = []
    provider = None
    collection = None
    for case in cases:
        started = time.perf_counter()
        result = search_asset_library(
            case["query"],
            category=case.get("category", ""),
            top_k=5,
            use_vector=use_vector,
            expand_relations=expand_relations,
        )
        durations.append((time.perf_counter() - started) * 1000.0)
        collection = result.get("active_collection")
        ids = [item["assetId"] for item in result.get("results", [])]
        expected = {str(item) for item in case.get("expectedAssetIds", [])}
        rank = next((index + 1 for index, item in enumerate(ids) if item in expected), 0)
        if rank:
            reciprocal_rank += 1.0 / rank
        for k in (1, 3, 5):
            relevant = len(expected.intersection(ids[:k]))
            hits[k] += int(relevant > 0)
            precision[k] += relevant / k
            recall[k] += relevant / max(1, len(expected))
        if rank != 1:
            failures.append(
                {
                    "query": case["query"],
                    "expected": sorted(expected),
                    "rank": rank or None,
                    "results": ids[:5],
                }
            )
        provider = provider or load_asset_index_state(DEFAULT_INDEX_DIR).get(
            "embedding_provider"
        )
    total = len(cases)
    divisor = max(1, total)
    return {
        "name": name,
        "query_count": total,
        "vector_enabled": use_vector,
        "relations_expanded": expand_relations,
        "collection": collection or active_asset_collection_name(DEFAULT_INDEX_DIR),
        "embedding_provider": provider,
        "rerank_version": ASSET_RERANK_VERSION,
        "hit_at_1": round(hits[1] / divisor, 4),
        "hit_at_3": round(hits[3] / divisor, 4),
        "hit_at_5": round(hits[5] / divisor, 4),
        "macro_precision_at_1": round(precision[1] / divisor, 4),
        "macro_precision_at_3": round(precision[3] / divisor, 4),
        "macro_precision_at_5": round(precision[5] / divisor, 4),
        "macro_recall_at_1": round(recall[1] / divisor, 4),
        "macro_recall_at_3": round(recall[3] / divisor, 4),
        "macro_recall_at_5": round(recall[5] / divisor, 4),
        "mrr": round(reciprocal_rank / divisor, 4),
        "average_latency_ms": round(sum(durations) / divisor, 2),
        "p95_latency_ms": round(_percentile(durations, 0.95), 2),
        "max_latency_ms": round(max(durations, default=0.0), 2),
        "failures": failures,
    }


def _matches_expected_fields(value: Any, expected: dict[str, Any]) -> bool:
    for key, wanted in expected.items():
        actual = value.get(key) if isinstance(value, dict) else None
        if isinstance(wanted, dict) and isinstance(actual, dict):
            if not _matches_expected_fields(actual, wanted):
                return False
        elif actual != wanted:
            return False
    return True


def _benchmark_relations(cases: list[dict[str, Any]]) -> dict[str, Any]:
    passed = 0
    constraint_total = 0
    constraint_passed = 0
    durations: list[float] = []
    failures: list[dict[str, Any]] = []
    for case in cases:
        started = time.perf_counter()
        result = get_asset_relations(
            str(case["sourceAssetId"]),
            relation_types={str(case["relationType"])},
            depth=int(case.get("depth", 1)),
            origins=case.get("origins"),
            include_constraints=bool(case.get("expectedConstraint")),
            direction=str(case.get("direction", "outgoing")),
        )
        durations.append((time.perf_counter() - started) * 1000.0)
        expected_targets = {str(item) for item in case.get("expectedTargetAssetIds", [])}
        matches = [
            edge
            for edge in result.get("relations", [])
            if edge.get("target") in expected_targets
            and edge.get("type") == case.get("relationType")
        ]
        case_passed = bool(matches)
        expected_constraint = case.get("expectedConstraint")
        if isinstance(expected_constraint, dict):
            constraint_total += 1
            constraint_ok = any(
                _matches_expected_fields(edge.get("compiledConstraint"), expected_constraint)
                for edge in matches
            )
            constraint_passed += int(constraint_ok)
            case_passed = case_passed and constraint_ok
        passed += int(case_passed)
        if not case_passed:
            failures.append(
                {
                    "sourceAssetId": case["sourceAssetId"],
                    "relationType": case["relationType"],
                    "expectedTargets": sorted(expected_targets),
                    "actual": [
                        {"target": edge.get("target"), "type": edge.get("type")}
                        for edge in result.get("relations", [])
                    ],
                }
            )
    total = len(cases)
    return {
        "case_count": total,
        "accuracy": round(passed / max(1, total), 4),
        "constraint_case_count": constraint_total,
        "constraint_compilation_accuracy": round(
            constraint_passed / max(1, constraint_total), 4
        ),
        "p95_latency_ms": round(_percentile(durations, 0.95), 3),
        "max_latency_ms": round(max(durations, default=0.0), 3),
        "failures": failures,
    }


def _scene_constraint_matches(
    placements: list[dict[str, Any]],
    check: dict[str, Any],
) -> bool:
    candidates = [
        item for item in placements if item.get("asset_id") == check.get("assetId")
    ]
    if not candidates:
        return False
    field = str(check.get("field", ""))
    for placement in candidates:
        actual = placement.get(field)
        if "equals" in check and actual == check["equals"]:
            return True
        if "minimum" in check:
            try:
                if float(actual) >= float(check["minimum"]):
                    return True
            except (TypeError, ValueError):
                pass
        if "containsType" in check and isinstance(actual, list):
            if any(item.get("type") == check["containsType"] for item in actual):
                return True
    return False


def _benchmark_scenes(cases: list[dict[str, Any]]) -> dict[str, Any]:
    passed = 0
    constraint_total = 0
    constraint_passed = 0
    durations: list[float] = []
    failures: list[dict[str, Any]] = []
    for case in cases:
        started = time.perf_counter()
        preview = build_asset_scene_preview(
            intent=str(case["intent"]),
            scene_context={"scene_token": "benchmark", "scene_path": "", "objects": []},
            max_assets=int(case.get("maxAssets", 20)),
            density=str(case.get("density", "medium")),
            constraints=dict(case.get("constraints", {})),
        )
        durations.append((time.perf_counter() - started) * 1000.0)
        placements = preview.get("placements", [])
        actual_ids = {str(item.get("asset_id")) for item in placements}
        expected_ids = {str(item) for item in case.get("expectedAssetIds", [])}
        asset_ok = expected_ids.issubset(actual_ids)
        recipe_ok = not case.get("expectedRecipeId") or (
            preview.get("recipe_id") == case.get("expectedRecipeId")
        )
        checks = [dict(item) for item in case.get("placementChecks", [])]
        checks_ok = True
        for check in checks:
            constraint_total += 1
            matched = _scene_constraint_matches(placements, check)
            constraint_passed += int(matched)
            checks_ok = checks_ok and matched
        case_passed = preview.get("can_apply") and asset_ok and recipe_ok and checks_ok
        passed += int(case_passed)
        if not case_passed:
            failures.append(
                {
                    "intent": case["intent"],
                    "expectedAssetIds": sorted(expected_ids),
                    "actualAssetIds": sorted(actual_ids),
                    "expectedRecipeId": case.get("expectedRecipeId"),
                    "actualRecipeId": preview.get("recipe_id"),
                    "errors": preview.get("errors", []),
                }
            )
    total = len(cases)
    return {
        "case_count": total,
        "accuracy": round(passed / max(1, total), 4),
        "constraint_check_count": constraint_total,
        "constraint_compilation_accuracy": round(
            constraint_passed / max(1, constraint_total), 4
        ),
        "p95_latency_ms": round(_percentile(durations, 0.95), 2),
        "max_latency_ms": round(max(durations, default=0.0), 2),
        "failures": failures,
    }


def _metric_delta(current: dict[str, Any], previous: dict[str, Any]) -> dict[str, float]:
    keys = ("hit_at_1", "hit_at_3", "mrr", "p95_latency_ms")
    return {
        key: round(float(current.get(key, 0.0)) - float(previous.get(key, 0.0)), 4)
        for key in keys
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default=str(DEFAULT_CASES))
    parser.add_argument("--relation-cases", default=str(DEFAULT_RELATION_CASES))
    parser.add_argument("--scene-cases", default=str(DEFAULT_SCENE_CASES))
    parser.add_argument("--output-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--no-vector", action="store_true")
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Run only the selected search mode instead of the ablation matrix.",
    )
    args = parser.parse_args()

    search_cases = _load_cases(Path(args.cases))
    relation_cases = _load_cases(Path(args.relation_cases))
    scene_cases = _load_cases(Path(args.scene_cases))
    primary = _benchmark_search(
        search_cases,
        use_vector=not args.no_vector,
        expand_relations=False,
        name="primary",
    )
    ablations = [primary]
    if not args.quick:
        if not args.no_vector:
            ablations.insert(
                0,
                _benchmark_search(
                    search_cases,
                    use_vector=False,
                    expand_relations=False,
                    name="lexical_rule_rerank",
                ),
            )
        ablations.append(
            _benchmark_search(
                search_cases,
                use_vector=not args.no_vector,
                expand_relations=True,
                name="graph_expansion_ablation",
            )
        )

    relation_report = _benchmark_relations(relation_cases)
    scene_report = _benchmark_scenes(scene_cases)
    gates = {
        "search_top1": primary["hit_at_1"] >= SEARCH_TOP1_GATE,
        "search_hit3": primary["hit_at_3"] >= SEARCH_HIT3_GATE,
        "search_mrr": primary["mrr"] >= SEARCH_MRR_GATE,
        "relation_accuracy": relation_report["accuracy"] >= RELATION_GATE,
        "constraint_compilation": min(
            relation_report["constraint_compilation_accuracy"],
            scene_report["constraint_compilation_accuracy"],
        ) >= CONSTRAINT_GATE,
        "search_p95": primary["p95_latency_ms"] <= SEARCH_P95_GATE_MS,
        "graph_p95": relation_report["p95_latency_ms"] <= GRAPH_P95_GATE_MS,
        "scene_plan_accuracy": scene_report["accuracy"] >= SCENE_PLAN_GATE,
        "scene_plan_p95": scene_report["p95_latency_ms"] <= SCENE_P95_GATE_MS,
    }

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    latest_path = output_dir / "latest.json"
    previous = None
    if latest_path.is_file():
        try:
            previous = json.loads(latest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            previous = None
    timestamp = datetime.now(timezone.utc)
    index_state = load_asset_index_state(DEFAULT_INDEX_DIR)
    report = {
        "success": True,
        "generated_at": timestamp.isoformat(),
        "configuration": {
            "active_collection": index_state.get("active_collection"),
            "embedding_provider": index_state.get("embedding_provider"),
            "rerank_version": ASSET_RERANK_VERSION,
            "vector_enabled": not args.no_vector,
            "search_case_path": str(Path(args.cases).resolve()),
            "relation_case_path": str(Path(args.relation_cases).resolve()),
            "scene_case_path": str(Path(args.scene_cases).resolve()),
        },
        "search": primary,
        "relations": relation_report,
        "scene_plans": scene_report,
        "ablation_matrix": ablations,
        "gates": gates,
        "acceptance_passed": all(gates.values()),
        "difference_from_previous": (
            _metric_delta(primary, previous.get("search", {})) if previous else None
        ),
    }
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    report_path = output_dir / timestamp.strftime("%Y%m%dT%H%M%SZ.json")
    report_path.write_text(text, encoding="utf-8")
    latest_path.write_text(text, encoding="utf-8")
    report["report_path"] = str(report_path)
    report["latest_path"] = str(latest_path)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["acceptance_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

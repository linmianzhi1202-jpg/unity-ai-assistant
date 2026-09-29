"""Game source code RAG tools for the product MCP server."""

from __future__ import annotations

import json
import logging
import sys
import asyncio
import os
import re
from pathlib import Path
from typing import Any

from services.code_adaptation_service import (
    AdaptationParseError,
    audit_generated_adaptation,
    build_adaptation_prompt,
    build_repair_prompt,
    call_ollama_for_adaptation,
    collect_project_context,
    ensure_usings,
    parse_reference_results,
    resolve_target_script,
    should_repair_adaptation,
)
from services.code_scoring_service import (
    load_rules,
    evaluate_references_async,
    _serialize_scorecard,
    _build_project_summary,
    run_score_game_code_task,
    RulesEngine,
    ScoreCard,
    GateResult,
)
from services.reference_pattern_service import (
    audit_knowledge_base_references,
    distill_reference_patterns,
    make_pattern_references,
)
from services.adaptation_task_service import AdaptTask, get_adapt_task_manager
from services.tools.tool_group_map import make_group_tags
from services.tools.unity_bridge import close_bridge, get_bridge, send_to_unity

logger = logging.getLogger(__name__)

_PRODUCT_ROOT = Path(__file__).resolve().parents[4]
_GAME_RAG_ROOT = _PRODUCT_ROOT / "Server" / "data" / "game-rag-knowledge-base"
_GAME_RAG_SRC = _GAME_RAG_ROOT / "src"
_GAME_RAG_CONFIG = _GAME_RAG_ROOT / "config" / "config_game.yaml"

_game_code_searcher = None
_game_code_import_error: str | None = None
_KEYWORD_SCAN_LIMIT = 5000
_SEMANTIC_SEARCH_TIMEOUT_SECONDS = float(os.getenv("UNITY_MCP_GAME_CODE_SEARCH_TIMEOUT", "12"))

# Default code types returned by search (excludes asset types: scene, material, asset, packages)
_CODE_TYPES = {"class_overview", "struct_overview", "enum_overview", "method_detail", "full_file"}


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _build_next_action(
    status: str,
    *,
    apply: bool,
    quality_audit: dict[str, Any] | None = None,
    compile_status: str = "not_run",
    error_code: str = "",
) -> str:
    """Return the next recommended operator action for adapt_game_code."""
    quality_audit = quality_audit or {}
    needs_repair = bool(quality_audit.get("needs_repair"))
    goal_audit_issues = quality_audit.get("goal_feature_audit", {}).get("issues", [])

    if status == "preview":
        if needs_repair:
            reasons: list[str] = []
            if goal_audit_issues:
                reasons.append("goal feature audit found missing implementations")
            if quality_audit.get("cross_file_api", {}).get("issues"):
                reasons.append("cross-file API references may be invalid")
            reason_text = "; ".join(reasons) if reasons else "issues in quality_audit"
            return f"Review generated_code and quality_audit issues ({reason_text}) before applying; retry with a tighter goal or references if needed."
        return "Review generated_code and set apply=true to write the script when it looks correct."
    if status == "applied":
        return "Script was written and compiled cleanly. Open Unity and verify runtime behavior in-scene."
    if status == "applied_with_compile_errors":
        return "Fix the reported compile errors in the target script or related dependencies before continuing."
    if status == "applied_pending_compile":
        if compile_status == "compiling":
            return "Unity is still compiling or reconnecting. Wait for compilation to finish, then run check_compile_errors or read recent logs."
        return "Script was written, but compile state was not confirmed. Re-run check_compile_errors and inspect recent Unity logs."
    if status == "unavailable":
        return "Restore the unavailable dependency (Unity or Ollama) and retry the same request."
    if status == "error":
        if error_code == "generation_json_parse_failed":
            return "Ollama returned non-JSON response. Try a model better at JSON (e.g. qwen2.5-coder:7b), or set UNITY_MCP_CODE_ADAPT_FALLBACK_MODEL as a backup model. Then retry."
        if error_code == "generated_code_incomplete":
            return "Ollama responded but generated_code was empty or missing C# class. Try a more specific goal or stronger model."
        if not apply:
            return "Fix the request inputs and retry the preview."
        return "Fix the reported error, then re-run adapt_game_code with apply=false before writing again."
    return "Inspect warnings and logs_excerpt to decide the next manual step."


def _preview_transport_hint() -> str:
    return (
        "For long generations, prefer start_adapt_game_code -> get_adapt_task_status -> apply_adapt_task "
        "to avoid MCP stdio timeouts."
    )


def _apply_transport_hint() -> str:
    return (
        "apply_adapt_task now runs write/refresh/compile-check in the background. "
        "Poll get_adapt_task_status until task status becomes completed or failed."
    )


def _normalize_compile_result(
    compile_result: dict[str, Any] | None,
    compile_status: str,
    warnings: list[str],
) -> dict[str, Any]:
    """Return a predictable compile_result payload for adapt_game_code."""
    payload = compile_result if isinstance(compile_result, dict) else {}
    unity_payload = payload.get("result", {}) if isinstance(payload.get("result"), dict) else {}
    return {
        "status": compile_status,
        "raw": compile_result,
        "has_errors": bool(unity_payload.get("has_errors", False)),
        "error_count": int(unity_payload.get("error_count", 0) or 0),
        "is_compiling": bool(unity_payload.get("is_compiling", unity_payload.get("compiling", False))),
        "errors": unity_payload.get("errors", []),
        "message": unity_payload.get("message") or (
            warnings[-1] if warnings and compile_status in {"unknown", "compiling"} else ""
        ),
    }


async def _wait_for_compile_after_script_write(
    timeout_seconds: float = 60.0,
    poll_seconds: float = 1.0,
) -> tuple[str, str, dict[str, Any] | None, list[str]]:
    """Wait for Unity to reconnect + compile after script write.

    Merged from the old sequential _wait_for_unity_after_script_write (45s)
    + _collect_compile_result_after_write (45s). Now a single loop that
    simultaneously tests reconnection and polls compile state, cutting
    worst-case latency from 90s to 60s.

    Returns:
        (compile_status, reconnect_error, compile_result, warnings)
    """
    warnings: list[str] = []
    compile_result: dict[str, Any] | None = None
    compile_status = "unknown"
    reconnect_error = ""
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    reconnect_failures = 0

    while asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(poll_seconds)
        try:
            # Use max_retries=1: outer poll loop handles retry, so don't
            # let the bridge waste ~17s on internal backoff per cycle.
            compile_result = await get_bridge().send_command(
                "manage_editor", {"action": "check_compile_errors"}, max_retries=1,
            )
            unity_compile = (compile_result or {}).get("result", {})
            is_compiling = bool(
                unity_compile.get("is_compiling", unity_compile.get("compiling", False))
            )
            has_errors = bool(unity_compile.get("has_errors", False))

            if is_compiling:
                compile_status = "compiling"
                continue  # Unity is alive and compiling — keep polling

            compile_status = "failed" if has_errors else "passed"
            return compile_status, "", compile_result, warnings
        except Exception as exc:
            reconnect_failures += 1
            reconnect_error = str(exc)
            close_bridge()

    warnings.append(
        f"Unity not ready within {timeout_seconds:.0f}s after script write "
        f"({reconnect_failures} reconnect attempt(s))."
        + (f" Last error: {reconnect_error}" if reconnect_error else "")
        + (" Unity was still compiling at timeout." if compile_status == "compiling" else "")
    )
    return compile_status, reconnect_error, compile_result, warnings


def _load_config() -> dict[str, Any]:
    if not _GAME_RAG_CONFIG.exists():
        return {}
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required to read config_game.yaml") from exc
    with open(_GAME_RAG_CONFIG, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _embedding_config_is_usable(config: dict[str, Any]) -> tuple[bool, str]:
    embedding = config.get("embedding", {})
    provider = embedding.get("provider", "")
    if provider != "local":
        return True, ""

    model_name = embedding.get("local", {}).get("model_name", "")
    if not model_name:
        return False, "Local embedding model_name is empty."

    model_path = Path(model_name)
    if not model_path.exists():
        return False, f"Local embedding path does not exist: {model_name}"

    required_any = ["model.safetensors", "pytorch_model.bin"]
    if not any((model_path / name).exists() and (model_path / name).stat().st_size > 0 for name in required_any):
        return False, f"Local embedding model weights are missing or empty under: {model_name}"

    for name in ["config.json", "modules.json"]:
        path = model_path / name
        if not path.exists() or path.stat().st_size == 0:
            return False, f"Local embedding file is missing or empty: {path}"

    return True, ""


def _get_searcher():
    global _game_code_searcher, _game_code_import_error
    if _game_code_searcher is not None:
        return _game_code_searcher

    if not _GAME_RAG_SRC.exists():
        _game_code_import_error = f"Game RAG source directory not found: {_GAME_RAG_SRC}"
        return None

    if str(_GAME_RAG_SRC) not in sys.path:
        sys.path.insert(0, str(_GAME_RAG_SRC))

    try:
        from game_code_search import GameCodeSearcher

        config = _load_config()
        _game_code_searcher = GameCodeSearcher(config)
        _game_code_import_error = None
        return _game_code_searcher
    except Exception as exc:
        _game_code_import_error = str(exc)
        logger.warning("Failed to initialize game code searcher: %s", exc)
        return None


def _metadata_value(metadata: dict[str, Any], key: str, default: Any = "") -> Any:
    value = metadata.get(key, default)
    if value is None:
        return default
    return value


def _summarize_code(text: str, class_name: str, method_name: str, code_type: str) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if method_name:
        return f"{class_name}.{method_name} implements the matched {code_type or 'code'} pattern."
    if class_name:
        return f"{class_name} provides a matched {code_type or 'code'} structure."
    if lines:
        return lines[0][:160]
    return "Matched game source code reference."


def _reuse_hint(class_name: str, method_name: str, code_type: str) -> str:
    if method_name and class_name:
        return (
            f"Use {class_name}.{method_name} as a reference, then adapt names, serialized "
            "fields, prefab links, and Unity lifecycle hooks to the current project."
        )
    if class_name:
        return (
            f"Use {class_name} as a structure reference, then copy only the responsibilities "
            "that match the current project architecture."
        )
    return "Use this snippet as a reference pattern, not as a direct copy."


def _format_code_result(item: dict[str, Any]) -> dict[str, Any]:
    if "error" in item:
        return item

    metadata = item.get("metadata") or {}
    text = item.get("text", "")
    class_name = _metadata_value(metadata, "class_name")
    method_name = _metadata_value(metadata, "method_name")
    code_type = _metadata_value(metadata, "code_type")

    return {
        "id": item.get("id", ""),
        "game_name": _metadata_value(metadata, "game_name"),
        "file_path": _metadata_value(metadata, "file_path"),
        "class_name": class_name,
        "method_name": method_name,
        "code_type": code_type,
        "line_start": _metadata_value(metadata, "line_start", None),
        "line_end": _metadata_value(metadata, "line_end", None),
        "score": item.get("score"),
        "summary": _summarize_code(text, class_name, method_name, code_type),
        "reuse_hint": _reuse_hint(class_name, method_name, code_type),
        "text": text,
        "metadata": metadata,
    }


def _format_graph_entity(item: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {"value": item}

    entity = item.get("entity", item)
    if not isinstance(entity, dict):
        return item

    metadata = entity.get("metadata") or {}
    return {
        "id": entity.get("id", ""),
        "name": entity.get("name", ""),
        "entity_type": entity.get("entity_type", ""),
        "description": entity.get("description", ""),
        "file_path": metadata.get("file_path", ""),
        "class_name": metadata.get("class_name", entity.get("name", "")),
        "method_name": metadata.get("method_name", ""),
        "game_name": metadata.get("game_name", ""),
        "relations": item.get("relations", []),
        "neighbors": item.get("neighbors", []),
    }

_GOAL_SCRIPT_HINTS = {
    "tower": ["tower", "turret", "塔", "炮塔", "防御塔"],
    "enemy": ["enemy", "monster", "mob", "敌人", "怪物", "受击", "死亡"],
    "game manager": ["game manager", "gamemanager", "manager", "游戏管理", "管理器"],
    "sound manager": ["sound", "audio", "sfx", "music", "声音", "音效", "音乐"],
    "map": ["map", "level", "grid", "tile", "地图", "关卡", "格子"],
    "ui": ["ui", "hud", "button", "panel", "canvas", "界面", "按钮", "面板"],
    "wave": ["wave", "spawn", "spawner", "round", "波次", "生成", "刷新", "出怪"],
    "projectile": ["projectile", "bullet", "missile", "arrow", "子弹", "投射物", "箭"],
    "player": ["player", "hero", "character", "玩家", "角色", "英雄"],
    "skill": ["skill", "ability", "spell", "技能", "法术"],
    "inventory": ["inventory", "item", "bag", "背包", "物品", "道具"],
}

_CATEGORY_TARGET_SIGNALS = {
    "tower": ["tower", "turret", "attack", "shoot", "range", "target", "projectile", "damage"],
    "enemy": ["enemy", "monster", "health", "hp", "damage", "die", "death", "hit", "move"],
    "game manager": ["gamemanager", "game_manager", "manager", "state", "score", "level", "win", "lose"],
    "sound manager": ["audio", "sound", "sfx", "music", "clip", "source", "play"],
    "map": ["map", "level", "grid", "tile", "cell", "path", "node"],
    "ui": ["ui", "hud", "button", "panel", "canvas", "text", "image", "slider", "tmp"],
    "wave": ["wave", "spawn", "spawner", "round", "enemy", "count", "interval"],
    "projectile": ["projectile", "bullet", "missile", "arrow", "speed", "damage", "target"],
    "player": ["player", "hero", "character", "input", "move", "health", "controller"],
    "skill": ["skill", "ability", "spell", "cooldown", "cost", "cast", "effect"],
    "inventory": ["inventory", "item", "bag", "slot", "pickup", "equipment"],
}

_SCRIPT_SELECTION_STOP_WORDS = {
    "the",
    "and",
    "for",
    "with",
    "into",
    "from",
    "this",
    "that",
    "code",
    "game",
    "unity",
    "add",
    "make",
    "logic",
    "system",
    "功能",
    "逻辑",
    "添加",
    "实现",
}


def _extract_script_class_names(script_text: str) -> list[str]:
    return re.findall(r"\bclass\s+([A-Za-z_]\w*)", script_text or "")


def _keyword_terms(query: str) -> list[str]:
    terms = re.findall(r"[A-Za-z0-9_]+", query.lower())
    return [
        term
        for term in terms
        if len(term) >= 3 and term not in _SCRIPT_SELECTION_STOP_WORDS
    ]


def _goal_terms_for_scripts(goal: str) -> list[str]:
    goal_lower = goal.lower()
    terms = _keyword_terms(goal)
    for canonical, hints in _GOAL_SCRIPT_HINTS.items():
        if any(hint in goal_lower for hint in hints):
            terms.extend(_keyword_terms(canonical))
            terms.extend(_keyword_terms(" ".join(hints)))
            for hint in hints:
                if re.fullmatch(r"[A-Za-z0-9_]+", hint):
                    terms.append(hint.lower())
    seen: set[str] = set()
    ordered: list[str] = []
    for term in terms:
        if term not in seen:
            seen.add(term)
            ordered.append(term)
    return ordered


def _goal_categories_for_scripts(goal: str) -> list[str]:
    goal_lower = goal.lower()
    categories: list[str] = []
    for canonical, hints in _GOAL_SCRIPT_HINTS.items():
        if canonical in goal_lower or any(hint in goal_lower for hint in hints):
            categories.append(canonical)
    return categories


def _extract_script_selection_features(script_text: str) -> dict[str, Any]:
    text = script_text or ""
    method_names = re.findall(
        r"\b(?:public|private|protected|internal)?\s*(?:static\s+)?(?:[\w<>\[\],.?]+\s+)?([A-Za-z_]\w*)\s*\(",
        text,
    )
    method_names = [
        name
        for name in method_names
        if name not in {"if", "for", "foreach", "while", "switch", "catch", "using", "return", "new"}
    ]
    field_names = re.findall(
        r"(?:\[SerializeField\]\s*)?(?:public|private|protected|internal|static|readonly|const|\s)+"
        r"[\w<>\[\],.?]+\s+([A-Za-z_]\w*)\s*(?:[;=])",
        text,
    )
    base_matches = re.findall(r"\bclass\s+[A-Za-z_]\w*\s*:\s*([^{\n]+)", text)
    lifecycle = [
        name
        for name in ["Awake", "Start", "Update", "FixedUpdate", "LateUpdate", "OnEnable", "OnDisable", "OnDestroy"]
        if re.search(rf"\b{name}\s*\(", text)
    ]
    unity_apis = [
        api
        for api in [
            "GetComponent",
            "Instantiate",
            "Destroy",
            "FindObjectOfType",
            "GameObject.Find",
            "Physics",
            "NavMeshAgent",
            "Button",
            "TextMeshProUGUI",
            "Rigidbody",
            "Collider",
        ]
        if api in text
    ]
    return {
        "class_names": _extract_script_class_names(text),
        "method_names": sorted(set(method_names))[:24],
        "field_names": sorted(set(field_names))[:24],
        "base_types": sorted(set(base.strip() for base in base_matches if base.strip()))[:8],
        "lifecycle_methods": lifecycle,
        "unity_apis": unity_apis,
        "serialized_field_count": text.count("[SerializeField]"),
    }


def _script_selection_confidence(score: float, risk_flags: list[str]) -> str:
    severe_flags = {"test_script", "generated_script", "third_party_or_plugin"}
    if score >= 7.0 and not any(flag in severe_flags for flag in risk_flags):
        return "high"
    if score >= 3.5:
        return "medium"
    return "low"


def _score_target_script_candidate(
    path: Path,
    project_root: Path,
    goal_terms: list[str],
    goal_categories: list[str],
) -> dict[str, Any] | None:
    rel = path.relative_to(project_root).as_posix()
    rel_lower = rel.lower()
    if rel_lower.startswith("assets/editor/") or "/editor/" in rel_lower:
        return None

    try:
        file_size = path.stat().st_size
    except OSError:
        file_size = 0

    try:
        text = path.read_text(encoding="utf-8-sig", errors="ignore")
    except Exception:
        text = ""

    text_preview = text[:20000]
    features = _extract_script_selection_features(text_preview)
    name_lower = path.stem.lower()
    directory_lower = path.parent.name.lower()
    class_names = list(features.get("class_names", []))
    methods = list(features.get("method_names", []))
    fields = list(features.get("field_names", []))
    symbol_text = " ".join([*class_names, *methods, *fields]).lower()
    path_text = " ".join([rel_lower, name_lower, directory_lower])

    score = 0.0
    reasons: list[str] = []
    matched_terms: set[str] = set()
    risk_flags: list[str] = []

    for term in goal_terms:
        term_lower = term.lower()
        if not term_lower:
            continue
        if term_lower == name_lower:
            score += 5.0
            reasons.append(f"file name exactly matches '{term_lower}'")
            matched_terms.add(term_lower)
        elif term_lower in name_lower:
            score += 2.5
            reasons.append(f"file name contains '{term_lower}'")
            matched_terms.add(term_lower)
        if term_lower == directory_lower:
            score += 2.0
            reasons.append(f"directory exactly matches '{term_lower}'")
            matched_terms.add(term_lower)
        elif term_lower in directory_lower:
            score += 1.0
            reasons.append(f"directory contains '{term_lower}'")
            matched_terms.add(term_lower)
        if any(term_lower == class_name.lower() for class_name in class_names):
            score += 4.0
            reasons.append(f"class name exactly matches '{term_lower}'")
            matched_terms.add(term_lower)
        elif term_lower in symbol_text:
            score += 0.8
            reasons.append(f"script symbols contain '{term_lower}'")
            matched_terms.add(term_lower)
        elif term_lower in path_text:
            score += 0.35
            matched_terms.add(term_lower)

    for category in goal_categories:
        signals = _CATEGORY_TARGET_SIGNALS.get(category, [])
        category_hits = [
            signal
            for signal in signals
            if signal in path_text or signal in symbol_text
        ]
        if category_hits:
            score += min(3.0, 0.65 * len(set(category_hits)))
            reasons.append(f"{category} responsibility signals: {', '.join(sorted(set(category_hits))[:5])}")
            matched_terms.update(category_hits[:5])

    if features.get("serialized_field_count"):
        score += min(1.0, 0.2 * int(features["serialized_field_count"]))
    if "MonoBehaviour" in " ".join(features.get("base_types", [])):
        score += 0.5
    if features.get("lifecycle_methods"):
        score += min(0.8, 0.2 * len(features["lifecycle_methods"]))
    if features.get("unity_apis"):
        score += min(0.8, 0.15 * len(features["unity_apis"]))

    if "/test/" in rel_lower or "/tests/" in rel_lower or name_lower.endswith("test") or "test" in name_lower:
        score -= 3.0
        risk_flags.append("test_script")
    if "generated" in rel_lower or "<auto-generated" in text_preview.lower():
        score -= 2.5
        risk_flags.append("generated_script")
    if rel_lower.startswith("assets/plugins/") or "/plugins/" in rel_lower or "/thirdparty/" in rel_lower:
        score -= 1.5
        risk_flags.append("third_party_or_plugin")
    if file_size > 120_000:
        score -= 0.75
        risk_flags.append("large_script")

    score = round(max(0.0, score), 3)
    if score <= 0:
        return None

    return {
        "path": rel,
        "class_names": class_names[:8],
        "score": score,
        "confidence": _script_selection_confidence(score, risk_flags),
        "reasons": sorted(set(reasons))[:8],
        "matched_terms": sorted(matched_terms)[:12],
        "risk_flags": sorted(set(risk_flags)),
        "signals": {
            "methods": methods[:10],
            "fields": fields[:10],
            "base_types": features.get("base_types", []),
            "lifecycle_methods": features.get("lifecycle_methods", []),
            "unity_apis": features.get("unity_apis", []),
            "serialized_field_count": features.get("serialized_field_count", 0),
        },
    }


def _select_target_script(project_root: Path, goal: str, max_candidates: int = 5) -> dict[str, Any]:
    assets_dir = project_root / "Assets"
    if not assets_dir.exists():
        return {
            "status": "error",
            "error": "Unity project Assets directory was not found.",
            "candidates": [],
            "warnings": ["Assets directory was not found."],
        }

    terms = _goal_terms_for_scripts(goal)
    categories = _goal_categories_for_scripts(goal)
    candidates: list[dict[str, Any]] = []
    for path in assets_dir.rglob("*.cs"):
        candidate = _score_target_script_candidate(path, project_root, terms, categories)
        if candidate:
            candidates.append(candidate)

    candidates.sort(key=lambda item: item.get("score", 0), reverse=True)
    top_candidates = candidates[: max(1, min(20, max_candidates))]
    if not top_candidates:
        return {
            "status": "needs_target",
            "error": "Could not infer a target script from the goal. Provide target_script_path explicitly.",
            "candidates": [],
            "goal_terms": terms,
            "goal_categories": categories,
            "warnings": ["No non-Editor C# script matched the goal terms."],
        }

    best = top_candidates[0]
    second_score = float(top_candidates[1]["score"]) if len(top_candidates) > 1 else 0.0
    best_score = float(best["score"])
    margin = best_score - second_score
    ambiguous = bool(second_score and (margin < 1.5 or second_score >= best_score * 0.82))
    if best.get("confidence") != "high" or ambiguous:
        return {
            "status": "needs_confirmation",
            "error": "Target script inference was not confident enough to proceed automatically.",
            "target_script_path": best.get("path"),
            "confidence": best.get("confidence", "low"),
            "candidates": top_candidates,
            "goal_terms": terms,
            "goal_categories": categories,
            "warnings": [
                "Automatic selection is conservative; rerun with target_script_path when candidates are close."
            ],
        }

    return {
        "status": "selected",
        "target_script_path": best["path"],
        "confidence": best.get("confidence", "high"),
        "candidates": top_candidates,
        "goal_terms": terms,
        "goal_categories": categories,
        "warnings": [],
    }


def _build_agent_reference_query(goal: str, project_root: Path, target_script_path: str) -> str:
    """Bias source-code retrieval toward the selected target script without hiding the user goal."""
    parts = [goal]
    rel_path = Path(target_script_path)
    if rel_path.stem:
        parts.append(rel_path.stem)

    target_path = project_root / target_script_path
    try:
        script_text = target_path.read_text(encoding="utf-8-sig", errors="ignore")[:5000]
        parts.extend(_extract_script_class_names(script_text))
    except Exception:
        pass

    parts.extend(_goal_terms_for_scripts(goal))
    seen: set[str] = set()
    ordered: list[str] = []
    for part in parts:
        value = str(part).strip()
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(value)
    return " ".join(ordered)


def _clean_reference_for_adaptation(reference: dict[str, Any]) -> dict[str, Any]:
    """Drop internal scoring objects before a reference is serialized or sent to the adapter."""
    return {
        key: value
        for key, value in reference.items()
        if not key.startswith("_")
    }


def _reference_scorecard(reference: dict[str, Any]) -> ScoreCard | None:
    card = reference.get("_scorecard")
    return card if isinstance(card, ScoreCard) else None


def _reference_gate(reference: dict[str, Any]) -> GateResult | None:
    gate = reference.get("_gate")
    return gate if isinstance(gate, GateResult) else None


def _reference_score_metadata(reference: dict[str, Any]) -> dict[str, Any]:
    card = _reference_scorecard(reference)
    gate = _reference_gate(reference)
    rule_score = float(getattr(card, "overall_score", 0.0) or 0.0)
    compatibility_score = round(rule_score * 10.0, 1)
    blocked = bool(getattr(card, "blocked", False) or getattr(gate, "blocked", False))
    hard_blockers = [
        {
            "rule_id": result.rule_id,
            "severity": result.severity,
            "detail": result.detail,
            "matched_lines": result.matched_lines,
        }
        for result in (getattr(gate, "critical_fails", []) if gate else [])
    ]
    warning_signals = [
        {
            "rule_id": result.rule_id,
            "severity": result.severity,
            "detail": result.detail,
        }
        for result in (getattr(gate, "warning_fails", []) if gate else [])
    ][:8]

    if blocked or compatibility_score < 40.0:
        risk_level = "high"
        recommended_use = "skip"
    elif compatibility_score >= 70.0:
        risk_level = "low"
        recommended_use = "use"
    else:
        risk_level = "medium"
        recommended_use = "use_with_caution"

    summary = getattr(card, "summary", "") if card else ""
    agent_notes = getattr(card, "agent_notes", "") if card else ""
    agent_review = getattr(card, "agent_review", None) if card else None
    agent_signals: list[dict[str, str]] = []
    if isinstance(agent_review, dict) and agent_review.get("status") == "completed":
        for dimension in agent_review.get("dimensions", []):
            if not isinstance(dimension, dict):
                continue
            if dimension.get("risk_level") in {"medium", "high"}:
                agent_signals.append({
                    "dimension": str(dimension.get("name", "")),
                    "risk_level": str(dimension.get("risk_level", "")),
                    "note": str(dimension.get("note", ""))[:180],
                })
        for risk in agent_review.get("top_risks", [])[:3]:
            agent_signals.append({
                "dimension": "top_risk",
                "risk_level": "medium",
                "note": str(risk)[:180],
            })
    reason_parts = [part for part in (summary, agent_notes) if part]
    return {
        "original_score": reference.get("score"),
        "compatibility_score": compatibility_score,
        "risk_level": risk_level,
        "recommended_use": recommended_use,
        "hard_blockers": hard_blockers,
        "signals": warning_signals,
        "agent_signals": agent_signals[:6],
        "reason": " ".join(reason_parts) or "Rule scoring completed.",
        "scorecard": _serialize_scorecard(card) if card else None,
    }


def _serialize_scored_reference(reference: dict[str, Any], *, include_text: bool = True) -> dict[str, Any]:
    clean = _clean_reference_for_adaptation(reference)
    if not include_text:
        clean.pop("text", None)
    clean.update(_reference_score_metadata(reference))
    return clean


def _scored_reference_for_adaptation(reference: dict[str, Any]) -> dict[str, Any]:
    allowed_keys = {
        "id",
        "game_name",
        "file_path",
        "class_name",
        "method_name",
        "code_type",
        "line_start",
        "line_end",
        "score",
        "summary",
        "reuse_hint",
        "text",
        "metadata",
        "compatibility_score",
        "risk_level",
        "recommended_use",
        "reason",
    }
    return {key: value for key, value in reference.items() if key in allowed_keys}


def _build_reference_scoring_payload(
    *,
    goal: str,
    target_script_path: str,
    passed_references: list[dict[str, Any]],
    blocked_references: list[dict[str, Any]],
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    scored_references = [
        _serialize_scored_reference(reference)
        for reference in [*passed_references, *blocked_references]
    ]
    scored_references.sort(
        key=lambda item: (
            {"use": 0, "use_with_caution": 1, "skip": 2}.get(str(item.get("recommended_use")), 3),
            -float(item.get("compatibility_score") or 0),
        )
    )

    recommended_references = [
        item
        for item in scored_references
        if item.get("recommended_use") in {"use", "use_with_caution"}
    ]
    rejected_references = [
        item
        for item in scored_references
        if item.get("recommended_use") == "skip"
    ]
    agent_review = next(
        (
            ((item.get("scorecard") or {}).get("agent_review"))
            for item in recommended_references
            if isinstance((item.get("scorecard") or {}).get("agent_review"), dict)
        ),
        None,
    )

    usable_count = len(recommended_references)
    low_risk_count = sum(1 for item in recommended_references if item.get("recommended_use") == "use")
    high_risk_count = sum(1 for item in scored_references if item.get("risk_level") == "high")
    gate_reasons: list[str] = []
    if usable_count == 0:
        gate_reasons.append("no_usable_references")
    if usable_count > 0 and low_risk_count == 0:
        gate_reasons.append("only_use_with_caution_references")
    if scored_references and scored_references[0].get("hard_blockers"):
        gate_reasons.append("best_reference_has_hard_blockers")
    if scored_references and high_risk_count > len(scored_references) / 2:
        gate_reasons.append("high_risk_references_dominate")

    apply_gate = {
        "blocked": bool(gate_reasons),
        "can_preview": usable_count > 0,
        "reasons": gate_reasons,
    }
    return {
        "status": "success",
        "goal": goal,
        "target_script_path": target_script_path,
        "scored_references": scored_references,
        "recommended_references": recommended_references,
        "rejected_references": rejected_references,
        "scoring_summary": {
            "total": len(scored_references),
            "recommended": usable_count,
            "rejected": len(rejected_references),
            "low_risk": low_risk_count,
            "high_risk": high_risk_count,
        },
        "agent_review": agent_review or {
            "status": "skipped",
            "reviewed_reference_ids": [],
            "dimensions": [],
            "top_risks": [],
            "suggested_refactors": [],
            "summary": "",
        },
        "apply_gate": apply_gate,
        "warnings": warnings or [],
        "next_action": (
            "Use recommended_references for adaptation preview."
            if usable_count
            else "Refine the search query or relax scoring rules before adapting."
        ),
    }


async def _score_reference_candidates(
    *,
    goal: str,
    target_script_path: str,
    references: list[dict[str, Any]],
    project_root: Path,
    run_agent_observer: bool = False,
) -> dict[str, Any]:
    normalized: list[dict[str, Any]] = []
    for reference in references:
        item = dict(reference)
        try:
            item["score"] = float(item.get("score") or 0.0)
        except (TypeError, ValueError):
            item["score"] = 0.0
        normalized.append(item)

    rules = load_rules()
    project_summary = _build_project_summary(target_script_path, str(project_root))
    passed, blocked = await evaluate_references_async(
        references=normalized,
        project_summary=project_summary,
        rules=rules,
        run_agent_observer=run_agent_observer,
    )
    return _build_reference_scoring_payload(
        goal=goal,
        target_script_path=target_script_path,
        passed_references=passed,
        blocked_references=blocked,
    )


def _distill_reference_candidates(
    *,
    goal: str,
    target_script_path: str,
    reference_scoring: dict[str, Any],
    project_root: Path,
    context_depth: int = 3,
) -> dict[str, Any]:
    target_path = (project_root / target_script_path.replace("/", os.sep)).resolve()
    context = collect_project_context(project_root, target_path, context_depth=context_depth)
    return distill_reference_patterns(
        goal=goal,
        target_script_path=target_script_path,
        reference_scoring=reference_scoring,
        target_content=str(context.get("target_content", "")),
        sample_scripts=context.get("sample_scripts", []),
        max_patterns=3,
    )


def _keyword_score(item: dict[str, Any], terms: list[str], class_name: str = "", code_type: str = "") -> float:
    metadata = item.get("metadata") or {}
    text = item.get("text", "")
    haystack = " ".join([
        text,
        str(metadata.get("file_path", "")),
        str(metadata.get("class_name", "")),
        str(metadata.get("method_name", "")),
        str(metadata.get("code_type", "")),
        str(metadata.get("game_name", "")),
    ]).lower()

    if not terms:
        return 0.1

    hits = sum(haystack.count(term) for term in terms)
    unique_hits = sum(1 for term in terms if term in haystack)
    score = unique_hits / max(1, len(terms)) + min(hits, 12) * 0.03

    if class_name and str(metadata.get("class_name", "")).lower() == class_name.lower():
        score += 0.4
    if code_type and str(metadata.get("code_type", "")).lower() == code_type.lower():
        score += 0.2
    if str(metadata.get("code_type", "")).lower() == "method_detail":
        score += 0.05

    return round(min(score, 0.99), 4)


def _keyword_search_code(
    query: str,
    top_k: int,
    game_name: str = "",
    class_name: str = "",
    code_type: str = "",
    include_assets: bool = False,
) -> list[dict[str, Any]]:
    config = _load_config()
    vector_dir = config.get("vector_store", {}).get("persist_directory", "")
    collection_name = config.get("vector_store", {}).get("collection_name", "game_source_code")
    if not vector_dir:
        return [{"error": "Game code vector_store.persist_directory is not configured."}]

    try:
        import chromadb

        client = chromadb.PersistentClient(path=str(vector_dir))
        collection = client.get_collection(collection_name)
    except Exception as exc:
        return [{"error": f"Failed to open game code ChromaDB collection: {exc}"}]

    where: dict[str, Any] = {}
    if game_name:
        where["game_name"] = game_name
    if class_name:
        where["class_name"] = class_name
    if code_type:
        where["code_type"] = code_type

    try:
        raw = collection.get(
            where=where if where else None,
            include=["documents", "metadatas"],
            limit=_KEYWORD_SCAN_LIMIT,
        )
    except Exception:
        raw = collection.get(include=["documents", "metadatas"], limit=_KEYWORD_SCAN_LIMIT)

    ids = raw.get("ids", []) or []
    documents = raw.get("documents", []) or []
    metadatas = raw.get("metadatas", []) or []
    terms = _keyword_terms(query)
    ranked: list[dict[str, Any]] = []

    for doc_id, text, metadata in zip(ids, documents, metadatas):
        metadata = metadata or {}
        if game_name and str(metadata.get("game_name", "")).lower() != game_name.lower():
            continue
        if class_name and str(metadata.get("class_name", "")).lower() != class_name.lower():
            continue
        if code_type and str(metadata.get("code_type", "")).lower() != code_type.lower():
            continue
        if not include_assets and metadata.get("code_type", "") not in _CODE_TYPES:
            continue
        score = _keyword_score({"text": text, "metadata": metadata}, terms, class_name, code_type)
        if score <= 0:
            continue
        ranked.append({
            "id": doc_id,
            "text": text,
            "metadata": metadata,
            "score": score,
        })

    ranked.sort(key=lambda item: item.get("score", 0), reverse=True)
    return ranked[: max(1, min(20, top_k))]


async def _search_code_with_timeout(
    searcher,
    query: str,
    top_k: int,
    game_name: str = "",
    class_name: str = "",
    code_type: str = "",
    include_assets: bool = False,
) -> tuple[list[dict[str, Any]], str]:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                _search_code,
                searcher,
                query,
                top_k,
                game_name,
                class_name,
                code_type,
                include_assets,
            ),
            timeout=_SEMANTIC_SEARCH_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Semantic game code search timed out after %ss for query=%r; using keyword fallback.",
            _SEMANTIC_SEARCH_TIMEOUT_SECONDS,
            query,
        )
        return _keyword_search_code(query, top_k, game_name, class_name, code_type, include_assets), "keyword_timeout_fallback"


def _search_code(
    searcher,
    query: str,
    top_k: int,
    game_name: str = "",
    class_name: str = "",
    code_type: str = "",
    include_assets: bool = False,
) -> tuple[list[dict[str, Any]], str]:
    force_keyword = os.getenv("UNITY_MCP_GAME_CODE_FORCE_KEYWORD", "").strip().lower() in {"1", "true", "yes", "on"}
    embedding_ok, embedding_reason = _embedding_config_is_usable(getattr(searcher, "config", {}) or {})
    if force_keyword or not embedding_ok:
        results = _keyword_search_code(query, top_k, game_name, class_name, code_type, include_assets)
        if not embedding_ok and results and isinstance(results[0], dict):
            for result in results:
                metadata = result.setdefault("metadata", {})
                metadata["search_warning"] = embedding_reason
        return results, "keyword_fallback"

    results = searcher.search(
        query=query,
        top_k=top_k,
        game_name=game_name or None,
        class_name=class_name or None,
        code_type=code_type or None,
        include_assets=include_assets,
    )
    return results, "default"


def get_game_code_module_status() -> dict[str, Any]:
    """Return product-facing status for the external game source code RAG."""
    try:
        config = _load_config()
    except Exception as exc:
        config = {}
        config_error = str(exc)
    else:
        config_error = ""
    vector_dir = Path(config.get("vector_store", {}).get("persist_directory", ""))
    graph_path = Path(config.get("graph", {}).get("file_path", ""))

    status: dict[str, Any] = {
        "id": "game_source_code",
        "name": "Game Source Code RAG",
        "installed": _GAME_RAG_ROOT.exists(),
        "status": "missing",
        "root": str(_GAME_RAG_ROOT),
        "config_path": str(_GAME_RAG_CONFIG),
        "vector_store": {
            "persist_directory": str(vector_dir) if str(vector_dir) else "",
            "exists": vector_dir.exists() if str(vector_dir) else False,
            "collection": config.get("vector_store", {}).get("collection_name", "game_source_code"),
        },
        "graph": {
            "file_path": str(graph_path) if str(graph_path) else "",
            "exists": graph_path.exists() if str(graph_path) else False,
        },
    }

    if not _GAME_RAG_ROOT.exists():
        status["hint"] = "Expected Server/data/game-rag-knowledge-base under unity-ai-assistant-product."
        return status

    if not _GAME_RAG_CONFIG.exists():
        status["status"] = "not_configured"
        status["hint"] = "Missing config/config_game.yaml."
        return status

    if config_error:
        status["status"] = "unavailable"
        status["error"] = config_error
        return status

    try:
        collection_name = config.get("vector_store", {}).get("collection_name", "game_source_code")
        document_count = 0
        if vector_dir.exists():
            try:
                import chromadb

                client = chromadb.PersistentClient(path=str(vector_dir))
                collection = client.get_collection(collection_name)
                document_count = collection.count()
            except Exception as count_exc:
                status["count_warning"] = str(count_exc)

        if vector_dir.exists() and document_count > 0:
            status["status"] = "active"
            status["document_count"] = document_count
        else:
            status["status"] = "not_built"
            status["hint"] = "Run Server/data/game-rag-knowledge-base/build_game_rag.py first."
    except Exception as exc:
        status["status"] = "error"
        status["error"] = str(exc)

    return status


def _update_adapt_task(task: AdaptTask | None, phase: str, progress: float) -> None:
    if task is not None:
        task.update(phase=phase, progress=progress)


def _build_task_status_payload(
    task: AdaptTask,
    *,
    include_generated_code: bool = True,
    include_adapt_compat: bool = False,
) -> dict[str, Any]:
    payload = task.to_dict(include_generated_code=include_generated_code)
    if task.status == "completed" and isinstance(task.result, dict):
        payload["result_status"] = task.result.get("status")
        if include_adapt_compat and task.task_type == "adapt_game_code":
            payload["adapt_result_status"] = task.result.get("status")
        payload.update({key: value for key, value in task.result.items() if key != "status"})
        # Propagate model metadata for diagnostics
        if task.result.get("_ollama"):
            payload["model_info"] = task.result["_ollama"]
    elif task.status == "failed" and isinstance(task.result, dict):
        # Propagate error_code for failure classification
        error_code = task.result.get("error_code", "")
        if error_code:
            payload["error_code"] = error_code
            # Map to human-readable failure category
            error_category_map = {
                "ollama_unavailable": "ollama_unavailable",
                "generation_json_parse_failed": "generation_json_parse_failed",
                "generated_code_incomplete": "generated_code_incomplete",
            }
            payload["failure_category"] = error_category_map.get(error_code, "generation_failed")
        # Propagate model metadata even on failure
        if task.result.get("_ollama"):
            payload["model_info"] = task.result["_ollama"]
    return payload


async def _run_adapt_preview(
    goal: str,
    target_script_path: str,
    reference_results_json: str,
    context_depth: int = 3,
    task: AdaptTask | None = None,
    api_graph_context: str | None = None,
    game_code_context: str | None = None,
) -> dict[str, Any]:
    status: str = "preview"
    warnings: list[str] = []
    adaptation_notes: list[str] = []
    # 将图谱上下文注入 adaptation_notes，供 LLM 生成代码时参考
    if api_graph_context:
        adaptation_notes.append(f"[api_graph_context] {api_graph_context[:500]}")
    if game_code_context:
        adaptation_notes.append(f"[game_code_context] {game_code_context[:500]}")
    planned_edits: list[str] = []
    project_style_summary: dict[str, Any] = {}
    matched_references: list[dict[str, Any]] = []
    quality_audit: dict[str, Any] = {"status": "not_run", "issues": [], "warnings": [], "needs_repair": False}
    generated_code = ""
    write_result: dict[str, Any] | None = None
    logs_excerpt: list[dict[str, Any]] = []

    _update_adapt_task(task, "prepare", 0.05)
    ollama_meta: dict[str, Any] = {}

    try:
        references, ref_warnings = parse_reference_results(reference_results_json)
        matched_references = references
        warnings.extend(ref_warnings)
    except ValueError as exc:
        status = "error"
        return {
            "status": status,
            "error_code": "invalid_reference_json",
            "goal": goal,
            "target_script_path": target_script_path,
            "error": str(exc),
            "warnings": warnings + [str(exc)],
            "apply_ready": False,
            "write_result": write_result,
            "compile_result": _normalize_compile_result(None, "not_run", warnings),
            "logs_excerpt": logs_excerpt,
            "quality_audit": quality_audit,
            "next_action": _build_next_action(status, apply=False),
        }

    try:
        bridge = get_bridge()
        unity_info = await bridge.get_unity_info()
    except Exception as exc:
        status = "unavailable"
        return {
            "status": status,
            "error_code": "unity_unavailable",
            "goal": goal,
            "target_script_path": target_script_path,
            "error": f"Unity connection unavailable: {exc}",
            "warnings": warnings,
            "apply_ready": False,
            "write_result": write_result,
            "compile_result": _normalize_compile_result(None, "not_run", warnings),
            "logs_excerpt": logs_excerpt,
            "quality_audit": quality_audit,
            "next_action": _build_next_action(status, apply=False),
        }

    try:
        editor_state_result = await send_to_unity("manage_editor", {"action": "get_editor_state"})
        editor_state = editor_state_result.get("result", {}) if isinstance(editor_state_result, dict) else {}
    except Exception as exc:
        editor_state = {}
        warnings.append(f"Failed to read editor state: {exc}")

    _update_adapt_task(task, "context", 0.18)
    try:
        project_root, target_path = resolve_target_script(unity_info, target_script_path)
        context = collect_project_context(project_root, target_path, context_depth=context_depth)
        if api_graph_context or game_code_context:
            context["graphrag_context"] = {
                "api_graph_context": api_graph_context or "",
                "game_code_context": game_code_context or "",
            }
        project_style_summary = context.get("style_summary", {})
    except FileNotFoundError as exc:
        status = "error"
        return {
            "status": status,
            "error_code": "target_not_found",
            "goal": goal,
            "target_script_path": target_script_path,
            "error": str(exc),
            "warnings": warnings + ["Create the script first or point to an existing Assets/.../*.cs file."],
            "apply_ready": False,
            "write_result": write_result,
            "compile_result": _normalize_compile_result(None, "not_run", warnings),
            "logs_excerpt": logs_excerpt,
            "quality_audit": quality_audit,
            "next_action": _build_next_action(status, apply=False),
        }
    except ValueError as exc:
        status = "error"
        return {
            "status": status,
            "error_code": "invalid_target_path",
            "goal": goal,
            "target_script_path": target_script_path,
            "error": str(exc),
            "warnings": warnings,
            "apply_ready": False,
            "write_result": write_result,
            "compile_result": _normalize_compile_result(None, "not_run", warnings),
            "logs_excerpt": logs_excerpt,
            "quality_audit": quality_audit,
            "next_action": _build_next_action(status, apply=False),
        }

    prompt = build_adaptation_prompt(goal, unity_info, editor_state, context, matched_references)

    try:
        _update_adapt_task(task, "generate", 0.32)
        adaptation = await call_ollama_for_adaptation(prompt)
        ollama_meta = adaptation.get("_ollama", {})
        generated_code = ensure_usings(adaptation.get("generated_code", ""), original_code=context.get("target_content", ""))
        adaptation_notes = adaptation_notes + adaptation.get("adaptation_notes", [])
        planned_edits = adaptation.get("planned_edits", [])
        warnings.extend(adaptation.get("warnings", []))
        _update_adapt_task(task, "audit", 0.78)
        quality_audit = audit_generated_adaptation(
            goal,
            generated_code,
            matched_references,
            adaptation_notes,
            planned_edits,
            context=context,
        )
        if quality_audit.get("needs_repair") and should_repair_adaptation():
            _update_adapt_task(task, "repair", 0.84)
            repair_prompt = build_repair_prompt(prompt, generated_code, quality_audit)
            repaired = await call_ollama_for_adaptation(repair_prompt)
            ollama_meta = repaired.get("_ollama", ollama_meta)  # Preserve repair model info
            generated_code = ensure_usings(repaired.get("generated_code", generated_code), original_code=context.get("target_content", ""))
            adaptation_notes = repaired.get("adaptation_notes", adaptation_notes)
            planned_edits = repaired.get("planned_edits", planned_edits)
            warnings.extend(repaired.get("warnings", []))
            _update_adapt_task(task, "audit", 0.94)
            quality_audit = audit_generated_adaptation(
                goal,
                generated_code,
                matched_references,
                adaptation_notes,
                planned_edits,
                context=context,
            )
    except RuntimeError as exc:
        status = "unavailable"
        return {
            "status": status,
            "error_code": "ollama_unavailable",
            "goal": goal,
            "target_script_path": target_script_path,
            "error": str(exc),
            "matched_references": matched_references,
            "project_style_summary": project_style_summary,
            "adaptation_notes": adaptation_notes,
            "generated_code": generated_code,
            "planned_edits": planned_edits,
            "warnings": warnings + [str(exc)],
            "quality_audit": {"status": "unavailable", "error": str(exc)},
            "apply_ready": False,
            "write_result": write_result,
            "compile_result": _normalize_compile_result(None, "not_run", warnings),
            "logs_excerpt": logs_excerpt,
            "next_action": _build_next_action(status, apply=False, quality_audit=quality_audit),
        }
    except AdaptationParseError as exc:
        status = "error"
        return {
            "status": status,
            "error_code": exc.error_code,
            "goal": goal,
            "target_script_path": target_script_path,
            "error": str(exc),
            "matched_references": matched_references,
            "project_style_summary": project_style_summary,
            "adaptation_notes": adaptation_notes,
            "generated_code": generated_code,
            "planned_edits": planned_edits,
            "warnings": warnings + [str(exc)],
            "quality_audit": {"status": "parse_error", "error_code": exc.error_code, "error": str(exc)},
            "apply_ready": False,
            "write_result": write_result,
            "compile_result": _normalize_compile_result(None, "not_run", warnings),
            "logs_excerpt": logs_excerpt,
            "next_action": _build_next_action(status, apply=False, quality_audit=quality_audit, error_code=exc.error_code),
        }
    except Exception as exc:
        status = "error"
        return {
            "status": status,
            "error_code": "generation_failed",
            "goal": goal,
            "target_script_path": target_script_path,
            "error": str(exc),
            "matched_references": matched_references,
            "project_style_summary": project_style_summary,
            "adaptation_notes": adaptation_notes,
            "generated_code": generated_code,
            "planned_edits": planned_edits,
            "warnings": warnings + [str(exc)],
            "quality_audit": {"status": "error", "error": str(exc)},
            "apply_ready": False,
            "write_result": write_result,
            "compile_result": _normalize_compile_result(None, "not_run", warnings),
            "logs_excerpt": logs_excerpt,
            "next_action": _build_next_action(status, apply=False, quality_audit=quality_audit),
        }

    apply_ready = bool(generated_code.strip())
    _update_adapt_task(task, "ready", 0.98)
    return {
        "status": status,
        "goal": goal,
        "target_script_path": target_script_path,
        "matched_references": matched_references,
        "project_style_summary": project_style_summary,
        "adaptation_notes": adaptation_notes,
        "generated_code": generated_code,
        "planned_edits": planned_edits,
        "warnings": warnings,
        "quality_audit": quality_audit,
        "apply_ready": apply_ready,
        "write_result": write_result,
        "compile_result": _normalize_compile_result(None, "not_run", warnings),
        "logs_excerpt": logs_excerpt,
        "next_action": _build_next_action(status, apply=False, quality_audit=quality_audit),
        "_ollama": ollama_meta,
    }


async def _apply_adapt_preview_result(preview_result: dict[str, Any], task: AdaptTask | None = None) -> dict[str, Any]:
    status = "preview"
    goal = str(preview_result.get("goal", ""))
    target_script_path = str(preview_result.get("target_script_path", ""))
    matched_references = preview_result.get("matched_references", [])
    project_style_summary = preview_result.get("project_style_summary", {})
    adaptation_notes = preview_result.get("adaptation_notes", [])
    generated_code = str(preview_result.get("generated_code", ""))
    planned_edits = preview_result.get("planned_edits", [])
    warnings = list(preview_result.get("warnings", []))
    quality_audit = preview_result.get("quality_audit", {})
    logs_excerpt = list(preview_result.get("logs_excerpt", []))
    write_result: dict[str, Any] | None = None

    if not generated_code.strip():
        status = "error"
        return {
            **preview_result,
            "status": status,
            "error_code": "empty_generated_code",
            "warnings": warnings + ["Generated code was empty."],
            "apply_ready": False,
            "write_result": write_result,
            "compile_result": _normalize_compile_result(None, "not_run", warnings),
            "logs_excerpt": logs_excerpt,
            "next_action": _build_next_action(status, apply=True, quality_audit=quality_audit),
        }

    _update_adapt_task(task, "apply", 0.05)
    try:
        bridge = get_bridge()
        unity_info = await bridge.get_unity_info()
        project_root, target_path = resolve_target_script(unity_info, target_script_path)
    except Exception as exc:
        status = "unavailable"
        return {
            **preview_result,
            "status": status,
            "error_code": "unity_unavailable",
            "error": f"Unity connection unavailable: {exc}",
            "warnings": warnings,
            "apply_ready": True,
            "write_result": write_result,
            "compile_result": _normalize_compile_result(None, "not_run", warnings),
            "logs_excerpt": logs_excerpt,
            "next_action": _build_next_action(status, apply=True, quality_audit=quality_audit),
        }

    folder = str(target_path.parent.relative_to(project_root)).replace("\\", "/")
    if folder == ".":
        folder = "Assets"
    script_name = target_path.stem

    try:
        write_result = await send_to_unity(
            "manage_script",
            {
                "action": "update",
                "folder": folder,
                "name": script_name,
                "content": generated_code,
            },
        )
        if write_result.get("status") != "success":
            raise RuntimeError(write_result.get("error") or str(write_result))
    except Exception as exc:
        # Fallback: write directly to disk when Unity plugin lacks update support
        try:
            target_path.write_text(generated_code, encoding="utf-8")
            write_result = {"status": "success", "file_path": str(target_path), "fallback_direct_write": True}
            warnings.append(f"manage_script update failed ({exc}); fell back to direct file write.")
        except Exception as write_exc:
            status = "error"
            return {
            "status": status,
            "error_code": "write_failed",
            "goal": goal,
            "target_script_path": target_script_path,
            "matched_references": matched_references,
            "project_style_summary": project_style_summary,
            "adaptation_notes": adaptation_notes,
            "generated_code": generated_code,
            "planned_edits": planned_edits,
            "warnings": warnings + [f"Failed to write target script: {exc}"],
            "quality_audit": quality_audit,
            "apply_ready": True,
            "write_result": write_result,
            "compile_result": _normalize_compile_result(None, "not_run", warnings),
            "logs_excerpt": logs_excerpt,
            "next_action": _build_next_action(status, apply=True, quality_audit=quality_audit),
        }

    try:
        await send_to_unity("manage_editor", {"action": "refresh", "force": False})
    except Exception as exc:
        warnings.append(f"Refresh request returned an error; Unity may be recompiling: {exc}")

    _update_adapt_task(task, "compile_check", 0.45)
    compile_status, reconnect_error, compile_result, compile_warnings = (
        await _wait_for_compile_after_script_write()
    )
    if reconnect_error:
        warnings.append(f"Unity reconnect issue after script write: {reconnect_error}")
    warnings.extend(compile_warnings)

    try:
        logs_result = await send_to_unity(
            "manage_editor",
            {
                "action": "get_unity_logs",
                "limit": 20,
                "show_logs": False,
                "show_warnings": True,
                "show_errors": True,
                "show_stack_traces": False,
                "search_term": script_name,
            },
        )
        logs_excerpt = (logs_result.get("result", {}) or {}).get("logs", [])[:10]
    except Exception as exc:
        warnings.append(f"Could not read Unity logs: {exc}")

    compile_payload = (compile_result or {}).get("result", {}) if isinstance(compile_result, dict) else {}
    has_errors = bool(compile_payload.get("has_errors", False))
    if has_errors:
        status = "applied_with_compile_errors"
    else:
        status = "applied" if compile_status != "unknown" else "applied_pending_compile"

    normalized_compile_result = _normalize_compile_result(compile_result, compile_status, warnings)
    _update_adapt_task(task, "compile_check", 0.95)
    return {
        "status": status,
        "goal": goal,
        "target_script_path": target_script_path,
        "matched_references": matched_references,
        "project_style_summary": project_style_summary,
        "adaptation_notes": adaptation_notes,
        "generated_code": generated_code,
        "planned_edits": planned_edits,
        "warnings": warnings,
        "quality_audit": quality_audit,
        "apply_ready": True,
        "write_result": write_result,
        "compile_result": normalized_compile_result,
        "logs_excerpt": logs_excerpt,
        "next_action": _build_next_action(
            status,
            apply=True,
            quality_audit=quality_audit,
            compile_status=compile_status,
        ),
    }


# ── GraphRAG 上下文打分 & 查询构造器 ──────────────────────────────

def _score_graphrag_context(
    context: str | None,
    goal: str,
    target_script_path: str,
    *,
    context_type: str = "graph",
) -> dict[str, Any]:
    """轻量相关性评分，决定是否注入 context 到 prompt。

    Returns:
        {"relevance": "high"|"medium"|"low"|"none", "score": 0.0-1.0,
         "reason": str, "inject": bool}
    """
    if not context or not context.strip():
        return {
            "relevance": "none", "score": 0.0,
            "reason": "empty context", "inject": False,
            "context_type": context_type,
        }

    context_lower = context.lower()
    matched_keywords: list[str] = []
    total_signals = 0
    script_hits = 0

    # 1) goal 关键词匹配
    goal_lower = goal.lower()
    goal_words = [w for w in goal_lower.split() if len(w) > 2 and w not in ("the", "and", "for", "that", "with", "this", "from")]
    goal_hits = sum(1 for w in goal_words if w in context_lower)
    total_signals += len(goal_words)
    matched_keywords.extend(w for w in goal_words if w in context_lower)

    # 2) target_script 类名拆分匹配（CamelCase → 单词）
    if target_script_path:
        import re
        script_stem = Path(target_script_path).stem
        script_words = [w.lower() for w in re.findall(r'[A-Z][a-z]+|[a-z]+', script_stem) if len(w) > 1]
        script_hits = sum(1 for w in script_words if w in context_lower)
        total_signals += max(len(script_words), 1)
        matched_keywords.extend(w for w in script_words if w in context_lower)

    # 3) context 本身不为空就是正面信号
    total_signals = max(total_signals, 1)
    match_ratio = (goal_hits + script_hits * 1.5) / total_signals
    score = round(min(match_ratio, 1.0), 2)

    if score >= 0.25:
        return {
            "relevance": "high", "score": score,
            "reason": f"{len(set(matched_keywords))} keywords matched ({goal_hits} goal, {script_hits} script)",
            "inject": True, "context_type": context_type,
        }
    elif score >= 0.1:
        return {
            "relevance": "medium", "score": score,
            "reason": f"weak match ({goal_hits}/{script_hits} keywords)",
            "inject": True, "context_type": context_type,
        }
    else:
        return {
            "relevance": "low", "score": score,
            "reason": f"no meaningful match ({goal_hits}/{script_hits} keywords)",
            "inject": False, "context_type": context_type,
        }


def _build_graphrag_query(
    goal: str,
    target_script_path: str,
    *,
    filtered_references: list[dict[str, Any]] | None = None,
) -> str:
    """基于 goal + 目标类名/方法名 + 参考代码类名 构造 GraphRAG 精准查询。"""
    parts = [goal]

    if target_script_path:
        script_stem = Path(target_script_path).stem
        parts.append(f"pattern like {script_stem}")

    if filtered_references:
        class_names: list[str] = []
        for ref in filtered_references[:3]:
            cn = ref.get("class_name", "") or ref.get("id", "") or ""
            cn = cn.split("_")[-1] if "_" in cn else cn
            if cn and cn not in class_names:
                class_names.append(cn)
        if class_names:
            parts.append(f"related to {', '.join(class_names[:5])}")

    return " ".join(parts)


async def _run_game_dev_agent_with_reference_scoring(
    goal: str,
    target_script_path: str = "",
    apply: bool = False,
    context_depth: int = 3,
    task: AdaptTask | None = None,
) -> dict[str, Any]:
    warnings: list[str] = []
    selected_references: list[dict[str, Any]] = []
    target_selection: dict[str, Any] = {}
    adapt_result: dict[str, Any] | None = None
    unified_search: dict[str, Any] | None = None
    knowledge_sources: dict[str, Any] = {}
    api_graph_context: str | None = None
    game_code_context: str | None = None
    knowledge_usage_audit: dict[str, Any] = {
        "sources_used": [],
        "contexts_injected": [],
        "relevance_summary": {},
        "warnings": [],
    }

    _update_adapt_task(task, "inspect_project", 0.05)
    try:
        bridge = get_bridge()
        unity_info = await bridge.get_unity_info()
    except Exception as exc:
        return {
            "status": "unavailable",
            "error_code": "unity_unavailable",
            "goal": goal,
            "target_script_path": target_script_path,
            "target_selection": target_selection,
            "selected_references": selected_references,
            "filtered_references": [],
            "reference_scoring": None,
            "apply_gate": {},
            "adapt_result": adapt_result,
            "quality_audit": {},
            "warnings": warnings,
            "knowledge_usage_audit": knowledge_usage_audit,
                "knowledge_sources": knowledge_sources,
                "unified_search": unified_search,
            "error": f"Unity connection unavailable: {exc}",
            "next_action": "Open the Unity project and reconnect the MCP bridge, then retry start_game_dev_agent.",
        }

    project_root = Path(
        unity_info.get("project_path")
        or unity_info.get("projectRoot")
        or unity_info.get("root")
        or ""
    )
    if project_root.name == "Assets":
        project_root = project_root.parent

    if target_script_path:
        target_selection = {
            "status": "provided",
            "target_script_path": target_script_path,
            "confidence": "explicit",
            "candidates": [],
        }
    else:
        _update_adapt_task(task, "select_target", 0.12)
        target_selection = _select_target_script(project_root, goal)
        if target_selection.get("status") != "selected":
            return {
                "status": target_selection.get("status", "needs_target"),
                "error_code": "target_script_not_selected",
                "goal": goal,
                "target_script_path": "",
                "target_selection": target_selection,
                "selected_references": selected_references,
                "filtered_references": [],
                "reference_scoring": None,
                "apply_gate": {},
                "adapt_result": adapt_result,
                "quality_audit": {},
                "warnings": warnings,
                "knowledge_usage_audit": knowledge_usage_audit,
                "knowledge_sources": knowledge_sources,
                "unified_search": unified_search,
                "next_action": "Choose one candidate and rerun start_game_dev_agent with target_script_path set explicitly.",
            }
        target_script_path = str(target_selection.get("target_script_path", ""))
        warnings.extend(str(item) for item in target_selection.get("warnings", []))

    _update_adapt_task(task, "search_references", 0.22)

    # ── GraphRAG 上下文：检索 → 打分 → 门控 → audit ──────────
    # 低相关不注入 prompt，避免污染生成；仅 warning + audit 记录。
    try:
        from services.tools.rag_tools import arun_knowledge_unified_search
        graph_query = _build_graphrag_query(goal, target_script_path)
        unified_search = await arun_knowledge_unified_search(
            query=graph_query,
            sources=["api_graph", "game_code_graph"],
            graph_mode="local",
            vector_results=0,
        )
        knowledge_sources = {
            "sources_used": unified_search.get("sources_used", []),
            "source_breakdown": unified_search.get("source_breakdown", {}),
        }
        knowledge_usage_audit["sources_used"] = list(knowledge_sources.get("sources_used", []))

        # 打分 + 门控
        for ctx_type, raw_ctx in [
            ("api_graph", unified_search.get("api_graph_context")),
            ("game_code_graph", unified_search.get("game_code_context")),
        ]:
            scoring = _score_graphrag_context(
                raw_ctx, goal, target_script_path, context_type=ctx_type,
            )
            knowledge_usage_audit["relevance_summary"][ctx_type] = scoring

            if scoring["inject"]:
                if ctx_type == "api_graph":
                    api_graph_context = raw_ctx
                else:
                    game_code_context = raw_ctx
                knowledge_usage_audit["contexts_injected"].append(ctx_type)
            elif scoring["relevance"] == "low" and raw_ctx:
                msg = (
                    f"{ctx_type} context scored low ({scoring['score']}): "
                    f"{scoring['reason']}. Not injected into prompt."
                )
                warnings.append(msg)
                knowledge_usage_audit["warnings"].append(msg)
    except Exception as graph_exc:
        msg = f"GraphRAG context unavailable (non-blocking): {graph_exc}"
        warnings.append(msg)
        knowledge_sources = {"error": str(graph_exc)}
        knowledge_usage_audit["warnings"].append(msg)

    searcher = _get_searcher()
    if not searcher:
        return {
            "status": "unavailable",
            "error_code": "game_code_rag_unavailable",
            "goal": goal,
            "target_script_path": target_script_path,
            "target_selection": target_selection,
            "selected_references": selected_references,
            "filtered_references": [],
            "reference_scoring": None,
            "apply_gate": {},
            "adapt_result": adapt_result,
            "quality_audit": {},
            "warnings": warnings,
            "knowledge_usage_audit": knowledge_usage_audit,
            "knowledge_sources": knowledge_sources,
            "unified_search": unified_search,
            "error": _game_code_import_error or "Game source code RAG is not available.",
            "module_status": get_game_code_module_status(),
            "next_action": "cd Server/data/game-rag-knowledge-base && python build_game_rag.py  # Build the RAG index, then retry start_game_dev_agent.",
        }

    reference_query = _build_agent_reference_query(goal, project_root, target_script_path)
    results, search_mode = await _search_code_with_timeout(
        searcher=searcher,
        query=reference_query,
        top_k=5,
    )
    selected_references = [_format_code_result(item) for item in results if not item.get("error")][:5]
    if not selected_references:
        return {
            "status": "error",
            "error_code": "no_reference_results",
            "goal": goal,
            "target_script_path": target_script_path,
            "target_selection": target_selection,
            "selected_references": selected_references,
            "filtered_references": [],
            "reference_scoring": None,
            "apply_gate": {},
            "adapt_result": adapt_result,
            "quality_audit": {},
            "warnings": warnings,
            "knowledge_usage_audit": knowledge_usage_audit,
            "knowledge_sources": knowledge_sources,
            "unified_search": unified_search,
            "search_mode": search_mode,
            "reference_query": reference_query,
            "next_action": "Retry with a more concrete goal or use search_game_code manually to find references.",
        }

    _update_adapt_task(task, "score_references", 0.28)
    try:
        reference_scoring = await _score_reference_candidates(
            goal=goal,
            target_script_path=target_script_path,
            references=selected_references,
            project_root=project_root,
            run_agent_observer=False,
        )
    except Exception as exc:
        warnings.append(f"score_references failed: {exc}. Keeping top references unfiltered.")
        reference_scoring = {
            "status": "error",
            "error": str(exc),
            "recommended_references": selected_references[:3],
            "rejected_references": [],
            "scored_references": selected_references[:3],
            "apply_gate": {"blocked": False, "can_preview": True, "reasons": ["scoring_failed"]},
            "scoring_summary": {
                "total": len(selected_references[:3]),
                "recommended": len(selected_references[:3]),
                "rejected": 0,
            },
            "warnings": [str(exc)],
        }

    apply_gate = reference_scoring.get("apply_gate", {})
    _update_adapt_task(task, "distill_patterns", 0.32)
    try:
        reference_patterns = _distill_reference_candidates(
            goal=goal,
            target_script_path=target_script_path,
            reference_scoring=reference_scoring,
            project_root=project_root,
            context_depth=context_depth,
        )
    except Exception as exc:
        warnings.append(f"distill_patterns failed: {exc}. Falling back to scored references.")
        reference_patterns = {
            "status": "error",
            "error": str(exc),
            "distilled_patterns": [],
            "dependency_map": {},
            "target_mapping": {},
            "implementation_constraints": [],
            "rejected_references": reference_scoring.get("rejected_references", []),
            "warnings": [str(exc)],
            "apply_gate": {"blocked": False, "can_preview": True, "reasons": ["pattern_distillation_failed"]},
        }

    pattern_gate = reference_patterns.get("apply_gate", {})
    filtered_references = make_pattern_references(reference_patterns)
    if not filtered_references and reference_patterns.get("status") == "error":
        filtered_references = [
            _scored_reference_for_adaptation(reference)
            for reference in reference_scoring.get("recommended_references", [])[:3]
        ]

    if not filtered_references:
        return {
            "status": "blocked_by_reference_pattern_distillation",
            "error_code": "no_usable_distilled_patterns",
            "goal": goal,
            "target_script_path": target_script_path,
            "target_selection": target_selection,
            "selected_references": selected_references,
            "filtered_references": [],
            "reference_patterns": reference_patterns,
            "reference_scoring": reference_scoring,
            "apply_gate": pattern_gate or apply_gate,
            "adapt_result": adapt_result,
            "quality_audit": {},
            "warnings": warnings,
            "knowledge_usage_audit": knowledge_usage_audit,
            "knowledge_sources": knowledge_sources,
            "unified_search": unified_search,
            "search_mode": search_mode,
            "reference_query": reference_query,
            "next_action": "Search for better references or refine the goal before running adaptation.",
        }

    _update_adapt_task(task, "adapt_preview", 0.36)
    reference_results_json = _json({"status": "success", "results": filtered_references})
    adapt_result = await _run_adapt_preview(
        goal=goal,
        target_script_path=target_script_path,
        reference_results_json=reference_results_json,
        context_depth=context_depth,
        task=task,
        api_graph_context=api_graph_context,
        game_code_context=game_code_context,
    )

    final_result = adapt_result
    combined_apply_gate = {
        "blocked": bool(apply_gate.get("blocked") or pattern_gate.get("blocked")),
        "can_preview": bool((apply_gate.get("can_preview", True)) and (pattern_gate.get("can_preview", True))),
        "reasons": list(apply_gate.get("reasons", [])) + list(pattern_gate.get("reasons", [])),
    }
    if apply and combined_apply_gate.get("blocked"):
        warnings.append(
            "apply=true was requested, but reference scoring/pattern distillation blocked automatic apply: "
            + ", ".join(combined_apply_gate.get("reasons", []))
        )
    elif apply and adapt_result.get("apply_ready"):
        _update_adapt_task(task, "apply", 0.82)
        final_result = await _apply_adapt_preview_result(adapt_result, task=task)
    elif apply:
        warnings.append("apply=true was requested, but the adaptation result was not apply_ready.")

    quality_audit = final_result.get("quality_audit") if isinstance(final_result, dict) else {}
    result_status = final_result.get("status") if isinstance(final_result, dict) else "error"
    return {
        "status": result_status,
        "goal": goal,
        "target_script_path": target_script_path,
        "target_selection": target_selection,
        "selected_references": selected_references,
        "filtered_references": filtered_references,
        "search_mode": search_mode,
        "reference_query": reference_query,
        "reference_scoring": reference_scoring,
        "reference_patterns": reference_patterns,
        "distilled_patterns": reference_patterns.get("distilled_patterns", []),
        "apply_gate": combined_apply_gate,
        "adapt_result": final_result,
        "quality_audit": quality_audit or {},
        "warnings": warnings + list(final_result.get("warnings", []) if isinstance(final_result, dict) else []),
        "knowledge_usage_audit": knowledge_usage_audit,
        "knowledge_sources": knowledge_sources,
        "unified_search": unified_search,
        "next_action": (
            "Review adapt_result; reference scoring or pattern distillation blocked automatic apply."
            if apply and combined_apply_gate.get("blocked")
            else (
                "Review adapt_result and call apply_adapt_task on a dedicated adapt task if you want a separate apply step."
                if not apply
                else final_result.get("next_action", "Inspect adapt_result for compile status and next steps.")
            )
        ),
    }


def register_game_code_tools(mcp) -> None:
    """Register game source code RAG tools."""

    @mcp.tool(
        name="search_game_code",
        description="""Search indexed Unity game source code for reusable implementation patterns.

Use before writing gameplay/UI/systems code. Results include source file, class,
method, line metadata, a short summary, and reuse guidance for adapting the
reference to the current Unity project.""",
        tags=make_group_tags("rag"),
    )
    async def search_game_code(
        query: str,
        top_k: int = 5,
        game_name: str = "",
        class_name: str = "",
        code_type: str = "",
        include_assets: bool = False,
        target: str = "",
        method_name: str = "",
        type: str = "",
    ) -> str:
        compat_params_used: dict[str, Any] = {}
        if type and not code_type:
            code_type = str(type)
            compat_params_used["type"] = "code_type"
        if target:
            query = f"{query} {target}".strip()
            compat_params_used["target"] = "query"
            if not class_name and re.match(r"^[A-Z][A-Za-z0-9_]*$", target.strip()):
                class_name = target.strip()
                compat_params_used["target_class_name"] = "class_name"
        if method_name:
            query = f"{query} {method_name}".strip()
            compat_params_used["method_name"] = "query"

        searcher = _get_searcher()
        if not searcher:
            return _json({
                "status": "unavailable",
                "query": query,
                "error": _game_code_import_error or "Game source code RAG is not available.",
                "module_status": get_game_code_module_status(),
                "next_action": "cd Server/data/game-rag-knowledge-base && python build_game_rag.py --stats  # Check status first; if empty, run: python build_game_rag.py",
            })

        results, search_mode = await _search_code_with_timeout(
            searcher=searcher,
            query=query,
            top_k=max(1, min(20, top_k)),
            game_name=game_name,
            class_name=class_name,
            code_type=code_type,
            include_assets=include_assets,
        )
        formatted = [_format_code_result(item) for item in results]
        return _json({
            "status": "success",
            "query": query,
            "total": len(formatted),
            "search_mode": search_mode,
            "filters_applied": {
                "game_name": game_name or None,
                "class_name": class_name or None,
                "code_type": code_type or None,
                "default_filter": None if include_assets else "code_only",
            },
            "compat_params_used": compat_params_used,
            "workflow_hint": (
                "Review these references first, then inspect the current Unity project "
                "scripts and adapt the smallest matching pattern."
            ),
            "search_hint": (
                "Try feature phrases such as enemy spawn, tower attack, wave manager, "
                "money UI, checkpoint movement, or add class_name/code_type filters "
                "if no results are returned."
            ),
            "results": formatted,
        })

    @mcp.tool(
        name="search_game_code_graph",
        description="""Search game source code with graph expansion for related classes and call chains.

Use when a feature spans multiple methods/classes, such as tower attacks,
enemy waves, UI state updates, save systems, or prefab-driven workflows.""",
        tags=make_group_tags("rag"),
    )
    async def search_game_code_graph(
        query: str,
        top_k: int = 5,
        game_name: str = "",
        class_name: str = "",
        traverse_depth: int = 1,
        include_assets: bool = False,
        target: str = "",
    ) -> str:
        compat_params_used: dict[str, Any] = {}
        if target:
            query = f"{query} {target}".strip()
            compat_params_used["target"] = "query"
            if not class_name and re.match(r"^[A-Z][A-Za-z0-9_]*$", target.strip()):
                class_name = target.strip()
                compat_params_used["target_class_name"] = "class_name"

        searcher = _get_searcher()
        if not searcher:
            return _json({
                "status": "unavailable",
                "query": query,
                "error": _game_code_import_error or "Game source code RAG is not available.",
                "module_status": get_game_code_module_status(),
                "next_action": "cd Server/data/game-rag-knowledge-base && python build_game_rag.py --stats  # Check status first; if empty, run: python build_game_rag.py",
            })

        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    searcher.search_graph,
                    query=query,
                    top_k=max(1, min(20, top_k)),
                    game_name=game_name or None,
                    class_name=class_name or None,
                    traverse_depth=max(1, min(3, traverse_depth)),
                    include_assets=include_assets,
                ),
                timeout=_SEMANTIC_SEARCH_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Graph game code search timed out after %ss for query=%r; using keyword fallback.",
                _SEMANTIC_SEARCH_TIMEOUT_SECONDS,
                query,
            )
            vector_results = []
            graph_results = []
            call_chain = []
            keyword_results = _keyword_search_code(query, top_k, game_name, class_name, include_assets=include_assets)
            return _json({
                "status": "success",
                "query": query,
                "filters_applied": {
                    "game_name": game_name or None,
                    "class_name": class_name or None,
                    "traverse_depth": traverse_depth,
                    "default_filter": None if include_assets else "code_only",
                },
                "compat_params_used": compat_params_used,
                "workflow_hint": (
                    "Search timed out on semantic/graph retrieval, so keyword fallback was used."
                ),
                "search_hint": (
                    "Narrow the query, add class_name, or retry with a more concrete feature phrase."
                ),
                "vector_results": [_format_code_result(item) for item in keyword_results],
                "graph_results": graph_results,
                "call_chain": call_chain,
                "search_mode": "keyword_timeout_fallback",
            })
        vector_results = [_format_code_result(item) for item in result.get("vector_results", [])]
        graph_results = [_format_graph_entity(item) for item in result.get("graph_results", [])]
        call_chain = [_format_graph_entity(item) for item in result.get("call_chain", [])]
        return _json({
            "status": "success",
            "query": query,
            "filters_applied": {
                "game_name": game_name or None,
                "class_name": class_name or None,
                "traverse_depth": traverse_depth,
                "default_filter": None if include_assets else "code_only",
            },
            "compat_params_used": compat_params_used,
            "workflow_hint": (
                "Use vector_results for the closest code snippets and call_chain/graph_results "
                "to understand dependencies before editing the current project."
            ),
            "search_hint": (
                "If vector_results is empty, retry with a concrete gameplay phrase or a known "
                "class name such as Tower, Enemy, GameManager, or UI."
            ),
            "search_mode": "semantic_graph",
            "vector_results": vector_results,
            "graph_results": graph_results,
            "call_chain": call_chain,
        })

    @mcp.tool(
        name="game_code_stats",
        description="Return build/status information for the game source code RAG knowledge base.",
        tags=make_group_tags("rag"),
    )
    def game_code_stats() -> str:
        return _json(get_game_code_module_status())

    @mcp.tool(
        name="select_game_target_script",
        description="""Infer the most likely Unity C# target script for a game development goal.

This is a fast, rule-based diagnostic tool. It scans Assets/**/*.cs, skips
Editor scripts, returns ranked candidates, and only auto-selects when the best
candidate is high confidence and clearly ahead.""",
        tags=make_group_tags("adaptation"),
    )
    async def select_game_target_script(
        goal: str,
        max_candidates: int = 5,
    ) -> dict[str, Any]:
        try:
            bridge = get_bridge()
            unity_info = await bridge.get_unity_info()
            project_root = Path(
                unity_info.get("project_path")
                or unity_info.get("projectRoot")
                or unity_info.get("root")
                or ""
            )
            if project_root.name == "Assets":
                project_root = project_root.parent
        except Exception as exc:
            return {
                "status": "unavailable",
                "error_code": "unity_unavailable",
                "goal": goal,
                "target_script_path": "",
                "confidence": "none",
                "candidates": [],
                "warnings": [f"Unity connection unavailable: {exc}"],
                "next_action": "Open the Unity project and reconnect the MCP bridge, then retry select_game_target_script.",
            }

        result = _select_target_script(
            project_root=project_root,
            goal=goal,
            max_candidates=max_candidates,
        )
        result.setdefault("goal", goal)
        result.setdefault("target_script_path", result.get("target_script_path", ""))
        result.setdefault("confidence", result.get("confidence", "none"))
        result.setdefault("warnings", [])
        result["project_root"] = str(project_root)
        result["next_action"] = (
            "Use target_script_path with start_game_dev_agent."
            if result.get("status") == "selected"
            else "Pick one candidate and rerun start_game_dev_agent with target_script_path set explicitly."
        )
        return result

    @mcp.tool(
        name="start_game_dev_agent",
        description="""Start a background game development agent task.

The agent selects a target script if needed, searches game source references,
runs an adaptation preview, and optionally applies it. Poll with get_task_status.""",
        tags=make_group_tags("adaptation"),
    )
    async def start_game_dev_agent(
        goal: str,
        target_script_path: str = "",
        apply: bool = False,
        context_depth: int = 3,
    ) -> dict[str, Any]:
        manager = get_adapt_task_manager()
        request = {
            "goal": goal,
            "target_script_path": target_script_path,
            "apply": apply,
            "context_depth": context_depth,
        }
        task = manager.start(
            request=request,
            task_type="game_dev_agent",
            runner_factory=lambda agent_task: _run_game_dev_agent_with_reference_scoring(
                goal=goal,
                target_script_path=target_script_path,
                apply=apply,
                context_depth=context_depth,
                task=agent_task,
            ),
        )
        return {
            "status": "queued",
            "task_id": task.task_id,
            "task_type": task.task_type,
            "phase": task.phase,
            "progress": task.progress,
            "goal": goal,
            "target_script_path": target_script_path,
            "next_action": "Poll get_task_status with this task_id until status=completed or failed.",
        }

    @mcp.tool(
        name="start_adapt_game_code",
        description="""Start a background preview adaptation task for one existing Unity C# script.

Use this when Ollama generation may exceed MCP request timeouts. Poll with
get_adapt_task_status, then call apply_adapt_task to write the completed preview.""",
        tags=make_group_tags("adaptation"),
    )
    async def start_adapt_game_code(
        goal: str,
        target_script_path: str,
        reference_results_json: str,
        context_depth: int = 3,
    ) -> dict[str, Any]:
        manager = get_adapt_task_manager()
        request = {
            "goal": goal,
            "target_script_path": target_script_path,
            "reference_results_json": reference_results_json,
            "context_depth": context_depth,
        }
        task = manager.start(
            request=request,
            runner_factory=lambda adapt_task: _run_adapt_preview(
                goal=goal,
                target_script_path=target_script_path,
                reference_results_json=reference_results_json,
                context_depth=context_depth,
                task=adapt_task,
            ),
        )
        return {
            "status": "queued",
            "task_id": task.task_id,
            "task_type": task.task_type,
            "phase": task.phase,
            "progress": task.progress,
            "goal": goal,
            "target_script_path": target_script_path,
            "next_action": "Poll get_adapt_task_status with this task_id until status=completed, then call apply_adapt_task if apply_ready is true.",
        }

    @mcp.tool(
        name="get_task_status",
        description="""Get status and result for any background task managed by the product server.""",
        tags=make_group_tags("adaptation"),
    )
    async def get_task_status(
        task_id: str,
        include_generated_code: bool = True,
    ) -> dict[str, Any]:
        manager = get_adapt_task_manager()
        task = manager.get(task_id)
        if not task:
            return {
                "status": "error",
                "error_code": "task_not_found",
                "task_id": task_id,
                "error": "Task was not found. It may have expired after cleanup or the server was restarted.",
            }
        return _build_task_status_payload(task, include_generated_code=include_generated_code)

    @mcp.tool(
        name="get_adapt_task_status",
        description="""Get the status or completed preview result for a background adapt_game_code task.""",
        tags=make_group_tags("adaptation"),
    )
    async def get_adapt_task_status(
        task_id: str,
        include_generated_code: bool = True,
    ) -> dict[str, Any]:
        manager = get_adapt_task_manager()
        task = manager.get(task_id)
        if not task:
            return {
                "status": "error",
                "error_code": "task_not_found",
                "task_id": task_id,
                "error": "Adapt task was not found. It may have expired after cleanup or the server was restarted.",
            }
        return _build_task_status_payload(
            task,
            include_generated_code=include_generated_code,
            include_adapt_compat=True,
        )

    @mcp.tool(
        name="apply_adapt_task",
        description="""Apply a completed adapt preview task by writing the script and running compile checks.""",
        tags=make_group_tags("adaptation"),
    )
    async def apply_adapt_task(task_id: str) -> dict[str, Any]:
        manager = get_adapt_task_manager()
        task = manager.get(task_id)
        if not task:
            return {
                "status": "error",
                "error_code": "task_not_found",
                "task_id": task_id,
                "error": "Adapt task was not found. It may have expired after cleanup or the server was restarted.",
            }
        if task.status == "cancelled":
            return {
                "status": "error",
                "error_code": "task_cancelled",
                "task_id": task_id,
                "error": "This adapt task was cancelled and cannot be applied.",
            }
        if task.status == "running":
            return {
                "status": "running",
                "task_id": task_id,
                "phase": task.phase,
                "progress": task.progress,
                "next_action": _apply_transport_hint(),
            }
        if task.status != "completed" or not isinstance(task.result, dict):
            return {
                "status": "error",
                "error_code": "task_not_ready",
                "task_id": task_id,
                "error": f"Task is not ready to apply. Current status={task.status}, phase={task.phase}.",
            }
        if task.result.get("status") in {"applied", "applied_with_compile_errors", "applied_pending_compile"}:
            return task.result
        if not task.result.get("apply_ready"):
            return {
                "status": "error",
                "error_code": "task_not_apply_ready",
                "task_id": task_id,
                "error": "Task completed without an apply-ready preview result.",
                "result": task.result,
            }
        preview_result = dict(task.result)
        task.update(status="running", phase="apply", progress=0.02)
        task.result = preview_result
        manager.run_existing(
            task,
            runner_factory=lambda current_task: _apply_adapt_preview_result(preview_result, task=current_task),
        )
        return {
            "status": "queued",
            "task_id": task_id,
            "phase": task.phase,
            "progress": task.progress,
            "goal": preview_result.get("goal"),
            "target_script_path": preview_result.get("target_script_path"),
            "next_action": _apply_transport_hint(),
        }

    @mcp.tool(
        name="cancel_task",
        description="""Cancel a queued or running background task managed by the product server.""",
        tags=make_group_tags("adaptation"),
    )
    async def cancel_task(task_id: str) -> dict[str, Any]:
        manager = get_adapt_task_manager()
        task = manager.cancel(task_id)
        if not task:
            return {
                "status": "error",
                "error_code": "task_not_found",
                "task_id": task_id,
                "error": "Task was not found.",
            }
        return {
            "status": task.status,
            "task_id": task.task_id,
            "task_type": task.task_type,
            "phase": task.phase,
            "progress": task.progress,
            "error": task.error,
        }

    @mcp.tool(
        name="cancel_adapt_task",
        description="""Cancel a queued or running adapt_game_code background task.""",
        tags=make_group_tags("adaptation"),
    )
    async def cancel_adapt_task(task_id: str) -> dict[str, Any]:
        result = await cancel_task(task_id)
        if result.get("error_code") == "task_not_found":
            result["error"] = "Adapt task was not found."
        return result

    @mcp.tool(
        name="adapt_game_code",
        description="""Adapt retrieved game source code into the current Unity project as a single C# script.

Use this after search_game_code or search_game_code_graph when you already know the
target script to update. Defaults to preview-only; set apply=true to write and compile.""",
        tags=make_group_tags("adaptation"),
    )
    async def adapt_game_code(
        goal: str,
        target_script_path: str,
        reference_results_json: str,
        apply: bool = False,
        context_depth: int = 3,
    ) -> dict[str, Any]:
        # preview-only: keep synchronous (non-blocking for typical Ollama latency)
        if not apply:
            preview_result = await _run_adapt_preview(
                goal=goal,
                target_script_path=target_script_path,
                reference_results_json=reference_results_json,
                context_depth=context_depth,
            )
            preview_result["warnings"] = list(preview_result.get("warnings", [])) + [_preview_transport_hint()]
            return preview_result

        # apply=true: delegate preview→apply chain to async task infra to avoid MCP stdio timeouts.
        # The entire generation+write+compile pipeline runs in a background asyncio task;
        # the caller polls get_adapt_task_status until completed/failed.
        manager = get_adapt_task_manager()
        request = {
            "goal": goal,
            "target_script_path": target_script_path,
            "reference_results_json": reference_results_json,
            "context_depth": context_depth,
            "apply": True,
        }

        async def _preview_then_apply(adapt_task: AdaptTask) -> dict[str, Any]:
            _ = adapt_task.update(status="running", phase="preview", progress=0.02)
            preview_result = await _run_adapt_preview(
                goal=goal,
                target_script_path=target_script_path,
                reference_results_json=reference_results_json,
                context_depth=context_depth,
                task=adapt_task,
            )
            preview_result["warnings"] = list(preview_result.get("warnings", [])) + [_preview_transport_hint()]
            if preview_result.get("status") in {"error", "unavailable"}:
                return preview_result
            _ = adapt_task.update(status="running", phase="apply", progress=0.05)
            return await _apply_adapt_preview_result(preview_result, task=adapt_task)

        task = manager.start(request=request, runner_factory=_preview_then_apply)
        return {
            "status": "queued",
            "task_id": task.task_id,
            "task_type": task.task_type,
            "phase": task.phase,
            "progress": task.progress,
            "goal": goal,
            "target_script_path": target_script_path,
            "next_action": (
                "Preview+apply is running in background. "
                "Poll get_adapt_task_status with this task_id until "
                "status=completed (success) or status=failed (error)."
            ),
        }

    # ── score_game_code: standalone scoring audit tool (Rule Engine, no LLM in scoring) ──
    @mcp.tool(
        name="score_game_code",
        description="""Evaluate how well a knowledge-base code snippet fits the current Unity project.

Uses a deterministic RE rule engine (NOT LLM) to:
1. Check code quality (null safety, comments, naming, performance patterns)
2. Check architecture fit (namespace match, dependency check, singleton compatibility)
3. Apply hard gating: any critical rule fail → code BLOCKED

Returns a ScoreCard with per-rule pass/fail results and gate decision. Agent notes are optional post-hoc observations (never affect the score).

Use when:
- Auditing a reference code snippet before adopting it
- Comparing multiple reference candidates for the same feature
- Verifying that a search result is truly suitable for the current project

Options:
- mode="sync": runs the rule engine immediately (<1ms for typical snippets)
- mode="async": queues a background task with optional Agent Observer notes""",
        tags=make_group_tags("scoring"),
    )
    async def score_game_code(
        code_text: str,
        target_script_path: str = "",
        project_root: str = "",
        mode: str = "sync",
        keyword_score: float = 0.0,
        run_agent_observer: bool = False,
    ) -> str:
        if mode == "async":
            try:
                mgr = get_adapt_task_manager()
                task = mgr.start(
                    request={
                        "code_text": code_text,
                        "target_script_path": target_script_path,
                        "project_root": project_root,
                        "keyword_score": keyword_score,
                        "run_agent_observer": run_agent_observer,
                    },
                    runner_factory=run_score_game_code_task,
                    task_type="score_game_code",
                )
                return _json({
                    "status": "queued",
                    "task_id": task.task_id,
                    "task_type": "score_game_code",
                    "mode": "async",
                    "next_action": "Call get_task_status(task_id=...) to retrieve the ScoreCard when scoring completes.",
                })
            except Exception as exc:
                return _json({"status": "error", "error": str(exc)})

        # ── sync mode: rule engine only (deterministic, <1ms) ──
        project_summary = _build_project_summary(target_script_path, project_root)
        try:
            rules = load_rules()
            engine = RulesEngine(rules, project_summary)
            results, gate = engine.evaluate_one(code_text)
            score, dims = engine.compute_score(results, gate)

            recommendation = "not_recommended" if gate.blocked else (
                "recommended" if score >= 7.0 else "recommended_with_caution"
            )
            card = ScoreCard(
                overall_score=score,
                blocked=gate.blocked,
                dimensions=[{"category": cat, "checks": items} for cat, items in dims.items()],
                recommendation=recommendation,
                summary=f"Gate: {'BLOCKED' if gate.blocked else 'PASS'} ({gate.pass_count}/{gate.total_count} rules)",
                keyword_score=keyword_score,
                combined_score=round(keyword_score * 0.3 + (score / 10.0) * 0.7, 4),
            )

            # Optionally run Agent Observer (off by default for sync mode)
            if run_agent_observer:
                try:
                    from services.code_scoring_service import AgentObserver
                    observer = AgentObserver()
                    review = await observer.review_references(
                        [{
                            "id": "single_reference",
                            "text": code_text,
                            "_scorecard": card,
                            "_gate": gate,
                        }],
                        project_summary=project_summary,
                        max_references=1,
                    )
                    card.agent_review = review
                    card.agent_notes = str(review.get("summary", ""))[:300]
                except Exception:
                    pass

            return _json({
                "status": "completed",
                "mode": "sync",
                "scorecard": _serialize_scorecard(card),
            })
        except Exception as exc:
            return _json({
                "status": "error",
                "mode": "sync",
                "error": f"Scoring failed: {exc}",
            })

    @mcp.tool(
        name="score_game_code_references",
        description="""Score and gate search_game_code/search_game_code_graph references for the current Unity project.

This is the batch reference-scoring entrypoint used by game_dev_agent. It parses
reference_results_json, scores every reference with the deterministic rule engine,
and returns recommended/rejected references plus an apply gate.""",
        tags=make_group_tags("scoring"),
    )
    async def score_game_code_references(
        goal: str,
        target_script_path: str,
        reference_results_json: str,
        context_depth: int = 3,
        run_agent_observer: bool = False,
    ) -> dict[str, Any]:
        warnings: list[str] = []
        try:
            references, ref_warnings = parse_reference_results(reference_results_json)
            warnings.extend(ref_warnings)
        except ValueError as exc:
            return {
                "status": "error",
                "error_code": "invalid_reference_json",
                "goal": goal,
                "target_script_path": target_script_path,
                "error": str(exc),
                "scored_references": [],
                "recommended_references": [],
                "rejected_references": [],
                "scoring_summary": {"total": 0, "recommended": 0, "rejected": 0},
                "apply_gate": {"blocked": True, "can_preview": False, "reasons": ["invalid_reference_json"]},
                "warnings": warnings + [str(exc)],
                "next_action": "Fix reference_results_json and retry scoring.",
            }

        try:
            bridge = get_bridge()
            unity_info = await bridge.get_unity_info()
            project_root, target_path = resolve_target_script(unity_info, target_script_path)
            collect_project_context(project_root, target_path, context_depth=context_depth)
        except Exception as exc:
            return {
                "status": "unavailable",
                "error_code": "unity_or_target_unavailable",
                "goal": goal,
                "target_script_path": target_script_path,
                "error": str(exc),
                "scored_references": [],
                "recommended_references": [],
                "rejected_references": [],
                "scoring_summary": {"total": 0, "recommended": 0, "rejected": 0},
                "apply_gate": {"blocked": True, "can_preview": False, "reasons": ["unity_or_target_unavailable"]},
                "warnings": warnings,
                "next_action": "Reconnect Unity or provide an existing Assets/.../*.cs target script.",
            }

        if not references:
            return {
                "status": "success",
                "goal": goal,
                "target_script_path": target_script_path,
                "scored_references": [],
                "recommended_references": [],
                "rejected_references": [],
                "scoring_summary": {"total": 0, "recommended": 0, "rejected": 0},
                "apply_gate": {"blocked": True, "can_preview": False, "reasons": ["no_references"]},
                "warnings": warnings,
                "next_action": "Run search_game_code/search_game_code_graph with a more concrete query.",
            }

        try:
            payload = await _score_reference_candidates(
                goal=goal,
                target_script_path=target_script_path,
                references=references,
                project_root=project_root,
                run_agent_observer=run_agent_observer,
            )
            payload["warnings"] = warnings + list(payload.get("warnings", []))
            return payload
        except Exception as exc:
            return {
                "status": "error",
                "error_code": "reference_scoring_failed",
                "goal": goal,
                "target_script_path": target_script_path,
                "error": str(exc),
                "scored_references": [],
                "recommended_references": [],
                "rejected_references": [],
                "scoring_summary": {"total": 0, "recommended": 0, "rejected": 0},
                "apply_gate": {"blocked": True, "can_preview": False, "reasons": ["reference_scoring_failed"]},
                "warnings": warnings + [str(exc)],
                "next_action": "Inspect scoring rules and retry after fixing the scoring error.",
            }

    @mcp.tool(
        name="distill_game_code_patterns",
        description="""Score, gate, and distill game-code references into portable implementation patterns.

Use this after search_game_code/search_game_code_graph when you want behavior
evidence and implementation constraints instead of direct code-copy references.""",
        tags=make_group_tags("scoring"),
    )
    async def distill_game_code_patterns(
        goal: str,
        target_script_path: str,
        reference_results_json: str,
        context_depth: int = 3,
        run_agent_review: bool = False,
    ) -> dict[str, Any]:
        warnings: list[str] = []
        try:
            references, ref_warnings = parse_reference_results(reference_results_json)
            warnings.extend(ref_warnings)
        except ValueError as exc:
            return {
                "status": "error",
                "error_code": "invalid_reference_json",
                "goal": goal,
                "target_script_path": target_script_path,
                "error": str(exc),
                "source_references": [],
                "distilled_patterns": [],
                "dependency_map": {},
                "target_mapping": {},
                "implementation_constraints": [],
                "rejected_references": [],
                "warnings": warnings + [str(exc)],
                "next_action": "Fix reference_results_json and retry pattern distillation.",
            }

        try:
            bridge = get_bridge()
            unity_info = await bridge.get_unity_info()
            project_root, _target_path = resolve_target_script(unity_info, target_script_path)
        except Exception as exc:
            return {
                "status": "unavailable",
                "error_code": "unity_or_target_unavailable",
                "goal": goal,
                "target_script_path": target_script_path,
                "error": str(exc),
                "source_references": [],
                "distilled_patterns": [],
                "dependency_map": {},
                "target_mapping": {},
                "implementation_constraints": [],
                "rejected_references": [],
                "warnings": warnings,
                "next_action": "Reconnect Unity or provide an existing Assets/.../*.cs target script.",
            }

        try:
            reference_scoring = await _score_reference_candidates(
                goal=goal,
                target_script_path=target_script_path,
                references=references,
                project_root=project_root,
                run_agent_observer=run_agent_review,
            )
            payload = _distill_reference_candidates(
                goal=goal,
                target_script_path=target_script_path,
                reference_scoring=reference_scoring,
                project_root=project_root,
                context_depth=context_depth,
            )
            payload["reference_scoring"] = reference_scoring
            payload["filtered_references"] = make_pattern_references(payload)
            payload["warnings"] = warnings + list(payload.get("warnings", []))
            return payload
        except Exception as exc:
            return {
                "status": "error",
                "error_code": "pattern_distillation_failed",
                "goal": goal,
                "target_script_path": target_script_path,
                "error": str(exc),
                "source_references": [],
                "distilled_patterns": [],
                "dependency_map": {},
                "target_mapping": {},
                "implementation_constraints": [],
                "rejected_references": [],
                "warnings": warnings + [str(exc)],
                "next_action": "Inspect reference scoring and target context, then retry pattern distillation.",
            }

    @mcp.tool(
        name="audit_game_code_knowledge_base",
        description="""Offline-style hygiene labels for game-code knowledge-base search results.

This tool does not modify the knowledge base. It classifies provided reference
results as golden_reference, usable_with_constraints, high_risk, or
deprecated_pattern.""",
        tags=make_group_tags("scoring"),
    )
    async def audit_game_code_knowledge_base(
        reference_results_json: str,
        max_items: int = 200,
    ) -> dict[str, Any]:
        try:
            references, warnings = parse_reference_results(reference_results_json)
        except ValueError as exc:
            return {
                "status": "error",
                "error_code": "invalid_reference_json",
                "error": str(exc),
                "labels": {
                    "golden_reference": [],
                    "usable_with_constraints": [],
                    "high_risk": [],
                    "deprecated_pattern": [],
                },
                "summary": {},
                "warnings": [str(exc)],
                "next_action": "Fix reference_results_json and retry knowledge-base audit.",
            }
        payload = audit_knowledge_base_references(references, max_items=max_items)
        payload["warnings"] = warnings
        return payload

    logger.info(
        "Game code tools registered: search_game_code, search_game_code_graph, game_code_stats, adapt_game_code, select_game_target_script, start_game_dev_agent, start_adapt_game_code, score_game_code, score_game_code_references, distill_game_code_patterns, audit_game_code_knowledge_base, get_task_status, cancel_task, get_adapt_task_status, apply_adapt_task, cancel_adapt_task"
    )

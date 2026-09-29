"""Distill scored game-code references into portable adaptation patterns.

The distillation layer treats knowledge-base code as evidence, not source to
copy. It extracts intent, state, methods, dependencies, and constraints that
the adapter can safely map onto the current Unity project.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any


_UNITY_LIFECYCLE = {
    "Awake",
    "Start",
    "Update",
    "FixedUpdate",
    "LateUpdate",
    "OnEnable",
    "OnDisable",
    "OnDestroy",
}

_UNITY_TYPES = {
    "AudioClip",
    "Button",
    "Camera",
    "Canvas",
    "Collider",
    "Collider2D",
    "GameObject",
    "Image",
    "NavMeshAgent",
    "Rigidbody",
    "Rigidbody2D",
    "Sprite",
    "Text",
    "TMP_Text",
    "Transform",
}

_BUILTIN_TYPES = {
    "Action",
    "Boolean",
    "Coroutine",
    "Debug",
    "Dictionary",
    "Enumerable",
    "IEnumerator",
    "List",
    "Mathf",
    "MonoBehaviour",
    "Object",
    "Quaternion",
    "Random",
    "SerializeField",
    "String",
    "Time",
    "Vector2",
    "Vector3",
    "Vector4",
    "WaitForSeconds",
}


def distill_reference_patterns(
    *,
    goal: str,
    target_script_path: str,
    reference_scoring: dict[str, Any],
    target_content: str = "",
    sample_scripts: list[dict[str, str]] | None = None,
    max_patterns: int = 3,
) -> dict[str, Any]:
    """Build a pattern-distillation payload from a scoring result."""
    sample_scripts = sample_scripts or []
    source_references = list(reference_scoring.get("scored_references") or [])
    recommended = list(reference_scoring.get("recommended_references") or [])[:max_patterns]
    rejected = list(reference_scoring.get("rejected_references") or [])

    warnings: list[str] = []
    distilled_patterns: list[dict[str, Any]] = []
    implementation_constraints: list[str] = [
        "Treat knowledge-base code as evidence only; do not copy source project class names, scene object names, or unrelated systems.",
        "Preserve the target script class name, namespace style, serialized fields, and public API unless the goal explicitly requires a change.",
        "Map every required field and method to the current target script or create the smallest local equivalent inside the target file.",
    ]

    target_symbols = _extract_target_symbols(target_content, sample_scripts)
    dependency_map: dict[str, Any] = {
        "external_types": [],
        "unity_types": [],
        "manager_or_singleton_dependencies": [],
        "missing_target_symbols": [],
    }
    target_mapping: dict[str, Any] = {
        "target_script": target_script_path,
        "available_fields": sorted(target_symbols["fields"])[:30],
        "available_methods": sorted(target_symbols["methods"])[:30],
        "available_types": sorted(target_symbols["types"])[:30],
        "suggested_mappings": [],
    }

    for index, reference in enumerate(recommended, start=1):
        pattern = _distill_one_reference(
            goal=goal,
            reference=reference,
            target_symbols=target_symbols,
            index=index,
        )
        distilled_patterns.append(pattern)
        implementation_constraints.extend(pattern["implementation_constraints"])
        target_mapping["suggested_mappings"].extend(pattern["suggested_mappings"])

        for dep in pattern["dependencies"]:
            if dep["kind"] == "unity_type":
                _append_unique(dependency_map["unity_types"], dep)
            elif dep["kind"] == "manager_or_singleton":
                _append_unique(dependency_map["manager_or_singleton_dependencies"], dep)
            elif dep["kind"] == "missing_target_symbol":
                _append_unique(dependency_map["missing_target_symbols"], dep)
            else:
                _append_unique(dependency_map["external_types"], dep)

    for rejected_ref in rejected[:5]:
        blockers = rejected_ref.get("hard_blockers") or []
        if blockers:
            warnings.append(
                f"Rejected {rejected_ref.get('class_name') or rejected_ref.get('id')}: "
                + "; ".join(str(item) for item in blockers[:3])
            )

    implementation_constraints = _dedupe_strings(implementation_constraints)
    target_mapping["suggested_mappings"] = _dedupe_dicts(target_mapping["suggested_mappings"])

    confidence_values = [float(item.get("confidence") or 0.0) for item in distilled_patterns]
    average_confidence = round(sum(confidence_values) / len(confidence_values), 3) if confidence_values else 0.0
    unresolved_count = sum(len(item.get("unresolved_risks") or []) for item in distilled_patterns)
    apply_gate = {
        "blocked": not distilled_patterns or average_confidence < 0.45 or unresolved_count >= 4,
        "can_preview": bool(distilled_patterns),
        "reasons": [],
    }
    if not distilled_patterns:
        apply_gate["reasons"].append("no_distilled_patterns")
    if distilled_patterns and average_confidence < 0.45:
        apply_gate["reasons"].append("low_pattern_confidence")
    if unresolved_count >= 4:
        apply_gate["reasons"].append("too_many_unresolved_pattern_risks")

    return {
        "status": "success" if distilled_patterns else "blocked",
        "goal": goal,
        "target_script_path": target_script_path,
        "source_references": source_references,
        "distilled_patterns": distilled_patterns,
        "dependency_map": dependency_map,
        "target_mapping": target_mapping,
        "implementation_constraints": implementation_constraints,
        "rejected_references": rejected,
        "preparation_summary": {
            "source_count": len(source_references),
            "pattern_count": len(distilled_patterns),
            "rejected_count": len(rejected),
            "average_confidence": average_confidence,
            "unresolved_risk_count": unresolved_count,
        },
        "apply_gate": apply_gate,
        "warnings": warnings,
        "next_action": (
            "Use distilled_patterns and implementation_constraints for adaptation."
            if distilled_patterns
            else "Search for better references or refine the goal before adapting."
        ),
    }


def make_pattern_references(pattern_payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert distilled patterns into adapter-compatible reference objects."""
    references: list[dict[str, Any]] = []
    for pattern in pattern_payload.get("distilled_patterns", [])[:3]:
        references.append({
            "id": pattern.get("id", ""),
            "class_name": pattern.get("source_class_name", ""),
            "method_name": pattern.get("source_method_name", ""),
            "code_type": "distilled_pattern",
            "score": pattern.get("confidence", 0.0),
            "summary": pattern.get("intent", ""),
            "reuse_hint": "Use this distilled pattern as implementation guidance, not as source code to copy.",
            "text": _pattern_text(pattern, pattern_payload),
            "distilled_pattern": pattern,
            "implementation_constraints": pattern_payload.get("implementation_constraints", []),
            "target_mapping": pattern_payload.get("target_mapping", {}),
            "dependency_map": pattern_payload.get("dependency_map", {}),
        })
    return references


def audit_knowledge_base_references(
    references: list[dict[str, Any]],
    *,
    max_items: int = 200,
) -> dict[str, Any]:
    """Offline-style deterministic hygiene labels for indexed game-code snippets."""
    labels: dict[str, list[dict[str, Any]]] = {
        "golden_reference": [],
        "usable_with_constraints": [],
        "high_risk": [],
        "deprecated_pattern": [],
    }

    for reference in references[:max_items]:
        text = str(reference.get("text") or "")
        tag, reasons = _classify_reference(text)
        entry = {
            "id": reference.get("id", ""),
            "file_path": reference.get("file_path", ""),
            "class_name": reference.get("class_name", ""),
            "method_name": reference.get("method_name", ""),
            "code_type": reference.get("code_type", ""),
            "score": reference.get("score"),
            "label": tag,
            "reasons": reasons,
        }
        labels[tag].append(entry)

    return {
        "status": "success",
        "labels": labels,
        "summary": {key: len(value) for key, value in labels.items()},
        "next_action": "Prefer golden_reference and usable_with_constraints results in adaptation flows.",
    }


def _distill_one_reference(
    *,
    goal: str,
    reference: dict[str, Any],
    target_symbols: dict[str, set[str]],
    index: int,
) -> dict[str, Any]:
    text = str(reference.get("text") or "")
    class_name = str(reference.get("class_name") or "")
    method_name = str(reference.get("method_name") or "")
    source_name = ".".join(part for part in (class_name, method_name) if part) or str(reference.get("id") or f"reference_{index}")

    fields = _extract_fields(text)
    methods = _extract_methods(text)
    lifecycle = [name for name in methods if name in _UNITY_LIFECYCLE]
    dependencies = _extract_dependencies(text, target_symbols)
    core_steps = _extract_core_steps(text, goal)
    required_state = _infer_required_state(fields, text)
    required_methods = _infer_required_methods(methods, method_name)
    constraints, do_not_copy, unresolved = _constraints_for_reference(reference, text, dependencies)
    suggested_mappings = _suggest_mappings(fields, methods, target_symbols)

    confidence = _pattern_confidence(reference, core_steps, unresolved, suggested_mappings)
    pattern_name = _pattern_name(goal, source_name, index)

    return {
        "id": str(reference.get("id") or f"pattern_{index}"),
        "pattern_name": pattern_name,
        "intent": _infer_intent(goal, source_name, text),
        "core_steps": core_steps,
        "required_state": required_state,
        "required_methods": required_methods,
        "unity_lifecycle_requirements": lifecycle or _infer_lifecycle_from_goal(goal, text),
        "do_not_copy": do_not_copy,
        "adaptation_notes": [
            "Implement the behavior inside the target script using local fields and methods.",
            "Prefer existing target members over source-project member names.",
        ],
        "confidence": confidence,
        "source_class_name": class_name,
        "source_method_name": method_name,
        "implementation_constraints": constraints,
        "unresolved_risks": unresolved,
        "dependencies": dependencies,
        "suggested_mappings": suggested_mappings,
    }


def _extract_target_symbols(target_content: str, sample_scripts: list[dict[str, str]]) -> dict[str, set[str]]:
    combined = "\n".join([target_content] + [str(item.get("content") or "") for item in sample_scripts])
    return {
        "fields": set(_extract_fields(combined)),
        "methods": set(_extract_methods(combined)),
        "types": set(re.findall(r"\b(?:class|struct|interface|enum)\s+([A-Za-z_]\w*)", combined)),
    }


def _extract_fields(code: str) -> list[str]:
    pattern = re.compile(
        r"(?:\[SerializeField\]\s*)?(?:public|private|protected|internal)?\s*"
        r"(?:static\s+|readonly\s+|const\s+)*[A-Za-z_][\w<>\[\],\s]*\s+([A-Za-z_]\w*)\s*(?:=|;)",
        re.MULTILINE,
    )
    return _dedupe_strings([m.group(1) for m in pattern.finditer(code or "") if not _looks_like_keyword(m.group(1))])


def _extract_methods(code: str) -> list[str]:
    pattern = re.compile(
        r"(?:public|private|protected|internal)?\s*(?:static\s+|virtual\s+|override\s+|async\s+)*"
        r"[A-Za-z_][\w<>\[\],\s]*\s+([A-Za-z_]\w*)\s*\(",
        re.MULTILINE,
    )
    return _dedupe_strings([m.group(1) for m in pattern.finditer(code or "") if not _looks_like_keyword(m.group(1))])


def _extract_dependencies(code: str, target_symbols: dict[str, set[str]]) -> list[dict[str, Any]]:
    type_names = set(re.findall(r"\b[A-Z][A-Za-z0-9_]{2,}\b", code or ""))
    dependencies: list[dict[str, Any]] = []
    for name in sorted(type_names):
        if name in _BUILTIN_TYPES:
            continue
        if name in _UNITY_TYPES:
            dependencies.append({"name": name, "kind": "unity_type", "target_has_symbol": True})
        elif name.endswith("Manager") or name.endswith("Singleton") or name in {"Instance", "GameManager"}:
            dependencies.append({
                "name": name,
                "kind": "manager_or_singleton",
                "target_has_symbol": name in target_symbols["types"],
            })
        elif name not in target_symbols["types"]:
            dependencies.append({"name": name, "kind": "missing_target_symbol", "target_has_symbol": False})
    return dependencies[:20]


def _extract_core_steps(code: str, goal: str) -> list[str]:
    code_lower = code.lower()
    steps: list[str] = []
    if any(term in code_lower for term in ("input.", "onclick", "button")):
        steps.append("Read player/UI input and route it to a local behavior method.")
    if any(term in code_lower for term in ("instantiate", "spawn")):
        steps.append("Create or spawn the required runtime object using target-project prefabs or serialized references.")
    if any(term in code_lower for term in ("damage", "takedamage", "health", "hp")):
        steps.append("Calculate damage or health changes and update local state before triggering death/feedback behavior.")
    if any(term in code_lower for term in ("move", "movetowards", "translate", "velocity", "navmeshagent")):
        steps.append("Move the object through the target project's existing transform, physics, or navigation style.")
    if any(term in code_lower for term in ("timer", "countdown", "deltaTime".lower(), "waitforseconds")):
        steps.append("Track elapsed time and trigger behavior only after the required timer condition is reached.")
    if any(term in code_lower for term in ("audioclip", "playsound", "playoneshot", "audio")):
        steps.append("Play feedback through existing audio references or a verified local AudioSource.")
    if not steps:
        steps.append(f"Implement the requested behavior for: {goal[:140]}")
    return steps[:6]


def _infer_required_state(fields: list[str], code: str) -> list[str]:
    required: list[str] = []
    field_text = " ".join(fields).lower()
    if any(term in field_text or term in code.lower() for term in ("damage", "attack", "atk")):
        required.append("damage or attack value")
    if any(term in field_text or term in code.lower() for term in ("health", "hp", "life")):
        required.append("health/life state")
    if any(term in field_text or term in code.lower() for term in ("speed", "velocity")):
        required.append("movement speed")
    if any(term in field_text or term in code.lower() for term in ("timer", "countdown", "delay")):
        required.append("timer/delay state")
    if any(term in code.lower() for term in ("prefab", "instantiate", "spawn")):
        required.append("prefab or spawn target reference")
    if not required and fields:
        required.extend(fields[:4])
    return _dedupe_strings(required)[:8]


def _infer_required_methods(methods: list[str], method_name: str) -> list[str]:
    selected = [name for name in methods if name not in _UNITY_LIFECYCLE]
    if method_name and method_name not in selected:
        selected.insert(0, method_name)
    return _dedupe_strings(selected)[:8]


def _constraints_for_reference(
    reference: dict[str, Any],
    text: str,
    dependencies: list[dict[str, Any]],
) -> tuple[list[str], list[str], list[str]]:
    constraints: list[str] = []
    do_not_copy: list[str] = []
    unresolved: list[str] = []
    text_lower = text.lower()

    if "getcomponent" in text_lower and not re.search(r"if\s*\([^)]*(?:!=\s*null|is\s+not\s+null|null\s*!=)", text, re.IGNORECASE):
        constraints.append("If a component lookup is needed, use TryGetComponent/GetComponent with a null guard or a serialized reference.")
        do_not_copy.append("Do not copy unchecked GetComponent usage.")

    if re.search(r"GameObject\.Find|FindObjectOfType|FindObjectsOfType", text):
        constraints.append("Avoid global scene searches in the target implementation; prefer serialized references, cached fields, or explicit injection.")
        do_not_copy.append("Do not copy global FindObjectOfType/GameObject.Find lookup patterns.")

    if re.search(r"Destroy\s*\(\s*FindObjectOfType", text):
        unresolved.append("Reference contains dangerous singleton destruction logic.")
        do_not_copy.append("Do not copy Destroy(FindObjectOfType<T>()) or similar singleton cleanup.")

    if ".Instance" in text or "Singleton<" in text:
        constraints.append("Do not assume the source singleton exists in the target project; map global access to current local references.")

    if any(dep["kind"] == "missing_target_symbol" for dep in dependencies):
        constraints.append("Replace source-only types and members with target-project equivalents or keep the change single-file.")
        unresolved.append("Some referenced source-project types are not present in the sampled target context.")

    hard_blockers = reference.get("hard_blockers") or []
    for blocker in hard_blockers[:3]:
        unresolved.append(str(blocker))

    return _dedupe_strings(constraints), _dedupe_strings(do_not_copy), _dedupe_strings(unresolved)


def _suggest_mappings(fields: list[str], methods: list[str], target_symbols: dict[str, set[str]]) -> list[dict[str, str]]:
    mappings: list[dict[str, str]] = []
    for source in fields[:10]:
        target = _closest_symbol(source, target_symbols["fields"])
        if target:
            mappings.append({"source": source, "target": target, "kind": "field"})
    for source in methods[:10]:
        target = _closest_symbol(source, target_symbols["methods"])
        if target:
            mappings.append({"source": source, "target": target, "kind": "method"})
    return mappings[:12]


def _closest_symbol(source: str, candidates: set[str]) -> str:
    source_terms = set(_split_terms(source))
    if not source_terms:
        return ""
    best = ("", 0.0)
    for candidate in candidates:
        candidate_terms = set(_split_terms(candidate))
        if not candidate_terms:
            continue
        overlap = len(source_terms & candidate_terms) / max(1, len(source_terms | candidate_terms))
        if overlap > best[1]:
            best = (candidate, overlap)
    return best[0] if best[1] >= 0.34 else ""


def _split_terms(name: str) -> list[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name or "")
    return [part.lower().strip("_") for part in re.split(r"[_\W\s]+", spaced) if len(part.strip("_")) >= 3]


def _pattern_confidence(
    reference: dict[str, Any],
    core_steps: list[str],
    unresolved: list[str],
    suggested_mappings: list[dict[str, str]],
) -> float:
    score = float(reference.get("compatibility_score") or 50) / 100.0
    if reference.get("recommended_use") == "use":
        score += 0.12
    if core_steps:
        score += 0.08
    if suggested_mappings:
        score += 0.05
    score -= min(0.35, len(unresolved) * 0.1)
    if reference.get("risk_level") == "medium":
        score -= 0.08
    if reference.get("risk_level") == "high":
        score -= 0.25
    return round(max(0.0, min(0.98, score)), 3)


def _pattern_name(goal: str, source_name: str, index: int) -> str:
    goal_terms = _split_terms(goal)[:3]
    prefix = "_".join(goal_terms) if goal_terms else "gameplay"
    source = re.sub(r"[^A-Za-z0-9_]+", "_", source_name).strip("_") or f"reference_{index}"
    return f"{prefix}_pattern_from_{source}"[:96]


def _infer_intent(goal: str, source_name: str, text: str) -> str:
    if source_name:
        return f"Use {source_name} as evidence for implementing: {goal}"
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return f"Use reference behavior as evidence for: {goal}. Source starts with: {first_line[:80]}"


def _infer_lifecycle_from_goal(goal: str, text: str) -> list[str]:
    lowered = (goal + "\n" + text).lower()
    lifecycle: list[str] = []
    if any(term in lowered for term in ("move", "timer", "countdown", "input")):
        lifecycle.append("Update")
    if any(term in lowered for term in ("initialize", "setup", "cache", "audio")):
        lifecycle.append("Awake or Start")
    return lifecycle


def _classify_reference(text: str) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if not text.strip():
        return "deprecated_pattern", ["empty_reference_text"]
    if re.search(r"Destroy\s*\(\s*FindObjectOfType", text):
        return "high_risk", ["dangerous_singleton_destroy"]
    if re.search(r"\bFindObjectOfType|GameObject\.Find", text):
        reasons.append("global_scene_lookup")
    if "GetComponent" in text and not re.search(r"if\s*\([^)]*(?:!=\s*null|is\s+not\s+null|null\s*!=)", text, re.IGNORECASE):
        reasons.append("unchecked_component_lookup")
    if len(text) > 6000:
        reasons.append("large_cross_system_snippet")
    if len(reasons) >= 2:
        return "usable_with_constraints", reasons
    if reasons:
        return "usable_with_constraints", reasons
    return "golden_reference", ["no_obvious_static_risks"]


def _pattern_text(pattern: dict[str, Any], payload: dict[str, Any]) -> str:
    return (
        "DISTILLED_REFERENCE_PATTERN\n"
        f"Pattern: {pattern.get('pattern_name')}\n"
        f"Intent: {pattern.get('intent')}\n"
        f"Core steps: {pattern.get('core_steps')}\n"
        f"Required state: {pattern.get('required_state')}\n"
        f"Required methods: {pattern.get('required_methods')}\n"
        f"Unity lifecycle: {pattern.get('unity_lifecycle_requirements')}\n"
        f"Do not copy: {pattern.get('do_not_copy')}\n"
        f"Constraints: {payload.get('implementation_constraints')}\n"
        f"Target mapping: {payload.get('target_mapping')}\n"
    )


def _append_unique(items: list[dict[str, Any]], item: dict[str, Any]) -> None:
    key = (item.get("name"), item.get("kind"))
    if not any((existing.get("name"), existing.get("kind")) == key for existing in items):
        items.append(item)


def _dedupe_strings(items: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        text = str(item).strip()
        if text and text not in seen:
            seen.add(text)
            output.append(text)
    return output


def _dedupe_dicts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    output: list[dict[str, Any]] = []
    for item in items:
        key = tuple(sorted((str(k), str(v)) for k, v in item.items()))
        if key not in seen:
            seen.add(key)
            output.append(item)
    return output


def _looks_like_keyword(name: str) -> bool:
    return name in {"if", "for", "foreach", "while", "switch", "return", "new", "using", "class"}

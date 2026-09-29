"""Adapt retrieved game source code to the currently open Unity project."""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any

import httpx


DEFAULT_CODE_ADAPT_MODEL = "qwen2.5-coder:7b"
DEFAULT_CODE_ADAPT_FALLBACK_MODEL = os.getenv("UNITY_MCP_CODE_ADAPT_FALLBACK_MODEL", "")
DEFAULT_OLLAMA_HOST = "http://localhost:11434"
MAX_EXTRA_TYPE_SOURCES = 16
MAX_EXTRA_TYPE_SOURCE_CHARS = 5000
COMMON_CSHARP_SYMBOLS = {
    "Action",
    "Add",
    "Added",
    "Awake",
    "Button",
    "Camera",
    "Color",
    "Debug",
    "Destroy",
    "False",
    "FixedUpdate",
    "GameObject",
    "GetComponent",
    "Implemented",
    "Instantiate",
    "List",
    "Mathf",
    "MonoBehaviour",
    "SerializeField",
    "Start",
    "String",
    "Text",
    "Time",
    "Transform",
    "True",
    "Updated",
    "Used",
    "Uses",
    "Update",
    "Vector2",
    "Vector3",
}
UNITY_BUILTIN_RECEIVERS = {
    "Application",
    "Camera",
    "Canvas",
    "Color",
    "Debug",
    "EventSystem",
    "GameObject",
    "Input",
    "LayerMask",
    "Mathf",
    "Physics",
    "Physics2D",
    "PlayerPrefs",
    "Quaternion",
    "Random",
    "SceneManager",
    "Screen",
    "String",
    "Time",
    "Vector2",
    "Vector3",
    "Vector4",
    "gameObject",
    "this",
    "transform",
}
UNITY_INHERITED_INSTANCE_MEMBERS = {
    "BroadcastMessage",
    "CancelInvoke",
    "CompareTag",
    "Destroy",
    "DestroyImmediate",
    "GetComponent",
    "GetComponentInChildren",
    "GetComponentInParent",
    "GetComponents",
    "GetComponentsInChildren",
    "GetComponentsInParent",
    "Invoke",
    "InvokeRepeating",
    "SendMessage",
    "StartCoroutine",
    "StopAllCoroutines",
    "StopCoroutine",
    "TryGetComponent",
    "enabled",
    "gameObject",
    "hideFlags",
    "isActiveAndEnabled",
    "name",
    "tag",
    "transform",
    "useGUILayout",
}
CSHARP_KEYWORDS = {
    "as",
    "base",
    "bool",
    "break",
    "case",
    "catch",
    "class",
    "const",
    "continue",
    "decimal",
    "default",
    "delegate",
    "do",
    "double",
    "else",
    "enum",
    "event",
    "false",
    "finally",
    "float",
    "for",
    "foreach",
    "if",
    "in",
    "int",
    "interface",
    "internal",
    "is",
    "lock",
    "long",
    "namespace",
    "new",
    "null",
    "object",
    "out",
    "override",
    "private",
    "protected",
    "public",
    "readonly",
    "ref",
    "return",
    "sealed",
    "short",
    "static",
    "string",
    "struct",
    "switch",
    "this",
    "throw",
    "true",
    "try",
    "typeof",
    "uint",
    "ulong",
    "using",
    "var",
    "virtual",
    "void",
    "while",
}
CSHARP_MEMBER_MODIFIERS = {
    "abstract",
    "async",
    "const",
    "event",
    "extern",
    "internal",
    "new",
    "override",
    "partial",
    "private",
    "protected",
    "public",
    "readonly",
    "sealed",
    "static",
    "unsafe",
    "virtual",
    "volatile",
}


def parse_reference_results(reference_results_json: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Extract top code references from search_game_code/search_game_code_graph output."""
    warnings: list[str] = []
    try:
        payload = json.loads(reference_results_json)
    except Exception as exc:
        raise ValueError(f"reference_results_json is not valid JSON: {exc}") from exc

    if isinstance(payload, list):
        candidates = payload
    elif isinstance(payload, dict):
        candidates = []
        for key in ("results", "vector_results", "matched_references"):
            value = payload.get(key)
            if isinstance(value, list):
                candidates.extend(value)
    else:
        candidates = []

    normalized: list[dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, dict) or item.get("error"):
            continue
        text = item.get("text") or item.get("content") or item.get("source") or ""
        metadata = item.get("metadata") or {}
        score = item.get("score")
        normalized.append({
            "id": item.get("id", ""),
            "game_name": item.get("game_name") or metadata.get("game_name", ""),
            "file_path": item.get("file_path") or metadata.get("file_path", ""),
            "class_name": item.get("class_name") or metadata.get("class_name", ""),
            "method_name": item.get("method_name") or metadata.get("method_name", ""),
            "code_type": item.get("code_type") or metadata.get("code_type", ""),
            "line_start": item.get("line_start") or metadata.get("line_start"),
            "line_end": item.get("line_end") or metadata.get("line_end"),
            "score": score if score is not None else 0,
            "summary": item.get("summary", ""),
            "reuse_hint": item.get("reuse_hint", ""),
            "text": text,
        })

    normalized.sort(key=lambda x: float(x.get("score") or 0), reverse=True)
    top = normalized[:3]
    if not top:
        warnings.append("No usable reference snippets found in reference_results_json.")
    return top, warnings


def resolve_target_script(project_info: dict[str, Any], target_script_path: str) -> tuple[Path, Path]:
    """Resolve an Assets-relative script path inside the current Unity project."""
    if not target_script_path or not target_script_path.replace("\\", "/").startswith("Assets/"):
        raise ValueError("target_script_path must be an existing Assets/.../*.cs path.")
    if not target_script_path.endswith(".cs"):
        raise ValueError("target_script_path must point to a .cs script.")

    project_root = (
        project_info.get("project_path")
        or project_info.get("projectRoot")
        or project_info.get("root")
        or ""
    )
    if not project_root and project_info.get("assets_path"):
        project_root = str(Path(project_info["assets_path"]).parent)
    if not project_root:
        raise ValueError("Unity project root is unavailable. Is Unity connected?")

    root = Path(project_root)
    if root.name == "Assets":
        root = root.parent
    root = root.resolve()
    target = (root / target_script_path.replace("/", os.sep)).resolve()
    if not str(target).lower().startswith(str(root).lower()):
        raise ValueError("target_script_path resolved outside the Unity project.")
    if not target.exists():
        raise FileNotFoundError(f"Target script does not exist: {target_script_path}")
    return root, target


def read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def collect_project_context(project_root: Path, target_path: Path, context_depth: int = 3) -> dict[str, Any]:
    """Collect target script and small neighbor samples for style inference."""
    assets_dir = project_root / "Assets"
    scripts_dir = assets_dir / "Scripts"
    target_text = read_text(target_path)

    candidates: list[Path] = []
    candidates.extend(sorted(target_path.parent.glob("*.cs")))
    if scripts_dir.exists():
        candidates.extend(sorted(scripts_dir.glob("*.cs")))
        candidates.extend(sorted(scripts_dir.glob("*/*.cs")))

    seen: set[Path] = set()
    samples: list[dict[str, str]] = []
    for path in candidates:
        resolved = path.resolve()
        if resolved == target_path or resolved in seen or not resolved.exists():
            continue
        seen.add(resolved)
        rel = resolved.relative_to(project_root).as_posix()
        samples.append({"path": rel, "content": read_text(resolved)[:5000]})
        if len(samples) >= max(1, min(8, context_depth)):
            break

    return {
        "project_root": str(project_root),
        "target_relative_path": target_path.relative_to(project_root).as_posix(),
        "target_content": target_text,
        "sample_scripts": samples,
        "style_summary": infer_project_style(target_text, samples),
    }


def infer_project_style(target_text: str, samples: list[dict[str, str]]) -> dict[str, Any]:
    combined = "\n".join([target_text] + [s["content"] for s in samples])
    namespaces = sorted(set(re.findall(r"^\s*namespace\s+([\w.]+)", combined, re.MULTILINE)))
    usings = re.findall(r"^\s*using\s+([^;]+);", combined, re.MULTILINE)
    class_matches = re.findall(r"\b(?:public|internal|private|protected)?\s*class\s+(\w+)(?:\s*:\s*([^{\n]+))?", combined)
    private_fields = re.findall(r"\bprivate\s+[\w<>\[\],\s]+\s+(\w+)\s*[;=]", combined)
    underscore_private = [name for name in private_fields if name.startswith("_")]

    return {
        "uses_namespace": bool(namespaces),
        "namespaces": namespaces[:5],
        "common_usings": [name for name, _ in Counter(usings).most_common(10)],
        "class_count_sampled": len(class_matches),
        "base_types": sorted(set(base.strip() for _, base in class_matches if base.strip()))[:10],
        "uses_singleton_pattern": "Singleton<" in combined or "public static" in combined and "Instance" in combined,
        "serialized_field_count": combined.count("[SerializeField]"),
        "private_field_style": "underscore" if len(underscore_private) > len(private_fields) / 2 else "plain",
        "brace_style": "mixed_or_existing",
        "note": "Preserve the target file's existing public API, serialized fields, and namespace style.",
    }


def build_adaptation_prompt(
    goal: str,
    project_info: dict[str, Any],
    editor_state: dict[str, Any],
    context: dict[str, Any],
    references: list[dict[str, Any]],
) -> str:
    reference_text = json.dumps(references, ensure_ascii=False, indent=2)[:18000]
    samples = [
        {"path": s["path"], "content_preview": s["content"][:2200]}
        for s in context.get("sample_scripts", [])
    ]
    target_content = context["target_content"][:18000]
    payload = {
        "goal": goal,
        "unity_project": project_info,
        "editor_state": editor_state,
        "target_script_path": context["target_relative_path"],
        "project_style_summary": context["style_summary"],
        "target_script_current_content": target_content,
        "neighbor_script_samples": samples,
        "reference_game_code": reference_text,
        "graphrag_context": context.get("graphrag_context", {}),
    }
    has_distilled_patterns = any(isinstance(ref, dict) and ref.get("distilled_pattern") for ref in references)
    pattern_rules = (
        "- The references include distilled_reference_pattern objects. Treat them as implementation evidence and constraints, not source code. Do not copy rejected or source-project code directly.\n"
        "- Follow implementation_constraints, do_not_copy, target_mapping, and dependency_map when translating the pattern into the target script.\n"
        if has_distilled_patterns else ""
    )
    return (
        "You are adapting Unity C# gameplay code into the user's current Unity project.\n"
        "Return ONLY valid JSON with this schema:\n"
        "{\n"
        '  "generated_code": "complete replacement C# file",\n'
        '  "adaptation_notes": ["short note"],\n'
        '  "planned_edits": ["short edit"],\n'
        '  "warnings": ["short warning"]\n'
        "}\n\n"
        "Rules:\n"
        "- generated_code must be the complete replacement contents for the target C# file.\n"
        "- Always include the standard Unity C# using directives at the top: using System; using System.Collections; using System.Collections.Generic; using UnityEngine; even if the target file is currently missing some.\n"
        "- Preserve every existing `using` directive from the target file. Only remove a using if you are certain its referenced type is no longer used anywhere in the new code.\n"
        "- Preserve the target file's class name, public API, SerializedField fields, Unity lifecycle hooks, and namespace style unless the goal requires a minimal change.\n"
        "- Use reference code only as behavior inspiration; do not copy source project names, paths, scene object names, or unrelated systems.\n"
        f"{pattern_rules}"
        "- Use graphrag_context as read-only guidance about Unity APIs and project code patterns; do not invent members that are not present in the target project context.\n"
        "- Do not invent multi-file changes. If the goal needs more files, keep this file valid and list follow-up work in warnings.\n"
        "- Prefer compiling Unity C# for Unity 2022.3.\n\n"
        f"INPUT:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def should_repair_adaptation() -> bool:
    return os.getenv("UNITY_MCP_CODE_ADAPT_REPAIR", "1").strip().lower() not in {"0", "false", "no", "off"}


def _strip_comments(code: str) -> str:
    code = re.sub(r"//.*?$", "", code or "", flags=re.MULTILINE)
    code = re.sub(r"/\*[\s\S]*?\*/", "", code, flags=re.MULTILINE)
    return code


def _parse_type_name(type_text: str) -> str | None:
    if not type_text:
        return None
    cleaned = re.sub(r"<.*?>", "", type_text).strip()
    if not cleaned:
        return None
    token = re.split(r"[\s\[\],]+", cleaned)[0]
    token = token.split(".")[-1]
    if not token or token.lower() in CSHARP_KEYWORDS:
        return None
    return token


def _index_type_members(code: str) -> dict[str, dict[str, set[str]]]:
    stripped = _strip_comments(code)
    indexed: dict[str, dict[str, set[str]]] = {}
    type_ranges: list[tuple[str, int, int]] = []

    type_pattern = re.compile(r"\b(class|struct|interface|enum)\s+([A-Za-z_]\w*)")
    for match in type_pattern.finditer(stripped):
        kind = match.group(1)
        type_name = match.group(2)
        if kind == "enum":
            indexed.setdefault(type_name, {"fields": set(), "properties": set(), "methods": set(), "kind": {"enum"}})
            continue
        brace_start = stripped.find("{", match.end())
        if brace_start == -1:
            continue
        depth = 0
        brace_end = -1
        for idx in range(brace_start, len(stripped)):
            ch = stripped[idx]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    brace_end = idx
                    break
        if brace_end == -1:
            continue
        indexed.setdefault(type_name, {"fields": set(), "properties": set(), "methods": set(), "kind": {kind}})
        type_ranges.append((type_name, brace_start + 1, brace_end))

    field_pattern = re.compile(
        r"^\s*(?:\[[^\]]+\]\s*)*(?:(?:" + "|".join(sorted(CSHARP_MEMBER_MODIFIERS)) + r")\s+)*"
        r"([A-Za-z_][\w<>\[\],.? ]*)\s+([A-Za-z_]\w*)\s*(?:=[^;]*)?;",
        re.MULTILINE,
    )
    property_pattern = re.compile(
        r"^\s*(?:\[[^\]]+\]\s*)*(?:(?:" + "|".join(sorted(CSHARP_MEMBER_MODIFIERS)) + r")\s+)*"
        r"([A-Za-z_][\w<>\[\],.? \t]*)\s+([A-Za-z_]\w*)\s*\{",
        re.MULTILINE,
    )
    method_pattern = re.compile(
        r"^\s*(?:\[[^\]]+\]\s*)*(?:(?:" + "|".join(sorted(CSHARP_MEMBER_MODIFIERS)) + r")\s+)*"
        r"(?:[A-Za-z_][\w<>\[\],.? ]*\s+)?([A-Za-z_]\w*)\s*\(([^)]*)\)\s*\{",
        re.MULTILINE,
    )

    for type_name, start, end in type_ranges:
        body = stripped[start:end]
        info = indexed[type_name]
        for match in field_pattern.finditer(body):
            field_name = match.group(2)
            if field_name not in {"if", "for", "while", "switch", "return"}:
                info["fields"].add(field_name)
        for match in property_pattern.finditer(body):
            info["properties"].add(match.group(2))
        for match in method_pattern.finditer(body):
            method_name = match.group(1)
            if method_name not in {"if", "for", "while", "switch", "catch", "foreach"}:
                info["methods"].add(method_name)

    return indexed


def _collect_extra_type_sources(context: dict[str, Any], generated_code: str) -> list[dict[str, str]]:
    project_root = context.get("project_root")
    if not project_root:
        return []
    root_path = Path(project_root)
    assets_dir = root_path / "Assets"
    if not assets_dir.exists():
        return []

    known_paths = {sample.get("path", "") for sample in context.get("sample_scripts", [])}
    target_relative_path = context.get("target_relative_path", "")
    known_paths.add(target_relative_path)
    target_is_editor = target_relative_path.replace("\\", "/").lower().startswith("assets/editor/")
    generated_symbols = extract_pascal_symbols(generated_code)
    extra_samples: list[dict[str, str]] = []
    seen_paths: set[str] = set()

    for symbol in generated_symbols[:80]:
        if symbol in COMMON_CSHARP_SYMBOLS or symbol in UNITY_BUILTIN_RECEIVERS:
            continue
        for path in assets_dir.rglob(f"{symbol}.cs"):
            rel = path.relative_to(root_path).as_posix()
            rel_lower = rel.lower()
            if not target_is_editor and rel_lower.startswith("assets/editor/"):
                continue
            if rel in known_paths or rel in seen_paths:
                continue
            seen_paths.add(rel)
            extra_samples.append({"path": rel, "content": read_text(path)[:MAX_EXTRA_TYPE_SOURCE_CHARS]})
            break
        if len(extra_samples) >= MAX_EXTRA_TYPE_SOURCES:
            break
    return extra_samples


def _build_project_api_index(context: dict[str, Any], generated_code: str) -> dict[str, dict[str, set[str]]]:
    combined_sources = [{"path": context.get("target_relative_path", ""), "content": context.get("target_content", "")}]
    combined_sources.extend(context.get("sample_scripts", []))
    combined_sources.extend(_collect_extra_type_sources(context, generated_code))

    api_index: dict[str, dict[str, set[str]]] = {}
    for sample in combined_sources:
        for type_name, members in _index_type_members(sample.get("content", "")).items():
            if type_name not in api_index:
                api_index[type_name] = {
                    "fields": set(),
                    "properties": set(),
                    "methods": set(),
                    "kind": set(),
                }
            for key in ("fields", "properties", "methods", "kind"):
                api_index[type_name][key].update(members.get(key, set()))
    return api_index


def _extract_current_class_name(code: str) -> str | None:
    match = re.search(r"\bclass\s+([A-Za-z_]\w*)", code or "")
    return match.group(1) if match else None


def _extract_parameter_types(code: str) -> dict[str, str]:
    parameter_types: dict[str, str] = {}
    stripped = _strip_comments(code)
    method_signature_pattern = re.compile(
        r"^\s*(?:\[[^\]]+\]\s*)*(?:(?:" + "|".join(sorted(CSHARP_MEMBER_MODIFIERS)) + r")\s+)*"
        r"(?:[A-Za-z_][\w<>\[\],.? ]*\s+)?[A-Za-z_]\w*\s*\(([^)]*)\)",
        re.MULTILINE,
    )
    for match in method_signature_pattern.finditer(stripped):
        parameter_blob = match.group(1)
        for raw_param in parameter_blob.split(","):
            param = raw_param.strip()
            if not param:
                continue
            param = re.sub(r"^\b(?:ref|out|in|params|this)\b\s+", "", param)
            pieces = [part for part in re.split(r"\s+", param) if part]
            if len(pieces) < 2:
                continue
            name = re.sub(r"[^A-Za-z0-9_]", "", pieces[-1])
            type_name = _parse_type_name(" ".join(pieces[:-1]))
            if name and type_name:
                parameter_types[name] = type_name
    return parameter_types


def _extract_field_types(code: str) -> dict[str, str]:
    field_types: dict[str, str] = {}
    stripped = _strip_comments(code)
    field_pattern = re.compile(
        r"^\s*(?:\[[^\]]+\]\s*)*(?:(?:" + "|".join(sorted(CSHARP_MEMBER_MODIFIERS)) + r")\s+)*"
        r"([A-Za-z_][\w<>\[\],.? ]*)\s+([A-Za-z_]\w*)\s*(?:=[^;]*)?;",
        re.MULTILINE,
    )
    for match in field_pattern.finditer(stripped):
        type_name = _parse_type_name(match.group(1))
        field_name = match.group(2)
        if type_name and field_name:
            field_types[field_name] = type_name
    return field_types


def _extract_local_variable_types(code: str) -> dict[str, str]:
    variable_types: dict[str, str] = {}
    stripped = _strip_comments(code)

    explicit_pattern = re.compile(
        r"\b([A-Z][A-Za-z0-9_<>\[\],.?]*)\s+([a-zA-Z_]\w*)\s*=\s*[^;]+;",
        re.MULTILINE,
    )
    for match in explicit_pattern.finditer(stripped):
        type_name = _parse_type_name(match.group(1))
        variable_name = match.group(2)
        if type_name and variable_name:
            variable_types[variable_name] = type_name

    declaration_pattern = re.compile(
        r"\b([A-Z][A-Za-z0-9_<>\[\],.?]*)\s+([a-zA-Z_]\w*)\s*(?:;|=)",
        re.MULTILINE,
    )
    for match in declaration_pattern.finditer(stripped):
        type_name = _parse_type_name(match.group(1))
        variable_name = match.group(2)
        if type_name and variable_name:
            variable_types.setdefault(variable_name, type_name)

    as_pattern = re.compile(
        r"\b(?:var|[A-Z][A-Za-z0-9_<>\[\],.?]*)\s+([a-zA-Z_]\w*)\s*=\s*[^;]*\bas\s+([A-Z][A-Za-z0-9_<>\[\],.?]*)",
        re.MULTILINE,
    )
    for match in as_pattern.finditer(stripped):
        variable_name = match.group(1)
        type_name = _parse_type_name(match.group(2))
        if type_name:
            variable_types[variable_name] = type_name

    return variable_types


def _extract_member_accesses(code: str) -> list[tuple[str, str]]:
    stripped = _strip_comments(code)
    matches = re.findall(r"\b([A-Za-z_]\w*)\s*\.\s*([A-Za-z_]\w*)\b", stripped)
    return [(receiver, member) for receiver, member in matches if receiver and member]


def _audit_cross_file_member_access(context: dict[str, Any], generated_code: str) -> tuple[list[str], list[str]]:
    api_index = _build_project_api_index(context, generated_code)
    if not api_index:
        return [], []

    variable_types: dict[str, str] = {}
    variable_types.update(_extract_field_types(generated_code))
    variable_types.update(_extract_parameter_types(generated_code))
    variable_types.update(_extract_local_variable_types(generated_code))

    current_class_name = _extract_current_class_name(generated_code)
    if current_class_name:
        variable_types.setdefault("this", current_class_name)

    issues: list[str] = []
    warnings: list[str] = []
    seen_issues: set[str] = set()
    seen_warnings: set[str] = set()

    for receiver, member in _extract_member_accesses(generated_code):
        if receiver in UNITY_BUILTIN_RECEIVERS or receiver.lower() in CSHARP_KEYWORDS:
            continue
        if receiver == "Instance" or member in UNITY_INHERITED_INSTANCE_MEMBERS:
            continue
        if member in {"Instance"}:
            continue

        receiver_type = variable_types.get(receiver)
        if not receiver_type and receiver in api_index:
            receiver_type = receiver
        if not receiver_type:
            continue
        if receiver_type in UNITY_BUILTIN_RECEIVERS:
            continue

        members = api_index.get(receiver_type)
        if not members:
            continue
        if "enum" in members.get("kind", set()):
            continue

        available_members = members.get("fields", set()) | members.get("properties", set()) | members.get("methods", set())
        if member not in available_members:
            issue = f"Generated code references {receiver}.{member}, but sampled project type {receiver_type} does not define member {member}."
            if issue not in seen_issues:
                seen_issues.add(issue)
                issues.append(issue)

    return issues, warnings


def _audit_goal_features(goal: str, generated_code: str) -> list[str]:
    """Lightweight goal-driven feature audit.

    Checks for high-value, low-ambiguity goal signals that are "obviously missing"
    from the generated code. Only flags clear gaps, not subtle semantic issues.

    Category 1: Delay + Destroy (延迟销毁)
    Category 2: Countdown/Timer (倒计时)
    Category 3: MoveSpeed in movement (移动速度)
    Category 4: Attack/Damage/Hit implementation
    """
    goal_lower = goal.lower()
    code_lower = generated_code.lower()
    issues: list[str] = []

    # ── Category 1: Delay + Destroy ──
    has_delay = any(kw in goal_lower for kw in ("delay", "延迟", "等待"))
    has_destroy = any(kw in goal_lower for kw in ("destroy", "销毁", "删除", "移除"))

    if has_destroy:
        # Does the generated code have a delayed destroy?
        has_destroy_call = bool(re.search(r"\bDestroy\s*\(.+?\)", generated_code))
        has_destroy_with_delay = bool(re.search(
            r"\bDestroy\s*\([^,)]+\s*,\s*(?:[0-9.]+[fF]?\s*|\w+\s*[*+/]\s*\w+\s*|\w+\s*)", generated_code
        ))
        has_coroutine_destroy = bool(re.search(
            r"(?:StartCoroutine|yield\s+return\s+(?:new\s+)?WaitForSeconds?|IEnumerator).*?Destroy",
            generated_code, re.DOTALL
        ))

        if not has_destroy_call:
            if has_delay:
                issues.append(
                    "[goal_feature_audit] Goal requires delay-then-destroy, "
                    "but generated_code has no Destroy() call at all."
                )
        elif not has_destroy_with_delay and not has_coroutine_destroy:
            if has_delay:
                issues.append(
                    "[goal_feature_audit] Goal requires delay-then-destroy, "
                    "but generated_code calls Destroy() without a delay parameter "
                    "and without a coroutine/IEnumerator pattern. "
                    "Use Destroy(gameObject, delaySeconds) or StartCoroutine with WaitForSeconds."
                )

    # ── Category 2: Countdown / Timer ──
    has_countdown = any(kw in goal_lower for kw in (
        "countdown", "倒计时", "timer", "计时", "倒计", "波次"
    ))
    if has_countdown:
        has_timer_field = bool(re.search(r"\b(?:float|int)\s+\w*(?:timer|countdown|cd|clock)", code_lower))
        has_timer_decrement = bool(re.search(
            r"(?:\w*(?:timer|countdown|cd|clock)\w*)\s*(?:-=\s*Time\.deltaTime|\-\-|--\s*\w*(?:timer|countdown))",
            code_lower
        ))
        has_timer_trigger = bool(re.search(
            r"if\s*\(.*(?:timer|countdown|cd|clock).*(?:<=|>=|==|<|>)\s*0",
            code_lower
        ))
        has_timer_display = bool(re.search(
            r"(?:Text|TMP_Text|UGUI|SetText|\.text\s*=|\bToString\b).*?(?:timer|countdown|cd|clock)",
            code_lower
        ))

        if has_timer_field and not has_timer_decrement and not has_timer_trigger:
            issues.append(
                "[goal_feature_audit] Goal requires countdown/timer, "
                "a timer field is defined but it is never decremented (e.g. -= Time.deltaTime) "
                "and never triggers any action when reaching zero."
            )

    # ── Category 3: MoveSpeed in movement ──
    has_movespeed = any(kw in goal_lower for kw in (
        "movespeed", "move_speed", "移动速度", "speed"
    ))
    if has_movespeed:
        has_speed_field = bool(re.search(r"\b(?:float|int)\s+\w*(?:speed|movespeed|velocity)", generated_code, re.IGNORECASE))
        speed_used_in_movement = bool(re.search(
            r"((?:speed|movespeed|velocity)\w*)\s*\*\s*Time\.deltaTime",
            generated_code,
            re.IGNORECASE,
        )) or bool(re.search(
            r"(?:MoveTowards|Translate|\.velocity\s*=|Move\s*\()[^)]*?(?:speed|movespeed|velocity)",
            generated_code,
            re.IGNORECASE,
        )) or bool(re.search(
            r"(?:speed|movespeed|velocity)\w*\s*\*\s*(?:Vector3|Vector2)",
            generated_code,
            re.IGNORECASE,
        )) or bool(re.search(
            r"(?:Vector3|Vector2)[.\w()]*\s*\*\s*(?:speed|movespeed|velocity)\w*",
            generated_code,
            re.IGNORECASE,
        ))

        if has_speed_field and not speed_used_in_movement:
            issues.append(
                "[goal_feature_audit] Goal requires move speed, "
                "a speed field is defined but it is not used in any movement formula "
                "(no MoveTowards/Translate/velocity assignment involving the speed variable). "
                "Ensure the speed variable participates in actual position change."
            )

    # ── Category 4: Attack / Damage / Hit ──
    has_attack = any(kw in goal_lower for kw in (
        "attack", "damage", "hit", "攻击", "伤害", "碰撞"
    ))
    if has_attack:
        has_attack_impl = bool(re.search(
            r"\b(?:attack|damage|hit|take_damage|takedamage|deal_damage|dealdamage)\b", code_lower
        ))
        has_damage_field = bool(re.search(r"\b(?:float|int)\s+\w*(?:damage|attack|atk)", code_lower))
        has_hp_field = bool(re.search(r"\b(?:float|int)\s+\w*(?:health|hp|life)", code_lower))
        has_damage_calc = bool(re.search(
            r"(?:health|hp|life)\w*\s*-=\s*(?:damage|attack|atk)", code_lower
        )) or bool(re.search(
            r"\.(?:health|hp|life)\s*-=\s*", code_lower
        ))

        if not has_attack_impl and not (has_damage_field and has_hp_field):
            issues.append(
                "[goal_feature_audit] Goal requires attack/damage/hit behavior, "
                "but generated_code has no attack, damage, hit, TakeDamage, or DealDamage "
                "method/identifier, and no damage+health field pair for a damage system."
            )

    return issues


def audit_generated_adaptation(
    goal: str,
    generated_code: str,
    references: list[dict[str, Any]],
    adaptation_notes: list[str],
    planned_edits: list[str],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Find obvious gaps where generated notes/reference behavior are not present in code."""
    code_lower = generated_code.lower()
    goal_lower = goal.lower()
    notes_text = "\n".join(adaptation_notes + planned_edits)
    notes_lower = notes_text.lower()
    reference_text = "\n".join(str(ref.get("text", "")) for ref in references)
    reference_lower = reference_text.lower()
    issues: list[str] = []
    warnings: list[str] = []

    # ── Goal-driven feature audit (new) ──
    goal_feature_issues = _audit_goal_features(goal, generated_code)
    issues.extend(goal_feature_issues)

    claimed_symbols = [
        symbol
        for symbol in extract_pascal_symbols(notes_text)
        if symbol not in COMMON_CSHARP_SYMBOLS and symbol not in generated_code
    ][:8]
    for symbol in claimed_symbols:
        issues.append(f"Notes/planned edits mention {symbol}, but generated_code does not contain that symbol.")

    if "damage" in notes_lower and not any(term in code_lower for term in ("damage", "health", "hp", "takehit", "takedamage")):
        issues.append("Adaptation notes claim damage handling, but generated_code has no obvious damage/health/take-damage implementation.")

    if "projectiletype" in reference_lower and "ProjectileType" not in generated_code:
        if any(term in goal_lower or term in notes_lower for term in ("attack", "damage", "projectile", "tower")):
            issues.append(
                "Matched reference uses ProjectileType for attack/damage behavior, but generated_code does not reference ProjectileType."
            )
        else:
            warnings.append("Matched reference uses ProjectileType, but generated_code does not; verify this is intentional.")

    if "attack" in goal_lower and "attack" not in code_lower:
        issues.append("Goal mentions attack behavior, but generated_code has no Attack-named method or attack identifier.")

    goal_terms = set(re.findall(r"[a-zA-Z]{4,}", goal_lower))
    reference_symbols = extract_pascal_symbols(reference_text)
    missing_goal_related_symbols = []
    for symbol in reference_symbols:
        symbol_lower = symbol.lower()
        if symbol in COMMON_CSHARP_SYMBOLS or symbol in generated_code:
            continue
        if any(term in symbol_lower for term in goal_terms):
            missing_goal_related_symbols.append(symbol)
    if missing_goal_related_symbols:
        warnings.append(
            "Goal-related reference symbols not present in generated_code: "
            + ", ".join(sorted(set(missing_goal_related_symbols))[:8])
        )

    cross_file_issues: list[str] = []
    cross_file_warnings: list[str] = []
    if context:
        cross_file_issues, cross_file_warnings = _audit_cross_file_member_access(context, generated_code)
        issues.extend(cross_file_issues)
        warnings.extend(cross_file_warnings[:8])

    return {
        "status": "needs_repair" if issues else "passed",
        "issues": issues,
        "warnings": warnings,
        "needs_repair": bool(issues),
        "goal_feature_audit": {
            "status": "failed" if goal_feature_issues else "passed",
            "issues": goal_feature_issues,
            "checked_categories": ["delay_destroy", "countdown_timer", "move_speed", "attack_damage"],
        },
        "cross_file_api": {
            "status": "failed" if cross_file_issues else "passed",
            "issues": cross_file_issues,
            "warnings": cross_file_warnings[:8],
        },
    }


def build_repair_prompt(
    original_prompt: str,
    generated_code: str,
    quality_audit: dict[str, Any],
) -> str:
    return (
        original_prompt
        + "\n\nThe previous generated_code failed a deterministic quality audit.\n"
        + "Repair the generated_code now. Return ONLY the same JSON schema as before.\n"
        + "Do not claim behavior in adaptation_notes unless the code concretely implements it.\n"
        + "If the reference behavior is intentionally not used, explain that in warnings and keep the script compiling.\n"
        + f"\nQUALITY_AUDIT:\n{json.dumps(quality_audit, ensure_ascii=False, indent=2)}\n"
        + f"\nPREVIOUS_GENERATED_CODE:\n```csharp\n{generated_code}\n```\n"
    )


def extract_pascal_symbols(text: str) -> list[str]:
    symbols = re.findall(r"\b[A-Z][A-Za-z0-9_]{2,}\b", text or "")
    seen: set[str] = set()
    ordered: list[str] = []
    for symbol in symbols:
        if symbol not in seen:
            seen.add(symbol)
            ordered.append(symbol)
    return ordered[:80]


async def _call_ollama_inner(host: str, model: str, prompt: str, timeout: float) -> str:
    """Raw Ollama API call, returns response text. Raises RuntimeError on connection failure."""
    body = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.15,
            "num_ctx": 16384,
        },
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(f"{host}/api/generate", json=body)
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        raise RuntimeError(f"Ollama unavailable at {host} with model {model}: {exc}") from exc

    return payload.get("response", "")


async def call_ollama_for_adaptation(prompt: str, allow_fallback: bool = True) -> dict[str, Any]:
    """Call Ollama for adaptation code generation with optional fallback model.

    If UNITY_MCP_CODE_ADAPT_FALLBACK_MODEL is set and the primary model
    fails to produce parseable JSON, the fallback model is tried once.

    Raises:
        RuntimeError: Ollama server is unreachable
        AdaptationParseError: Response cannot be parsed (even after fallback if enabled)
    """
    host = os.getenv("OLLAMA_HOST", DEFAULT_OLLAMA_HOST).rstrip("/")
    if host and not host.lower().startswith(("http://", "https://")):
        host = f"http://{host}"
    timeout = float(os.getenv("UNITY_MCP_CODE_ADAPT_TIMEOUT", "180"))
    primary_model = os.getenv("UNITY_MCP_CODE_ADAPT_MODEL", DEFAULT_CODE_ADAPT_MODEL)
    fallback_model = os.getenv("UNITY_MCP_CODE_ADAPT_FALLBACK_MODEL", DEFAULT_CODE_ADAPT_FALLBACK_MODEL)

    # ── Primary model attempt ──
    text = await _call_ollama_inner(host, primary_model, prompt, timeout)
    try:
        parsed = parse_adaptation_response(text)
    except AdaptationParseError:
        # Only try fallback if configured, allowed, and different from primary
        if not allow_fallback:
            raise
        if not fallback_model or fallback_model.strip() == primary_model:
            raise
        # ── Fallback model attempt ──
        fb_text = await _call_ollama_inner(host, fallback_model.strip(), prompt, timeout)
        parsed = parse_adaptation_response(fb_text)
        parsed["_ollama"] = {
            "host": host,
            "model": fallback_model.strip(),
            "primary_model": primary_model,
            "fallback_used": True,
        }
        return parsed

    parsed["_ollama"] = {"host": host, "model": primary_model}
    return parsed


class AdaptationParseError(ValueError):
    """Raised when Ollama response cannot be parsed into valid adaptation JSON.

    error_code is one of:
    - json_parse_failed: text could not be decoded as JSON at all
    - generated_code_incomplete: JSON parsed but generated_code is missing,
      empty, or does not contain a C# class
    """

    def __init__(self, message: str, error_code: str = "generation_failed"):
        super().__init__(message)
        self.error_code = error_code


def _try_json_repair(text: str) -> str | None:
    """Apply lightweight JSON repairs for common Ollama formatting errors.

    Returns repaired text or None if repair is not possible.
    Only handles well-understood, low-risk fixes:
    - Trailing commas before } or ]
    - Leading/trailing explanatory text around a {...} or ```json``` block
    """
    # 1. Extract fenced block ```json ... ```
    fenced = re.search(r"```(?:json)?\s*\n?([\s\S]*?)\n?\s*```", text)
    if fenced:
        candidate = fenced.group(1).strip()
        if candidate.startswith("{"):
            return candidate

    # 2. Extract first { ... } block (greedy, from first { to last })
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        candidate = match.group(0)
        # Remove trailing commas before } or ]
        repaired = re.sub(r",(\s*[}\]])", r"\1", candidate)
        return repaired

    return None


def parse_adaptation_response(text: str) -> dict[str, Any]:
    """Parse Ollama adaptation response into structured dict.

    Raises AdaptationParseError with specific error_code on failure:
    - json_parse_failed: text is not valid JSON even after repair
    - generated_code_incomplete: JSON parsed but generated_code missing/empty/no C# class
    """
    stripped = text.strip()
    json_str: str | None = None
    last_error: str = ""

    # Attempt 1: direct JSON parse
    # Strip markdown fence first
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        data = json.loads(stripped)
        if isinstance(data, dict):
            json_str = json.dumps(data)  # not strictly needed, but confirms validity
    except json.JSONDecodeError as exc:
        last_error = str(exc)

    # Attempt 2: regex extract + repair
    if json_str is None:
        repaired = _try_json_repair(stripped)
        if repaired:
            try:
                data = json.loads(repaired)
                if isinstance(data, dict):
                    json_str = json.dumps(data)
            except json.JSONDecodeError as exc:
                last_error = f"{last_error}; repair attempt: {exc}"

    # Attempt 3: raw regex extract without repair (existing fallback)
    if json_str is None:
        match = re.search(r"\{[\s\S]*\}", stripped)
        if match:
            try:
                data = json.loads(match.group(0))
                if isinstance(data, dict):
                    json_str = json.dumps(data)
            except json.JSONDecodeError as exc:
                last_error = f"{last_error}; extract attempt: {exc}"

    if json_str is None or not isinstance(data, dict):
        raise AdaptationParseError(
            f"[json_parse_failed] Could not parse Ollama response as JSON. "
            f"Last error: {last_error}. Raw response (first 300 chars): {text[:300]}",
            error_code="generation_json_parse_failed",
        )

    generated_code = data.get("generated_code", "")
    if not generated_code:
        raise AdaptationParseError(
            "[generated_code_incomplete] Ollama response parsed as JSON but generated_code field is empty or missing.",
            error_code="generated_code_incomplete",
        )
    if "class " not in generated_code:
        raise AdaptationParseError(
            "[generated_code_incomplete] Ollama response has generated_code but no C# class definition found.",
            error_code="generated_code_incomplete",
        )

    return {
        "generated_code": strip_csharp_fence(generated_code),
        "adaptation_notes": normalize_string_list(data.get("adaptation_notes")),
        "planned_edits": normalize_string_list(data.get("planned_edits")),
        "warnings": normalize_string_list(data.get("warnings")),
    }


def strip_csharp_fence(code: str) -> str:
    stripped = code.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:csharp|cs|c#)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip() + "\n"


def normalize_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


UNITY_STANDARD_USINGS = [
    "using System;",
    "using System.Collections;",
    "using System.Collections.Generic;",
    "using UnityEngine;",
]


def extract_usings(code: str) -> list[str]:
    """Extract all `using ...;` directives from C# code, preserving order."""
    if not code:
        return []
    result: list[str] = []
    for line in code.splitlines():
        stripped = line.strip()
        if stripped.startswith("using ") and ";" in stripped:
            result.append(stripped)
    return result


def ensure_usings(generated_code: str, original_code: str = "") -> str:
    """Ensure the generated code contains all necessary using directives.

    Two sources of truth:
    1. All using directives from the original file are preserved (even if Ollama dropped them).
    2. Standard Unity usings (System/Collections/Generic/UnityEngine) are always included.

    Missing directives are injected after the last existing using statement.
    """
    if not generated_code or not generated_code.strip():
        return generated_code

    generated_usings = set(extract_usings(generated_code))
    original_usings = extract_usings(original_code)

    needed: list[str] = []
    for using in UNITY_STANDARD_USINGS + original_usings:
        if using not in needed:
            needed.append(using)

    missing = [using for using in needed if using not in generated_usings]
    if not missing:
        return generated_code

    lines = generated_code.splitlines(keepends=True)
    if not lines:
        return generated_code

    # Insert after the last existing using line
    last_using_line = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("using ") and ";" in stripped:
            last_using_line = i

    insert_pos = last_using_line + 1
    insert_text = "\n".join(missing) + "\n"
    if insert_pos < len(lines) and lines[insert_pos].strip():
        insert_text += "\n"

    return "".join(lines[:insert_pos]) + insert_text + "".join(lines[insert_pos:])

"""Structured scoring for knowledge base code references — v2.0.

Double-layer architecture:
  L1: RulesEngine — deterministic regex engine, authoritative score + gate
  L2: AgentObserver — optional post-hoc LLM notes, never affects score/gate
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────

_RUBRIC_YAML_PATH = Path(__file__).resolve().parent.parent / "config" / "scoring_rubric.yaml"
DEFAULT_SCORING_MODEL = "gemma4:26b"
DEFAULT_OLLAMA_HOST = "http://localhost:11434"
_MAX_CACHE_ENTRIES = 200
_SCORE_CACHE: dict[str, dict[str, Any]] = {}

# ── Data Classes ───────────────────────────────────────────

@dataclass
class ScoringRule:
    """One rule loaded from YAML."""
    id: str
    severity: str          # "critical" | "warning" | "info"
    category: str          # "code_quality" | "architecture_fit"
    description: str
    patterns: list[str] = field(default_factory=list)
    logic: str = "match_any"   # match_any | count_gt | match_none | match_count | no_null_guard | comment_ratio_lt | no_namespace | missing_null_guard_in_coroutine | namespace_mismatch | dependency_check
    threshold: int = 0
    score_penalty: float = 0.0


@dataclass
class RuleResult:
    """Result of evaluating one rule against one code snippet."""
    rule_id: str
    severity: str
    category: str
    pass_: bool
    matched_lines: list[str] = field(default_factory=list)
    detail: str = ""


@dataclass
class GateResult:
    """Gating decision for one code snippet."""
    blocked: bool
    critical_fails: list[RuleResult] = field(default_factory=list)
    warning_fails: list[RuleResult] = field(default_factory=list)
    info_items: list[RuleResult] = field(default_factory=list)
    pass_count: int = 0
    total_count: int = 0


@dataclass
class ScoreCard:
    """Final score + gate for one code reference."""
    overall_score: float = 10.0       # 10 = perfect
    blocked: bool = False
    dimensions: list[dict[str, Any]] = field(default_factory=list)
    recommendation: str = "not_evaluated"
    summary: str = ""
    agent_notes: str = ""
    agent_review: dict[str, Any] | None = None
    keyword_score: float = 0.0
    combined_score: float = 0.0       # keyword * 0.3 + rule_score/10 * 0.7


# ── YAML Loading ───────────────────────────────────────────

def load_rules(path: Path | None = None) -> list[ScoringRule]:
    """Load scoring rules from YAML config."""
    if yaml is None:
        raise RuntimeError("PyYAML is required. Install: pip install pyyaml")

    file_path = path or _RUBRIC_YAML_PATH
    if not file_path.exists():
        raise FileNotFoundError(f"Scoring rubric not found: {file_path}")

    with open(file_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    rules: list[ScoringRule] = []
    for r in raw.get("rules", []):
        rules.append(ScoringRule(
            id=r.get("id", ""),
            severity=r.get("severity", "info"),
            category=r.get("category", "code_quality"),
            description=r.get("description", ""),
            patterns=r.get("patterns", []),
            logic=r.get("logic", "match_any"),
            threshold=r.get("threshold", 0),
            score_penalty=float(r.get("score_penalty", 0)),
        ))
    return rules


def load_agent_config() -> dict[str, Any]:
    """Load Agent Observer settings from rubric YAML."""
    if yaml is None:
        return {"enabled": False}

    file_path = _RUBRIC_YAML_PATH
    if not file_path.exists():
        return {"enabled": False}

    with open(file_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    agent_cfg = raw.get("agent", {})
    return {
        "enabled": bool(agent_cfg.get("enabled", True)),
        "model": agent_cfg.get("model", DEFAULT_SCORING_MODEL),
        "timeout_seconds": int(agent_cfg.get("timeout_seconds", 15)),
        "temperature": float(agent_cfg.get("temperature", 0.1)),
    }


# ── Project Context ────────────────────────────────────────

def _build_project_summary(target_script_path: str, project_root: str = "") -> str:
    """Build concise project context for Agent Observer.

    Extracts: namespace, base class, usings, SerializeField fields, lifecycle patterns.
    """
    parts: list[str] = []

    if project_root:
        parts.append(f"项目根目录: {project_root}")

    if target_script_path:
        target_path = Path(target_script_path)
        if not target_path.is_absolute() and project_root:
            target_path = Path(project_root) / target_script_path

        if target_path.exists():
            try:
                content = target_path.read_text(encoding="utf-8", errors="ignore")
                ns_match = re.search(r"namespace\s+(\S+)", content)
                if ns_match:
                    parts.append(f"命名空间: {ns_match.group(1)}")

                base_match = re.search(r"class\s+\w+\s*:\s*(\S+)", content)
                if base_match:
                    parts.append(f"基类: {base_match.group(1)}")

                usings = re.findall(r"using\s+(\S+?);", content)
                if usings:
                    parts.append(f"using: {', '.join(usings[:10])}")

                fields = re.findall(r"\[SerializeField\][\s\S]*?(\w+)\s+(\w+);", content)
                if fields:
                    fl = ", ".join(f"{t} {n}" for t, n in fields[:6])
                    parts.append(f"序列化字段: {fl}")

                patterns = []
                if "Singleton" in content or "Instance" in content:
                    patterns.append("单例模式")
                if "event" in content or "Action" in content:
                    patterns.append("事件驱动")
                if "ObjectPool" in content:
                    patterns.append("对象池")
                if patterns:
                    parts.append(f"设计模式: {', '.join(patterns)}")

                lifecycle = []
                for m in ["Awake", "Start", "Update", "FixedUpdate", "LateUpdate",
                          "OnEnable", "OnDisable", "OnDestroy"]:
                    if re.search(rf"\b{m}\b\s*\(", content):
                        lifecycle.append(m)
                if lifecycle:
                    parts.append(f"生命周期: {', '.join(lifecycle)}")
            except Exception:
                pass

    if not parts:
        parts.append("(无法读取目标脚本)")

    return "\n".join(parts)


# ── Rules Engine ───────────────────────────────────────────

class RulesEngine:
    """Deterministic rule engine. No LLM. Pure regex + text analysis."""

    def __init__(self, rules: list[ScoringRule], project_context: str = ""):
        self.rules = rules
        self.project_context = project_context

    def _code_lines(self, code: str) -> list[str]:
        return code.splitlines()

    def _rule_match_any(self, rule: ScoringRule, code: str) -> RuleResult:
        """Rule fails if any pattern matches."""
        matched = []
        for pattern in rule.patterns:
            try:
                hits = re.findall(pattern, code, re.MULTILINE | re.DOTALL)
                if hits:
                    # findall can return list of strings or list of tuples; flatten tuples
                    flat: list[str] = []
                    for h in hits:
                        if isinstance(h, str):
                            flat.append(h)
                        elif isinstance(h, tuple):
                            flat.append(str(h[0]) if h else "")
                    matched.extend(flat)
            except Exception:
                continue
        if not matched:
            return RuleResult(rule.id, rule.severity, rule.category, True, [], f"未命中模式: {rule.description}")
        # Truncate display
        display = [str(m)[:120] for m in matched[:3]]
        return RuleResult(rule.id, rule.severity, rule.category, False, display,
                         f"命中 {len(matched)} 处: {rule.description}")

    def _rule_count_gt(self, rule: ScoringRule, code: str) -> RuleResult:
        """Rule fails if total match count > threshold."""
        total = 0
        for pattern in rule.patterns:
            try:
                total += len(re.findall(pattern, code, re.MULTILINE))
            except Exception:
                continue
        if total <= rule.threshold:
            return RuleResult(rule.id, rule.severity, rule.category, True, [],
                             f"发现 {total} 处 (阈值={rule.threshold}): {rule.description}")
        return RuleResult(rule.id, rule.severity, rule.category, False, [f"共 {total} 处"],
                         f"超标: {total} > {rule.threshold}: {rule.description}")

    def _rule_match_none(self, rule: ScoringRule, code: str) -> RuleResult:
        """Rule fails if NO pattern matches (expected something to be present)."""
        for pattern in rule.patterns:
            try:
                if re.search(pattern, code, re.MULTILINE):
                    return RuleResult(rule.id, rule.severity, rule.category, True, [], f"已找到: {rule.description}")
            except Exception:
                continue
        return RuleResult(rule.id, rule.severity, rule.category, False, [], f"缺失: {rule.description}")

    def _rule_match_count(self, rule: ScoringRule, code: str) -> RuleResult:
        """Report match count. Always passes (info-only rule)."""
        total = 0
        for pattern in rule.patterns:
            try:
                total += len(re.findall(pattern, code, re.MULTILINE))
            except Exception:
                continue
        return RuleResult(rule.id, rule.severity, rule.category, True, [f"共 {total} 处"],
                         f"共 {total} 处: {rule.description}")

    def _rule_no_null_guard(self, rule: ScoringRule, code: str) -> RuleResult:
        """Check if GetComponent/Find calls lack a nearby null guard (within 3 lines)."""
        lines = self._code_lines(code)
        unsafe: list[str] = []
        find_re = re.compile(r'(?:GetComponent|Find)(?:<[^>]*>)?\([^)]*\)')

        for i, line in enumerate(lines):
            if find_re.search(line):
                # Check next 3 lines for null guard
                window = lines[i + 1:i + 4]
                guarded = any("null" in w for w in window)
                if not guarded:
                    unsafe.append(f"L{i+1}: {line.strip()[:80]}")

        if len(unsafe) <= rule.threshold:
            return RuleResult(rule.id, rule.severity, rule.category, True, unsafe,
                             f"不安全调用 {len(unsafe)} 处 (阈值={rule.threshold}): {rule.description}")
        return RuleResult(rule.id, rule.severity, rule.category, False, unsafe[:5],
                         f"超标: {len(unsafe)} > {rule.threshold}: {rule.description}")

    def _rule_comment_ratio_lt(self, rule: ScoringRule, code: str) -> RuleResult:
        """Rule fails if comment ratio < threshold%."""
        lines = self._code_lines(code)
        comment_lines = 0
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("//") or stripped.startswith("///") or "/*" in stripped or "*" in stripped[:1]:
                comment_lines += 1
        ratio = (comment_lines / max(1, len(lines))) * 100

        if ratio >= rule.threshold:
            return RuleResult(rule.id, rule.severity, rule.category, True, [],
                             f"注释率 {ratio:.1f}% (阈值={rule.threshold}%): {rule.description}")
        return RuleResult(rule.id, rule.severity, rule.category, False, [f"注释率 {ratio:.1f}%"],
                         f"注释率 {ratio:.1f}% < {rule.threshold}%: {rule.description}")

    def _rule_no_namespace(self, rule: ScoringRule, code: str) -> RuleResult:
        """Check if namespace declaration exists."""
        if re.search(r'namespace\s+\S+', code):
            return RuleResult(rule.id, rule.severity, rule.category, True, [], "命名空间存在")
        return RuleResult(rule.id, rule.severity, rule.category, False, [], "未声明命名空间")

    def _rule_missing_null_guard_in_coroutine(self, rule: ScoringRule, code: str) -> RuleResult:
        """Check if coroutine methods check gameObject != null or this != null before yield."""
        coro_match = re.search(r'IEnumerator\s+(\w+)\s*\([^)]*\)', code, re.MULTILINE)
        if not coro_match:
            return RuleResult(rule.id, rule.severity, rule.category, True, [], "未找到协程方法")
        # Scan coroutine body for yield and check if null guard precedes it
        method_body = code[coro_match.end():]
        # Find first yield
        yield_idx = method_body.find("yield")
        if yield_idx < 0:
            return RuleResult(rule.id, rule.severity, rule.category, True, [], "协程无 yield 语句")
        before_yield = method_body[:yield_idx]
        if "null" in before_yield.lower():
            return RuleResult(rule.id, rule.severity, rule.category, True, [], "协程有判空防护")
        return RuleResult(rule.id, rule.severity, rule.category, False, [], "协程缺少 gameObject/this 判空防护")

    def _rule_namespace_mismatch(self, rule: ScoringRule, code: str, project_ns: str) -> RuleResult:
        """Check if code namespace matches project namespace."""
        if not project_ns:
            return RuleResult(rule.id, rule.severity, rule.category, True, [], "无项目命名空间可比较")
        code_ns = re.search(r'namespace\s+(\S+)', code)
        if not code_ns:
            return RuleResult(rule.id, rule.severity, rule.category, True, [], "参考代码未声明命名空间")
        if code_ns.group(1).lower() == project_ns.lower():
            return RuleResult(rule.id, rule.severity, rule.category, True, [], f"命名空间一致: {project_ns}")
        return RuleResult(rule.id, rule.severity, rule.category, False,
                         [f"参考={code_ns.group(1)} 项目={project_ns}"], f"命名空间不一致")

    def _rule_dependency_check(self, rule: ScoringRule, code: str) -> RuleResult:
        """Check if referenced types/APIs are likely present in the project (heuristic).

        Extracts class references and checks against project context (using directives,
        class names found in the project summary).
        """
        # Extract potential type references (PascalCase words, >=3 chars)
        type_refs = set(re.findall(r'\b([A-Z][a-zA-Z]{2,})\b', code))
        # Comprehensive Unity builtins whitelist
        unity_builtins = {
            # ── Core ──
            "GameObject", "Transform", "MonoBehaviour", "Component", "Object",
            "Behaviour", "Renderer", "Collider", "Collider2D",
            "Rigidbody", "Rigidbody2D", "Joint", "SpringJoint", "FixedJoint", "HingeJoint",
            "Light", "Camera", "Canvas", "CanvasGroup", "CanvasScaler",
            # ── Math / Data ──
            "Vector2", "Vector3", "Vector4", "Quaternion", "Matrix4x4",
            "Color", "Color32", "Mathf", "Random", "Range", "Bounds", "Ray", "RaycastHit", "RaycastHit2D",
            "Plane", "LayerMask", "Physics", "Physics2D", "Time",
            # ── Navigation ──
            "NavMeshAgent", "NavMesh", "NavMeshPath", "NavMeshObstacle", "NavMeshSurface",
            "NavMeshLink", "NavMeshData", "NavMeshTriangulation",
            "SetDestination", "RemainingDistance", "StoppingDistance",
            # ── Animation ──
            "Animator", "Animation", "AnimationClip", "AnimationCurve",
            "AnimatorController", "AnimatorOverrideController", "RuntimeAnimatorController",
            "Avatar", "Humanoid", "AnimatorStateInfo", "AnimatorTransitionInfo",
            "SetFloat", "SetInteger", "SetBool", "SetTrigger", "ResetTrigger",
            "GetFloat", "GetInteger", "GetBool", "GetCurrentAnimatorStateInfo",
            "CrossFade", "Play", "NormalizedTime",
            # ── UI ──
            "Text", "Button", "Image", "Slider", "InputField", "Toggle", "Dropdown",
            "ScrollRect", "Scrollbar", "TextMeshPro", "TextMeshProUGUI", "TMP_Text",
            "RectTransform", "Rect", "LayoutGroup", "HorizontalLayoutGroup",
            "VerticalLayoutGroup", "GridLayoutGroup", "ContentSizeFitter",
            # ── Audio ──
            "AudioSource", "AudioClip", "AudioListener", "AudioMixer", "AudioMixerGroup",
            "PlayOneShot", "PlayClipAtPoint",
            # ── 2D ──
            "SpriteRenderer", "Sprite", "SpriteAtlas", "Tilemap", "Tile", "TileBase",
            "TilemapRenderer", "Grid", "TilemapCollider2D", "CompositeCollider2D",
            "PlatformEffector2D", "SurfaceEffector2D",
            # ── Scene / Resources ──
            "SceneManager", "Scene", "LoadSceneMode", "Resources", "AssetBundle",
            "Addressables", "Application", "Screen", "PlayerPrefs", "Input", "Cursor",
            # ── Events / Delegates ──
            "Action", "Event", "EventArgs", "EventHandler", "UnityEvent", "UnityAction",
            "Delegate", "Func", "Predicate",
            # ── Collections / System ──
            "List", "Dictionary", "Array", "String", "StringBuilder", "Queue", "Stack",
            "HashSet", "LinkedList", "SortedDictionary", "IEnumerable", "IEnumerator",
            "Enumerator", "Collection", "KeyValuePair", "ReadOnlyCollection",
            # ── System / IO ──
            "System", "UnityEngine", "UnityEditor", "File", "Directory", "Path", "StreamReader",
            "StreamWriter", "FileStream", "MemoryStream", "Encoding",
            "Regex", "Thread", "Task", "CancellationToken",
            # ── Debug ──
            "Debug", "LogWarning", "LogError", "LogException", "Assert",
            # ── Coroutine ──
            "WaitForSeconds", "WaitForSecondsRealtime", "WaitForEndOfFrame",
            "WaitUntil", "WaitWhile", "YieldInstruction", "Coroutine",
            # ── Lifecycle methods (PascalCase names that regex will catch) ──
            "Awake", "Start", "Update", "FixedUpdate", "LateUpdate",
            "OnEnable", "OnDisable", "OnDestroy", "OnValidate", "OnTriggerEnter",
            "OnTriggerExit", "OnTriggerStay", "OnCollisionEnter", "OnCollisionExit",
            "OnCollisionStay", "OnTriggerEnter2D", "OnTriggerExit2D", "OnTriggerStay2D",
            "OnCollisionEnter2D", "OnCollisionExit2D", "OnCollisionStay2D",
            "OnDrawGizmos", "OnDrawGizmosSelected", "Reset", "OnGUI",
            # ── Common patterns ──
            "Instance", "Singleton", "SerializeField", "SerializeFiled",
            "Header", "Range", "Tooltip", "RequireComponent", "HideInInspector",
            "DisallowMultipleComponent", "AddComponentMenu", "ExecuteInEditMode",
            "SelectionBase", "ExecuteAlways",
            # ── Misc Unity APIs ──
            "AssetDatabase", "EditorUtility", "Handles", "Gizmos",
            "ScriptableObject", "ScriptableSingleton", "CreateAssetMenu",
            "MenuItem", "ContextMenu", "ContextMenuItem",
            "SerializedObject", "SerializedProperty",
            "EditorApplication", "EditorWindow",
            "Selection", "Undo", "EventSystem",
            "GraphicRaycaster", "RaycastResult", "PointerEventData",
            "StandaloneInputModule", "BaseInputModule",
            "AspectRatioFitter", "LayoutElement", "Mask", "RectMask2D",
            "Outline", "Shadow", "Selectable", "Navigation",
        }

        unknown = type_refs - unity_builtins
        # Heuristic: check if unknown types appear in project context
        if self.project_context:
            project_text = self.project_context.lower()
            truly_unknown = [t for t in unknown if t.lower() not in project_text]
        else:
            truly_unknown = list(unknown)

        if not truly_unknown:
            return RuleResult(rule.id, rule.severity, rule.category, True, [], "所有类型引用在项目中可解析")

        # Don't be too aggressive — <5 unknown types is acceptable
        if len(truly_unknown) <= 5:
            return RuleResult(rule.id, rule.severity, rule.category, True, [f"少量未知道类型: {truly_unknown[:5]}"],
                             f"仅 {len(truly_unknown)} 个类型未在项目上下文中找到")

        return RuleResult(rule.id, rule.severity, rule.category, False,
                         [f"未知道类型: {truly_unknown[:8]}"],
                         f"存在 {len(truly_unknown)} 个类型在当前项目中可能不存在")

    # ── Main dispatch ──

    def evaluate_one(self, code: str, project_context_override: str = "") -> tuple[list[RuleResult], GateResult]:
        """Evaluate all rules against one code snippet. Returns (results, gate)."""
        ctx = project_context_override or self.project_context

        # Extract project namespace from context for namespace_mismatch rule
        project_ns = ""
        for line in ctx.splitlines():
            if line.startswith("命名空间:"):
                project_ns = line.split(":", 1)[1].strip()
                break

        results: list[RuleResult] = []
        # Dispatch table
        dispatch = {
            "match_any": self._rule_match_any,
            "count_gt": self._rule_count_gt,
            "match_none": self._rule_match_none,
            "match_count": self._rule_match_count,
            "no_null_guard": self._rule_no_null_guard,
            "comment_ratio_lt": self._rule_comment_ratio_lt,
            "no_namespace": self._rule_no_namespace,
            "missing_null_guard_in_coroutine": self._rule_missing_null_guard_in_coroutine,
        }

        for rule in self.rules:
            if rule.logic == "namespace_mismatch":
                result = self._rule_namespace_mismatch(rule, code, project_ns)
            elif rule.logic == "dependency_check":
                result = self._rule_dependency_check(rule, code)
            elif rule.logic in dispatch:
                result = dispatch[rule.logic](rule, code)
            else:
                # Unknown logic → fallback to match_any
                result = self._rule_match_any(rule, code)
            results.append(result)

        gate = self.compute_gate(results)
        return results, gate

    def compute_gate(self, results: list[RuleResult]) -> GateResult:
        """Compute gating decision from rule results."""
        critical_fails = [r for r in results if r.severity == "critical" and not r.pass_]
        warning_fails = [r for r in results if r.severity == "warning" and not r.pass_]
        info_items = [r for r in results if r.severity == "info" and not r.pass_]
        pass_count = sum(1 for r in results if r.pass_)

        return GateResult(
            blocked=len(critical_fails) > 0,
            critical_fails=critical_fails,
            warning_fails=warning_fails,
            info_items=info_items,
            pass_count=pass_count,
            total_count=len(results),
        )

    def compute_score(self, results: list[RuleResult], gate: GateResult) -> tuple[float, dict[str, list[dict[str, Any]]]]:
        """Compute overall score from rule results. blocked code gets 0."""
        if gate.blocked:
            dims = self._group_results_by_category(results)
            return 0.0, dims

        max_score = 10.0
        penalty = 0.0
        for r in results:
            if r.severity == "warning" and not r.pass_:
                penalty += r.score_penalty if hasattr(r, 'score_penalty') else 1.5
        for r in results:
            if r.severity == "info" and not r.pass_:
                # info doesn't deduct but we could add minimal penalty if needed
                pass

        # Look up actual score_penalty from original rules
        rule_map = {rule.id: rule.score_penalty for rule in self.rules}
        penalty = 0.0
        for r in results:
            if r.severity in ("warning",) and not r.pass_:
                penalty += rule_map.get(r.rule_id, 1.0)

        score = max(0.0, max_score - penalty)
        dims = self._group_results_by_category(results)
        return round(score, 1), dims

    def _group_results_by_category(self, results: list[RuleResult]) -> dict[str, list[dict[str, Any]]]:
        """Group rule results by category for ScoreCard dimensions output."""
        groups: dict[str, list[dict[str, Any]]] = {}
        for r in results:
            cat = r.category
            if cat not in groups:
                groups[cat] = []
            groups[cat].append({
                "rule_id": r.rule_id,
                "severity": r.severity,
                "pass": r.pass_,
                "matched_lines": r.matched_lines,
                "detail": r.detail,
            })
        return groups


# ── Agent Observer (L2, optional, never affects score/gate) ──

class AgentObserver:
    """Post-hoc semantic observer. Runs AFTER RulesEngine, only writes agent_notes.

    Does NOT participate in scoring or gating. Failure → empty notes (graceful degrade).
    """

    def __init__(self):
        cfg = load_agent_config()
        self.enabled = cfg["enabled"]
        self.model = os.getenv("UNITY_MCP_CODE_SCORING_MODEL", cfg["model"])
        self.timeout = float(os.getenv("UNITY_MCP_CODE_SCORING_TIMEOUT", cfg["timeout_seconds"]))
        self.temperature = cfg["temperature"]
        self.host = os.getenv("OLLAMA_HOST", DEFAULT_OLLAMA_HOST).rstrip("/")
        if self.host and not self.host.lower().startswith(("http://", "https://")):
            self.host = f"http://{self.host}"

    @staticmethod
    def _empty_review(status: str = "skipped", summary: str = "") -> dict[str, Any]:
        return {
            "status": status,
            "reviewed_reference_ids": [],
            "dimensions": [
                {"name": "performance_complexity", "risk_level": "low", "note": ""},
                {"name": "responsibility_cohesion", "risk_level": "low", "note": ""},
                {"name": "project_fit_coupling", "risk_level": "low", "note": ""},
            ],
            "top_risks": [],
            "suggested_refactors": [],
            "summary": summary,
        }

    @staticmethod
    def _normalize_review(raw: Any, reviewed_ids: list[str]) -> dict[str, Any]:
        if not isinstance(raw, dict):
            return AgentObserver._empty_review("skipped", "CodeQualityAgent returned non-JSON output.")

        required_names = ["performance_complexity", "responsibility_cohesion", "project_fit_coupling"]
        raw_dimensions = raw.get("dimensions", [])
        by_name = {
            str(item.get("name", "")): item
            for item in raw_dimensions
            if isinstance(item, dict)
        }
        dimensions: list[dict[str, str]] = []
        for name in required_names:
            item = by_name.get(name, {})
            risk = str(item.get("risk_level", "low")).lower()
            if risk not in {"low", "medium", "high"}:
                risk = "low"
            dimensions.append({
                "name": name,
                "risk_level": risk,
                "note": str(item.get("note", ""))[:220],
            })

        reviewed_set = set(reviewed_ids)
        return {
            "status": "completed",
            "reviewed_reference_ids": [
                str(value)
                for value in raw.get("reviewed_reference_ids", reviewed_ids)
                if str(value) in reviewed_set
            ][:3],
            "dimensions": dimensions,
            "top_risks": [str(item)[:180] for item in raw.get("top_risks", []) if str(item).strip()][:3],
            "suggested_refactors": [
                str(item)[:180]
                for item in raw.get("suggested_refactors", [])
                if str(item).strip()
            ][:3],
            "summary": str(raw.get("summary", ""))[:300],
        }

    async def review_references(
        self,
        references: list[dict[str, Any]],
        project_summary: str = "",
        scorecards: list[ScoreCard] | None = None,
        gates: list[GateResult] | None = None,
        max_references: int = 3,
        max_code_chars_per_reference: int = 1600,
    ) -> dict[str, Any]:
        """Review up to three passed references in one bounded LLM request."""
        if not self.enabled:
            return self._empty_review("skipped", "CodeQualityAgent is disabled.")

        selected = references[: max(0, min(3, max_references))]
        if not selected:
            return self._empty_review("skipped", "No recommended references to review.")

        review_items: list[dict[str, Any]] = []
        reviewed_ids: list[str] = []
        for index, ref in enumerate(selected, start=1):
            ref_id = str(ref.get("id") or f"reference_{index}")
            reviewed_ids.append(ref_id)
            card = ref.get("_scorecard")
            if card is None and scorecards and index - 1 < len(scorecards):
                card = scorecards[index - 1]
            gate = ref.get("_gate")
            if gate is None and gates and index - 1 < len(gates):
                gate = gates[index - 1]
            review_items.append({
                "id": ref_id,
                "file_path": ref.get("file_path", ""),
                "class_name": ref.get("class_name", ""),
                "method_name": ref.get("method_name", ""),
                "rule_score": getattr(card, "overall_score", None),
                "rule_summary": getattr(card, "summary", ""),
                "critical_fails": [result.rule_id for result in getattr(gate, "critical_fails", [])],
                "warning_fails": [result.rule_id for result in getattr(gate, "warning_fails", [])],
                "code_preview": str(ref.get("text", ""))[:max_code_chars_per_reference],
            })

        prompt = (
            "You are CodeQualityAgent for Unity C# reference-code selection.\n"
            "RulesEngine already handled deterministic checks and hard gating. "
            "Do not rescore and do not block anything.\n"
            "Review only these three soft dimensions: performance_complexity, "
            "responsibility_cohesion, project_fit_coupling.\n"
            "Return ONLY strict JSON with keys: status, reviewed_reference_ids, "
            "dimensions, top_risks, suggested_refactors, summary.\n"
            "Each dimension must contain: name, risk_level (low|medium|high), note.\n"
            "Limit top_risks and suggested_refactors to at most 3 short items each.\n\n"
            f"PROJECT_CONTEXT:\n{project_summary or '(not provided)'}\n\n"
            f"REFERENCES:\n{json.dumps(review_items, ensure_ascii=False, indent=2)}"
        )

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.host}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {"temperature": self.temperature, "num_ctx": 8192},
                    },
                )
                response.raise_for_status()
                body = response.json()
                text = body.get("response", "").strip()
                if text.startswith("```"):
                    text = re.sub(r"^```(?:json)?\s*", "", text)
                    text = re.sub(r"\s*```$", "", text)
                return self._normalize_review(json.loads(text), reviewed_ids)
        except httpx.TimeoutException as exc:
            logger.warning("CodeQualityAgent timed out: %s", exc)
            return self._empty_review("skipped", "CodeQualityAgent timed out.")
        except Exception as exc:
            logger.warning("CodeQualityAgent failed (graceful degrade): %s", exc)
            return self._empty_review("unavailable", f"CodeQualityAgent unavailable: {exc}")

    async def observe(
        self,
        code_text: str,
        score_card: ScoreCard,
        gate_result: GateResult,
        rule_results: list[RuleResult],
        project_summary: str = "",
    ) -> str:
        """Backward-compatible single-snippet wrapper around CodeQualityAgent."""
        review = await self.review_references(
            [{
                "id": "single_reference",
                "text": code_text,
                "_scorecard": score_card,
                "_gate": gate_result,
            }],
            project_summary=project_summary,
            max_references=1,
        )
        score_card.agent_review = review
        score_card.agent_notes = str(review.get("summary", ""))[:300]
        return score_card.agent_notes


# ── Public API (called by game_code_tools.py) ──

def evaluate_references(
    references: list[dict[str, Any]],
    project_summary: str = "",
    rules: list[ScoringRule] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Synchronous batch evaluation. Returns (passed_refs, blocked_refs).

    Each returned ref dict has '_gate' and '_scorecard' keys added.
    """
    if rules is None:
        rules = load_rules()

    engine = RulesEngine(rules, project_summary)
    passed: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []

    for ref in references:
        code_text = ref.get("text", "")
        keyword_score = float(ref.get("score", 0))

        if not code_text.strip():
            ref["_gate"] = GateResult(blocked=False, total_count=0)
            ref["_scorecard"] = ScoreCard(overall_score=0.0, recommendation="not_recommended",
                                          summary="空代码片段", keyword_score=keyword_score,
                                          combined_score=keyword_score * 0.3)
            passed.append(ref)
            continue

        # Check cache
        cache_key = hashlib.sha256(f"v2|{code_text[:200]}".encode()).hexdigest()
        if cache_key in _SCORE_CACHE:
            cached = _SCORE_CACHE[cache_key]
            ref["_gate"] = cached["gate"]
            ref["_scorecard"] = cached["scorecard"]
        else:
            results, gate = engine.evaluate_one(code_text)
            score, dims = engine.compute_score(results, gate)
            blocked_flag = gate.blocked
            recommendation = "not_recommended" if blocked_flag else (
                "recommended" if score >= 7.0 else "recommended_with_caution"
            )
            card = ScoreCard(
                overall_score=score,
                blocked=blocked_flag,
                dimensions=[
                    {"category": cat, "checks": items}
                    for cat, items in dims.items()
                ],
                recommendation=recommendation,
                summary=f"Gate: {'BLOCKED' if blocked_flag else 'PASS'} ({gate.pass_count}/{gate.total_count} rules passed)",
                keyword_score=keyword_score,
                combined_score=round(keyword_score * 0.3 + (score / 10.0) * 0.7, 4),
            )
            ref["_gate"] = gate
            ref["_scorecard"] = card
            _SCORE_CACHE[cache_key] = {"gate": gate, "scorecard": card}
            if len(_SCORE_CACHE) > _MAX_CACHE_ENTRIES:
                _SCORE_CACHE.pop(next(iter(_SCORE_CACHE)))

        if ref["_gate"].blocked:
            blocked.append(ref)
        else:
            passed.append(ref)

    # Sort passed by combined_score desc
    passed.sort(key=lambda r: r["_scorecard"].combined_score, reverse=True)
    return passed, blocked


async def evaluate_references_async(
    references: list[dict[str, Any]],
    project_summary: str = "",
    rules: list[ScoringRule] | None = None,
    run_agent_observer: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Async batch evaluation with optional Agent Observer notes.

    Returns (passed_refs, blocked_refs) with _gate, _scorecard, and optionally
    _scorecard.agent_review filled by CodeQualityAgent.
    """
    passed, blocked = evaluate_references(references, project_summary, rules)

    if run_agent_observer:
        observer = AgentObserver()
        reviewed_refs = [
            ref
            for ref in passed[:3]
            if isinstance(ref.get("_scorecard"), ScoreCard) and not ref.get("_scorecard").blocked
        ]
        review = await observer.review_references(reviewed_refs, project_summary=project_summary)
        reviewed_ids = set(review.get("reviewed_reference_ids", []))
        for ref in reviewed_refs:
            ref_id = str(ref.get("id") or "")
            card: ScoreCard | None = ref.get("_scorecard")
            if card is None:
                continue
            if not reviewed_ids or ref_id in reviewed_ids:
                card.agent_review = review
                card.agent_notes = str(review.get("summary", ""))[:300]

    return passed, blocked


def _serialize_scorecard(card: ScoreCard) -> dict[str, Any]:
    """Serialize ScoreCard to dict for API responses (backward compatible)."""
    return {
        "overall_score": card.overall_score,
        "blocked": card.blocked,
        "keyword_score": card.keyword_score,
        "combined_score": card.combined_score,
        "recommendation": card.recommendation,
        "summary": card.summary,
        "agent_notes": card.agent_notes,
        "agent_review": card.agent_review,
        "dimensions": card.dimensions,
    }


# ── Task runner (for standalone score_game_code MCP tool) ──

async def run_score_game_code_task(task: Any) -> dict[str, Any]:
    """Task runner for AdaptTaskManager. Uses RulesEngine (no LLM in scoring)."""

    def _update(tsk: Any, phase: str, progress: float) -> None:
        if tsk is not None and hasattr(tsk, "update"):
            tsk.update(phase=phase, progress=progress)

    request = task.request
    code_text = request.get("code_text", "")
    target_script_path = request.get("target_script_path", "")
    project_root = request.get("project_root", "")

    if not code_text.strip():
        return {"status": "error", "error": "code_text is required and must not be empty.", "scorecard": None}

    _update(task, "load_rules", 0.1)
    rules = load_rules()

    _update(task, "build_context", 0.2)
    project_summary = _build_project_summary(target_script_path, project_root)

    _update(task, "run_rules", 0.35)
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
        summary=f"Gate: {'BLOCKED' if gate.blocked else 'PASS'} ({gate.pass_count}/{gate.total_count} rules passed)",
        keyword_score=float(request.get("keyword_score", 0)),
        combined_score=round(float(request.get("keyword_score", 0)) * 0.3 + (score / 10.0) * 0.7, 4),
    )

    # Optional: run Agent Observer
    run_agent = request.get("run_agent_observer", False)
    if run_agent:
        _update(task, "agent_observer", 0.7)
        observer = AgentObserver()
        try:
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
        except Exception as exc:
            logger.warning("AgentObserver failed in task runner: %s", exc)

    _update(task, "done", 1.0)
    return {
        "status": "completed",
        "scorecard": _serialize_scorecard(card),
    }

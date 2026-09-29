"""
代码知识图谱提取器
从代码块元数据提取实体（class/method/field/file/game）和关系（inherits/has_method/calls等），
构建与 ExtendedKnowledgeGraph 兼容的 JSON 图文件。

用法：
    extractor = CodeGraphExtractor()
    graph_data = extractor.build_from_chunks(code_chunks)
    extractor.save(graph_data, "game_code_graph.json")
"""

import os
import re
import json
import logging
from pathlib import Path
from collections import defaultdict
from typing import List, Dict, Optional, Set, Tuple, Any

logger = logging.getLogger(__name__)


class CodeGraphExtractor:
    """从代码块构建实体-关系知识图谱"""

    # 支持的关系类型
    RELATION_TYPES = {
        "game_contains_class": "game_contains_class",
        "class_has_method": "class_has_method",
        "class_has_field": "class_has_field",
        "class_inherits": "class_inherits",
        "method_calls": "method_calls",
        "method_uses_field": "method_uses_field",
        "file_contains_class": "file_contains_class",
        "same_game": "same_game",
    }

    # 实体类型
    ENTITY_TYPES = {
        "game": "game",
        "class": "class",
        "method": "method",
        "field": "field",
        "file": "file",
    }

    def __init__(self):
        self.entities: Dict[str, dict] = {}
        self.relations: List[dict] = []
        self._entity_counter = 0

    def _make_id(self, prefix: str) -> str:
        self._entity_counter += 1
        return f"{prefix}:{self._entity_counter}"

    # ---- 构建入口 ----

    def build_from_chunks(self, chunks: List[Any]) -> Dict[str, Any]:
        """
        从 CodeChunk 列表构建图

        Args:
            chunks: CodeChunk 对象列表（来自 code_processor.py）

        Returns:
            图数据字典: {"nodes": [...], "edges": [...]}
        """
        self.entities = {}
        self.relations = []
        self._entity_counter = 0

        # 第一遍：按代码块元数据创建实体
        self._extract_entities(chunks)

        # 第二遍：分析代码文本提取关系
        self._extract_relations(chunks)

        logger.info(f"图构建完成: {len(self.entities)} 实体, {len(self.relations)} 关系")
        return self._to_dict()

    # ---- 实体提取 ----

    def _extract_entities(self, chunks: List[Any]) -> None:
        """从代码块创建实体"""
        seen_games: Set[str] = set()
        seen_files: Set[str] = set()
        seen_classes: Set[str] = set()
        game_class_ids: Dict[str, str] = {}  # game_key -> entity_id

        for chunk in chunks:
            meta = getattr(chunk, 'metadata', None) or {}
            text = getattr(chunk, 'text', '') or ''
            chunk_id = getattr(chunk, 'id', '') or ''
            code_type = meta.get('code_type', '') if isinstance(meta, dict) else ''

            game_name = meta.get('game_name', 'unknown')
            file_path = meta.get('file_path', '')
            file_name = meta.get('file_name', '')
            class_name = meta.get('class_name', '')
            method_name = meta.get('method_name', '')
            class_name = meta.get('class_name', '')
            method_name = meta.get('method_name', '')

            # 游戏实体
            game_key = game_name
            if game_key not in seen_games:
                gid = self._make_id("game")
                self.entities[gid] = {
                    "id": gid,
                    "name": game_name,
                    "entity_type": "game",
                    "description": f"游戏项目: {game_name}",
                    "metadata": {"game_name": game_name}
                }
                seen_games.add(game_key)
                game_class_ids[game_key] = gid

            # 文件实体
            if file_path and file_path not in seen_files:
                fid = self._make_id("file")
                self.entities[fid] = {
                    "id": fid,
                    "name": file_name or os.path.basename(file_path),
                    "entity_type": "file",
                    "description": file_path,
                    "metadata": {"file_path": file_path, "game_name": game_name}
                }
                seen_files.add(file_path)

            # 类实体 (从 class_overview 块创建)
            if code_type == 'class_overview' and class_name:
                cid = f"class:{class_name}"
                if cid not in seen_classes:
                    bases = self._parse_inheritance(text)
                    self.entities[cid] = {
                        "id": cid,
                        "name": class_name,
                        "entity_type": "class",
                        "description": f"类 {class_name} (来源: {game_name})",
                        "metadata": {
                            "game_name": game_name,
                            "file_path": file_path,
                            "file_name": file_name,
                            "base_classes": bases,
                        }
                    }
                    seen_classes.add(cid)

                    # game_contains_class
                    gid = game_class_ids.get(game_name)
                    if gid:
                        self.relations.append({
                            "source": gid,
                            "target": cid,
                            "relation_type": "game_contains_class",
                            "weight": 0.9,
                            "metadata": {}
                        })

                    # 继承关系
                    for base in bases:
                        bic = f"class:{base}"
                        self.entities.setdefault(bic, {
                            "id": bic,
                            "name": base,
                            "entity_type": "class",
                            "description": f"外部基类: {base}",
                            "metadata": {"external": True}
                        })
                        self.relations.append({
                            "source": cid,
                            "target": bic,
                            "relation_type": "class_inherits",
                            "weight": 0.85,
                            "metadata": {}
                        })

            # 方法实体 (从 method_detail 块创建)
            if code_type == 'method_detail' and class_name and method_name:
                mid = f"method:{class_name}.{method_name}"
                is_coroutine = meta.get('is_coroutine', 'False') == 'True'
                return_type = meta.get('return_type', '')
                self.entities[mid] = {
                    "id": mid,
                    "name": method_name,
                    "entity_type": "method",
                    "description": f"{class_name}.{method_name}() -> {return_type} "
                                   f"{'[coroutine]' if is_coroutine else ''}",
                    "metadata": {
                        "class_name": class_name,
                        "game_name": game_name,
                        "file_path": file_path,
                        "is_coroutine": is_coroutine,
                        "return_type": return_type,
                        "chunk_id": chunk_id,
                    }
                }

                # class_has_method
                cid = f"class:{class_name}"
                if cid in self.entities:
                    self.relations.append({
                        "source": cid,
                        "target": mid,
                        "relation_type": "class_has_method",
                        "weight": 0.8,
                        "metadata": {}
                    })

            # 字段实体 (从 class_overview 提取字段)
            if code_type == 'class_overview' and class_name:
                cid = f"class:{class_name}"
                if cid in seen_classes:
                    fields = self._parse_fields(text)
                    for fname, ftype in fields:
                        fid = f"field:{class_name}.{fname}"
                        self.entities[fid] = {
                            "id": fid,
                            "name": fname,
                            "entity_type": "field",
                            "description": f"{ftype} {class_name}.{fname}",
                            "metadata": {
                                "class_name": class_name,
                                "field_type": ftype,
                                "game_name": game_name,
                            }
                        }
                        self.relations.append({
                            "source": cid,
                            "target": fid,
                            "relation_type": "class_has_field",
                            "weight": 0.7,
                            "metadata": {}
                        })

    # ---- 关系提取 ----

    def _extract_relations(self, chunks: List[Any]) -> None:
        """从代码块中提取方法调用关系"""
        for chunk in chunks:
            meta = getattr(chunk, 'metadata', None) or {}
            text = getattr(chunk, 'text', '') or ''
            code_type = meta.get('code_type', '') if isinstance(meta, dict) else ''
            class_name = meta.get('class_name', '') if isinstance(meta, dict) else ''
            method_name = meta.get('method_name', '') if isinstance(meta, dict) else ''

            if code_type != 'method_detail' or not class_name or not method_name:
                continue

            mid = f"method:{class_name}.{method_name}"
            if mid not in self.entities:
                continue

            # 提取方法体中调用的方法/属性
            called = self._parse_method_calls(text, class_name)

            for target_name in called:
                # 尝试解析为 method:ClassName.MethodName 或 field:ClassName.FieldName
                # 或同类的 method:class_name.method_name
                tid = f"method:{target_name}"

                # 检查是否是已知的方法
                if tid not in self.entities:
                    # 可能是同类的私有方法
                    tid_same = f"method:{class_name}.{target_name}"
                    if tid_same in self.entities:
                        tid = tid_same
                    else:
                        # 外部 API 调用，创建外部实体
                        self.entities.setdefault(tid, {
                            "id": tid,
                            "name": target_name.split('.')[-1],
                            "entity_type": "method",
                            "description": f"外部方法: {target_name}()",
                            "metadata": {"external": True}
                        })

                self.relations.append({
                    "source": mid,
                    "target": tid,
                    "relation_type": "method_calls",
                    "weight": 0.55,
                    "metadata": {}
                })

        # 补充 same_game 关系（同游戏内的类之间）
        game_classes: Dict[str, List[str]] = defaultdict(list)
        for eid, ent in self.entities.items():
            if ent['entity_type'] == 'class' and not ent['metadata'].get('external'):
                gname = ent['metadata'].get('game_name', '')
                game_classes[gname].append(eid)

        for gname, class_ids in game_classes.items():
            for i in range(len(class_ids)):
                for j in range(i + 1, len(class_ids)):
                    self.relations.append({
                        "source": class_ids[i],
                        "target": class_ids[j],
                        "relation_type": "same_game",
                        "weight": 0.5,
                        "metadata": {}
                    })

    # ---- 解析辅助方法 ----

    _INHERIT_RE = re.compile(r'class\s+\w+\s*:\s*([\w<>,.\s]+)', re.IGNORECASE)

    def _parse_inheritance(self, text: str) -> List[str]:
        """从类概述文本中提取基类名"""
        bases = []
        for line in text.split('\n'):
            m = self._INHERIT_RE.search(line)
            if m:
                raw = m.group(1).strip()
                # 分割泛型符号和逗号
                parts = re.split(r'[,<>]', raw)
                for p in parts:
                    p = p.strip()
                    if p and p.lower() not in ('monobehaviour', 'scriptableobject',
                                                'object', 'enum', 'struct'):
                        bases.append(p)
        return bases

    _FIELD_RE = re.compile(
        r'(public|private|protected|internal|static|const|readonly)?\s*'
        r'([\w<>\[\],.\s]+?)\s+(\w+)\s*[;=]',
        re.IGNORECASE
    )

    def _parse_fields(self, text: str) -> List[Tuple[str, str]]:
        """从类概述中提取字段 (name, type)"""
        fields = []
        # 只在 "Fields & Properties" 之后开始匹配
        in_fields = False
        for line in text.split('\n'):
            line = line.strip()
            if 'field' in line.lower() and 'properties' in line.lower():
                in_fields = True
                continue
            if in_fields and not line:
                continue
            if in_fields:
                m = self._FIELD_RE.match(line)
                if m:
                    type_name = m.group(2).strip() if m.group(2) else 'object'
                    field_name = m.group(3).strip()
                    # 排除关键字
                    if field_name.lower() not in ('new', 'class', 'struct', 'enum', 'void', 'int',
                                                   'float', 'string', 'bool', 'gameobject', 'vector3',
                                                   'vector2', 'color', 'transform'):
                        fields.append((field_name, type_name))
        return fields

    _CALL_RE = re.compile(r'(?:^|\s|\.)([A-Z][\w]*(?:\.[A-Z][\w]*)+)\.(\w+)\s*\(',
                          re.MULTILINE)
    _SELF_CALL_RE = re.compile(r'\b(?!new\b)([a-z_]\w*)\s*\(', re.IGNORECASE)

    def _parse_method_calls(self, text: str, class_name: str) -> Set[str]:
        """从方法代码中提取调用的方法名"""
        calls = set()

        # 提取 "ClassName.MethodName(" 或 "Instance.MethodName(" 模式
        for m in self._CALL_RE.finditer(text):
            full = f"{m.group(1)}.{m.group(2)}"
            calls.add(full)

        # 提取同类方法调用 "MethodName(" 模式
        for m in self._SELF_CALL_RE.finditer(text):
            name = m.group(1)
            # 排除 C# 关键字和已知 Unity API
            filtered = name.lower()
            if filtered not in ('if', 'for', 'while', 'foreach', 'switch', 'using',
                                'lock', 'fixed', 'checked', 'unchecked', 'sizeof',
                                'typeof', 'nameof', 'default', 'instantiate',
                                'destroy', 'getcomponent', 'setactive', 'addcomponent',
                                'debug', 'print', 'startcoroutine', 'stopcoroutine',
                                'invoke', 'invokerepeating', 'cancelinvoke',
                                'getkeydown', 'getkey', 'getkeyup',
                                'ispointerovergameobject'):
                calls.add(f"{class_name}.{name}")

        return calls

    # ---- 序列化 ----

    def _to_dict(self) -> Dict[str, Any]:
        return {
            "nodes": list(self.entities.values()),
            "edges": self.relations,
            "stats": {
                "entity_count": len(self.entities),
                "relation_count": len(self.relations),
                "entity_types": self._count_types(self.entities),
                "relation_types": self._count_relation_types(self.relations),
            }
        }

    @staticmethod
    def _count_types(entities: Dict[str, dict]) -> Dict[str, int]:
        counts = defaultdict(int)
        for e in entities.values():
            counts[e['entity_type']] += 1
        return dict(counts)

    @staticmethod
    def _count_relation_types(relations: List[dict]) -> Dict[str, int]:
        counts = defaultdict(int)
        for r in relations:
            counts[r['relation_type']] += 1
        return dict(counts)

    def save(self, data: Dict[str, Any], filepath: str) -> None:
        """保存图数据到 JSON 文件"""
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"图数据已保存: {filepath} "
                    f"({data['stats']['entity_count']} 实体, "
                    f"{data['stats']['relation_count']} 关系)")


class GameCodeGraph:
    """
    轻量游戏代码知识图谱检索器
    兼容 ExtendedKnowledgeGraph 的接口风格
    """

    _TOKEN_RE = re.compile(r'[a-zA-Z_]\w*|[0-9]+|\S')  # 分词正则

    def __init__(self, graph_data: Dict[str, Any]):
        self.nodes: Dict[str, dict] = {}
        self.edges: List[dict] = graph_data.get('edges', [])
        self.stats: Dict[str, Any] = graph_data.get('stats', {})

        for node in graph_data.get('nodes', []):
            self.nodes[node['id']] = node

        # 构建索引
        self._entity_type_index: Dict[str, List[str]] = defaultdict(list)
        self._source_index: Dict[str, List[int]] = defaultdict(list)
        self._target_index: Dict[str, List[int]] = defaultdict(list)
        # 搜索倒排索引: token_lower → {entity_id: score}
        self._search_index: Dict[str, Dict[str, float]] = defaultdict(dict)

        for nid, node in self.nodes.items():
            self._entity_type_index[node['entity_type']].append(nid)
            self._index_node(nid, node)

        for i, edge in enumerate(self.edges):
            self._source_index[edge['source']].append(i)
            self._target_index[edge['target']].append(i)

    def _index_node(self, nid: str, node: dict) -> None:
        """为单个实体建立搜索倒排索引"""
        name = node.get('name', '')
        desc = node.get('description', '')
        
        # 名字分词 (权重 2.0)
        for token in self._TOKEN_RE.findall(name):
            token = token.lower().strip('.,;:()[]{}"\'')
            if len(token) >= 2:
                current = self._search_index[token].get(nid, 0)
                self._search_index[token][nid] = current + 2.0
        
        # 描述分词 (权重 1.0)
        for token in self._TOKEN_RE.findall(desc):
            token = token.lower().strip('.,;:()[]{}"\'')
            if len(token) >= 2:
                current = self._search_index[token].get(nid, 0)
                self._search_index[token][nid] = max(current, current + 1.0)  # 名>描

    # ---- 查询方法 ----

    def search_by_name(self, query: str, limit: int = 10) -> List[dict]:
        """按名称/描述搜索实体（倒排索引，O(k) k=命中数）"""
        scored: Dict[str, float] = defaultdict(float)
        query_lower = query.lower()

        # 词法匹配（倒排索引快速查找）
        for token in self._TOKEN_RE.findall(query):
            token = token.lower().strip('.,;:()[]{}"\'')
            if len(token) >= 2 and token in self._search_index:
                for nid, score in self._search_index[token].items():
                    scored[nid] += score

        # 回退：子串匹配（仅在分词无结果时启用）
        if not scored:
            for nid, node in self.nodes.items():
                if query_lower in node.get('name', '').lower():
                    scored[nid] = 2.0
                elif query_lower in node.get('description', '').lower():
                    scored[nid] = 1.0

        results = [(s, self.nodes[nid]) for nid, s in scored.items() if nid in self.nodes]
        results.sort(key=lambda x: x[0], reverse=True)
        return [r[1] for r in results[:limit]]

    def get_by_type(self, entity_type: str) -> List[dict]:
        """按实体类型获取"""
        ids = self._entity_type_index.get(entity_type, [])
        return [self.nodes[nid] for nid in ids]

    def get_entity(self, entity_id: str) -> Optional[dict]:
        return self.nodes.get(entity_id)

    def get_relations(self, entity_id: str, relation_type: str = None) -> List[dict]:
        """获取实体的所有关系"""
        result = []
        for idx in self._source_index.get(entity_id, []):
            edge = self.edges[idx]
            if relation_type is None or edge['relation_type'] == relation_type:
                result.append(edge)
        for idx in self._target_index.get(entity_id, []):
            edge = self.edges[idx]
            if relation_type is None or edge['relation_type'] == relation_type:
                result.append(edge)
        return result

    def get_neighbors(self, entity_id: str, relation_type: str = None) -> List[dict]:
        """获取实体的邻居实体"""
        neighbors = []
        seen = set()

        for idx in self._source_index.get(entity_id, []):
            edge = self.edges[idx]
            if relation_type is None or edge['relation_type'] == relation_type:
                tid = edge['target']
                if tid in self.nodes and tid not in seen:
                    neighbors.append(self.nodes[tid])
                    seen.add(tid)

        for idx in self._target_index.get(entity_id, []):
            edge = self.edges[idx]
            if relation_type is None or edge['relation_type'] == relation_type:
                sid = edge['source']
                if sid in self.nodes and sid not in seen:
                    neighbors.append(self.nodes[sid])
                    seen.add(sid)

        return neighbors

    def traverse(self, start_id: str, relation_type: str = None,
                 max_depth: int = 2) -> Dict[str, Any]:
        """
        图遍历：从起始实体出发，按深度遍历

        Returns: {"entity": ..., "relations": [...], "neighbors": [...]}
        """
        entity = self.nodes.get(start_id)
        if not entity:
            return {"error": f"实体不存在: {start_id}"}

        visited = {start_id}
        result_relations = []
        result_neighbors = []

        queue = [(start_id, 0)]
        while queue:
            current, depth = queue.pop(0)
            if depth >= max_depth:
                continue

            for idx in self._source_index.get(current, []):
                edge = self.edges[idx]
                result_relations.append(edge)
                nid = edge['target']
                if nid not in visited and nid in self.nodes:
                    visited.add(nid)
                    result_neighbors.append(self.nodes[nid])
                    queue.append((nid, depth + 1))

            for idx in self._target_index.get(current, []):
                edge = self.edges[idx]
                result_relations.append(edge)
                nid = edge['source']
                if nid not in visited and nid in self.nodes:
                    visited.add(nid)
                    result_neighbors.append(self.nodes[nid])
                    queue.append((nid, depth + 1))

        return {
            "entity": entity,
            "relations": result_relations,
            "neighbors": result_neighbors,
        }


def load_graph(filepath: str) -> Optional[GameCodeGraph]:
    """从 JSON 文件加载知识图谱"""
    if not os.path.exists(filepath):
        logger.warning(f"图文件不存在: {filepath}")
        return None
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return GameCodeGraph(data)

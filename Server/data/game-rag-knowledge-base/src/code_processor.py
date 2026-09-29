"""
C# 代码处理器
负责扫描游戏源码目录、提取 .cs 文件、按类/方法边界智能分块

核心策略：
- 每个类生成1个「类概览块」（using + class声明 + 字段/属性，不含方法体）
- 每个方法生成1个「方法详细块」（类名前缀 + 完整方法代码 + 注释）
- 元数据携带 game_name、class_name、method_name、code_type、file_path

未来升级 GraphRAG 时，元数据可直接用于构建实体-关系图。
"""

import os
import re
import json
import logging
from pathlib import Path
from typing import List, Dict, Optional, Generator, Tuple
from dataclasses import dataclass, field


logger = logging.getLogger(__name__)


@dataclass
class CodeChunk:
    """代码分块数据结构"""
    id: str                      # game_name/class_name/method_name_chunk_N
    text: str                    # 增强文本（类名前缀 + 代码 + 注释）
    metadata: Dict[str, str]     # 元数据字典
    doc_id: str                  # 所属文件 ID
    chunk_index: int             # 分块序号


@dataclass
class ClassInfo:
    """类/结构体/枚举信息"""
    name: str
    code_type: str               # class / struct / enum
    start_line: int
    end_line: int
    body_start: int              # { 所在行
    body_end: int                # } 所在行
    modifiers: str = ""          # public/private/internal/static/abstract
    base_class: str = ""         # 基类/接口
    fields: List[str] = field(default_factory=list)  # 字段声明行
    properties: List[str] = field(default_factory=list)  # 属性声明行


@dataclass
class MethodInfo:
    """方法信息"""
    name: str
    return_type: str
    start_line: int
    end_line: int
    body_start: int
    body_end: int
    modifiers: str = ""          # public/private/protected/internal/static/virtual/override
    is_static: bool = False
    is_coroutine: bool = False   # IEnumerator


class CodeProcessor:
    """C# 代码处理器"""

    # 类/结构体/枚举声明正则
    CLASS_PATTERN = re.compile(
        r'^'
        r'(?P<modifiers>(?:(?:public|private|protected|internal)\s+)?'
        r'(?:(?:static|abstract|sealed|partial)\s+)*)'
        r'(?P<type>class|struct|enum)\s+'
        r'(?P<name>\w+)\s*'
        r'(?P<inheritance>:.*?)?'
        r'$',
        re.MULTILINE
    )

    # 方法声明正则（匹配行首的方法签名）
    METHOD_PATTERN = re.compile(
        r'^'
        r'(?P<modifiers>(?:(?:public|private|protected|internal)\s+)?'
        r'(?:(?:static|virtual|override|abstract|async|sealed|new)\s+)*)'
        r'(?P<return_type>(?:[\w<>\[\],.\s]+?))\s+'
        r'(?P<name>\w+)\s*'
        r'\((?P<params>[^)]*)\)\s*'
        r'$',
        re.MULTILINE
    )

    # 属性声明正则（get/set 属性）
    PROPERTY_PATTERN = re.compile(
        r'^'
        r'(?P<modifiers>(?:public|private|protected|internal)\s+)'
        r'(?:(?:static|virtual|override|abstract)\s+)*'
        r'(?P<type>[\w<>\[\],.\s]+)\s+'
        r'(?P<name>\w+)\s*'
        r'\{\s*(?P<body>get;[^}]*|set;[^}]*|get\s*\{[^}]*\}\s*set\s*\{[^}]*\})\s*\}'
        r'$',
        re.MULTILINE
    )

    # 字段声明正则
    FIELD_PATTERN = re.compile(
        r'^'
        r'(?P<modifiers>(?:public|private|protected|internal)\s+)'
        r'(?:(?:static|readonly|const|volatile)\s+)*'
        r'(?P<type>[\w<>\[\],.\s]+)\s+'
        r'(?P<name>\w+)\s*'
        r'(?:=\s*(?:[^;]+))?;'
        r'$',
        re.MULTILINE
    )

    # using 语句正则
    USING_PATTERN = re.compile(r'^using\s+[^;]+;', re.MULTILINE)

    # 注释正则
    COMMENT_PATTERN = re.compile(r'//.*$|/\*[\s\S]*?\*/', re.MULTILINE)

    def __init__(self, source_root: str, config: Optional[dict] = None):
        """
        Args:
            source_root: 游戏源码根目录（例如 game_source/）
            config: 配置字典，支持 chunk_size 等参数
        """
        self.source_root = Path(source_root)
        self.config = config or {}
        self.max_file_size = self.config.get('max_file_size_kb', 200) * 1024  # 最大文件大小

    def scan_game_dirs(self) -> List[Path]:
        """
        扫描游戏源码目录，找到所有游戏子目录

        Returns:
            游戏目录路径列表
        """
        games = []
        if not self.source_root.exists():
            logger.error(f"游戏源码目录不存在: {self.source_root}")
            return games

        for item in self.source_root.iterdir():
            if item.is_dir():
                # 检查是否包含 Unity 项目特征
                scripts_dir = item / "Assets" / "Scripts"
                # 也检查更深层路径
                deep_scripts = list(item.rglob("*/Assets/Scripts"))
                if scripts_dir.exists() or deep_scripts:
                    games.append(item)

        logger.info(f"扫描到 {len(games)} 个游戏项目")
        return games

    # 资产文件扩展名
    ASSET_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.prefab', '.controller', '.anim', '.asset', '.unity', '.mat'}

    @staticmethod
    def _is_asset_file(file_path: Path) -> bool:
        return file_path.suffix.lower() in CodeProcessor.ASSET_EXTENSIONS

    def find_cs_files(self, game_dir: Path) -> List[Path]:
        """
        在游戏目录下查找所有 .cs 脚本文件

        优先在 Assets/Scripts/ 下查找，也搜索其他路径
        """
        cs_files = []

        # 优先扫描 Assets/Scripts/
        for pattern in ["**/Assets/Scripts/**/*.cs", "**/*.cs"]:
            found = list(game_dir.rglob(pattern))
            # 过滤掉非源码文件
            found = [
                f for f in found
                if not any(x in f.parts for x in ['Plugins', 'Plugins', 'Editor', 'Generated'])
            ]
            if found:
                cs_files.extend(found)
                break

        # 也包含 Plugins 中有意义的脚本
        plugins_cs = list(game_dir.rglob("**/Pluggins/**/*.cs"))
        for p in plugins_cs:
            if p not in cs_files and p.stat().st_size < 1024 * 1024:  # 跳过超大文件
                cs_files.append(p)

        return cs_files

    def find_asset_files(self, game_dir: Path) -> List[Path]:
        """
        查找游戏目录下的资源文件（图片、预制体、动画等）
        """
        assets = []
        # 跳过无关目录
        skip_dirs = {'Plugins', 'Editor', 'Generated', 'Library', 'Packages', 'Build'}
        for ext in self.ASSET_EXTENSIONS:
            for f in game_dir.rglob(f"**/*{ext}"):
                if any(s in f.parts for s in skip_dirs):
                    continue
                assets.append(f)
        # 限制数量避免爆炸
        if len(assets) > 2000:
            logger.warning(f"资产文件过多 ({len(assets)})，采样 2000 个")
            assets = assets[:2000]
        return assets

    def find_package_files(self, game_dir: Path) -> List[Path]:
        """查找游戏项目中的包管理文件"""
        results = []
        for p in game_dir.rglob("**/Packages/manifest.json"):
            results.append(p)
        for p in game_dir.rglob("**/Packages/packages-lock.json"):
            if p not in results:
                results.append(p)
        return results

    def process_package_file(self, file_path: Path, game_name: str) -> Optional[CodeChunk]:
        """解析 manifest.json / packages-lock.json，提取依赖包列表"""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                data = json.load(f)
        except Exception:
            return None

        rel_path = self._get_relative_path(file_path, game_name)

        deps = data.get('dependencies', {})
        if not deps:
            return None

        dep_lines = [f"// 游戏 {game_name} 的 Unity 包依赖:"]
        dep_lines.append(f"// 文件: {file_path.name}")
        dep_lines.append(f"// 路径: {rel_path}")
        dep_lines.append("// 已安装包:")
        for pkg, ver in sorted(deps.items()):
            dep_lines.append(f"//   {pkg}@{ver}")

        text = '\n'.join(dep_lines)

        chunk_id = f"{game_name}/packages/{file_path.stem}_{hash(str(file_path)) & 0xFFFF:04x}/chunk_0"

        return CodeChunk(
            id=chunk_id,
            text=text,
            metadata={
                'game_name': game_name,
                'file_path': rel_path,
                'file_name': file_path.name,
                'class_name': '',
                'method_name': '',
                'code_type': 'packages',
                'asset_type': '包依赖',
                'asset_name': file_path.stem,
            },
            doc_id=f"{game_name}/{rel_path}",
            chunk_index=0,
        )

    def process_asset_file(self, file_path: Path, game_name: str) -> Optional[CodeChunk]:
        """
        处理资产文件，按类型分发
        """
        ext = file_path.suffix.lower()
        if ext == '.unity':
            return self._process_scene_file(file_path, game_name)
        elif ext == '.mat':
            return self._process_material_file(file_path, game_name)
        return self._process_general_asset(file_path, game_name)

    def _process_scene_file(self, file_path: Path, game_name: str) -> Optional[CodeChunk]:
        """解析 .unity 场景文件，提取 GameObject 名 + 组件"""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except Exception:
            return None

        rel_path = self._get_relative_path(file_path, game_name)

        # 提取所有 GameObject 名称
        game_objects = []
        for m in re.finditer(r'm_Name:\s+(.+)', content):
            name = m.group(1).strip()
            if name and name not in game_objects:
                game_objects.append(name)

        # 提取组件类型（从 YAML 类标签）
        component_types = set()
        for m in re.finditer(r'---\s*!u!\d+\s*&\d+\s*\n(\w[\w.]*):',
                             content, re.MULTILINE):
            ctype = m.group(1).strip()
            if ctype and ctype not in ('GameObject', 'Transform', 'RectTransform', 'MonoBehaviour'):
                component_types.add(ctype)

        # 限制输出长度
        obj_list = game_objects[:80]
        comp_list = sorted(component_types)[:30]

        text = (
            f"// 游戏: {game_name}\n"
            f"// 类型: 场景文件\n"
            f"// 文件: {file_path.name}\n"
            f"// 路径: {rel_path}\n"
            f"// 物体列表: {', '.join(obj_list)}\n"
            f"// 组件类型: {', '.join(comp_list)}\n"
        )

        chunk_id = f"{game_name}/scene/{file_path.stem}_{hash(str(file_path)) & 0xFFFF:04x}/chunk_0"

        return CodeChunk(
            id=chunk_id,
            text=text,
            metadata={
                'game_name': game_name,
                'file_path': rel_path,
                'file_name': file_path.name,
                'class_name': '',
                'method_name': '',
                'code_type': 'scene',
                'asset_type': '场景文件',
                'asset_name': file_path.stem,
            },
            doc_id=f"{game_name}/{rel_path}",
            chunk_index=0,
        )

    def _process_material_file(self, file_path: Path, game_name: str) -> Optional[CodeChunk]:
        """解析 .mat 材质文件"""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read(4096)  # 只读前 4KB
        except Exception:
            return None

        rel_path = self._get_relative_path(file_path, game_name)

        # 提取 Shader 名
        shader_match = re.search(r'm_Shader:\s*\{fileID:\s*\d+,\s*guid:\s*[^,]+,.*?\}', content)
        shader = "unknown"
        if shader_match:
            shader = shader_match.group(0)[:80]

        # 提取纹理引用
        textures = set()
        for m in re.finditer(r'm_Texture:\s*\{fileID:\s*\d+\}', content):
            textures.add(m.group(0))
        tex_list = list(textures)[:10]

        text = (
            f"// 游戏: {game_name}\n"
            f"// 类型: 材质文件\n"
            f"// 文件: {file_path.name}\n"
            f"// 路径: {rel_path}\n"
            f"// 名称: {file_path.stem}\n"
            f"// Shader: {shader}\n"
            f"// 纹理引用: {', '.join(tex_list)}\n"
        )

        chunk_id = f"{game_name}/mat/{file_path.stem}_{hash(str(file_path)) & 0xFFFF:04x}/chunk_0"

        return CodeChunk(
            id=chunk_id,
            text=text,
            metadata={
                'game_name': game_name,
                'file_path': rel_path,
                'file_name': file_path.name,
                'class_name': '',
                'method_name': '',
                'code_type': 'material',
                'asset_type': '材质文件',
                'asset_name': file_path.stem,
            },
            doc_id=f"{game_name}/{rel_path}",
            chunk_index=0,
        )

    def _process_general_asset(self, file_path: Path, game_name: str) -> Optional[CodeChunk]:
        """处理通用资产文件（图片、预制体等）"""
        rel_path = self._get_relative_path(file_path, game_name)
        ext = file_path.suffix.lower()
        name = file_path.stem

        type_map = {'.png': '图片/精灵', '.jpg': '图片', '.jpeg': '图片',
                    '.prefab': '预制体', '.controller': '动画控制器',
                    '.anim': '动画片段', '.asset': '资源文件'}
        asset_type = type_map.get(ext, '资源')

        # 从路径中提取关键词
        skip_dirs = {'Assets', 'Scripts', 'Resources', 'Sprites', 'Images', 'Textures', 'Prefabs', 'Animations'}
        path_parts = [p for p in file_path.parts if p not in skip_dirs]
        path_keywords = ' '.join(p.replace('.meta', '').replace('.cs', '') for p in path_parts if p)

        text = (
            f"// 游戏: {game_name}\n"
            f"// 类型: {asset_type}\n"
            f"// 文件名: {file_path.name}\n"
            f"// 路径: {rel_path}\n"
            f"// 目录关键词: {path_keywords}\n"
            f"// 名称: {name}\n"
        )

        chunk_id = f"{game_name}/asset/{name}_{hash(str(file_path)) & 0xFFFF:04x}/chunk_0"

        return CodeChunk(
            id=chunk_id,
            text=text,
            metadata={
                'game_name': game_name,
                'file_path': rel_path,
                'file_name': file_path.name,
                'class_name': '',
                'method_name': '',
                'code_type': 'asset',
                'asset_type': asset_type,
                'asset_name': name,
            },
            doc_id=f"{game_name}/{rel_path}",
            chunk_index=0,
        )

    def _read_file_lines(self, file_path: Path) -> Optional[List[str]]:
        """读取文件所有行"""
        try:
            if file_path.stat().st_size > self.max_file_size:
                logger.warning(f"文件过大，跳过: {file_path} ({file_path.stat().st_size} bytes)")
                return None

            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                return f.readlines()
        except Exception as e:
            logger.warning(f"读取文件失败: {file_path}, 错误: {e}")
            return None

    def _match_brace(self, lines: List[str], open_line_idx: int) -> int:
        """
        大括号匹配：从 open_line_idx 行开始（该行包含 {），找到匹配的 } 所在行

        Args:
            lines: 所有行
            open_line_idx: 开始行（该行可能包含 {）

        Returns:
            匹配的 } 所在行索引
        """
        depth = 0
        started = False        # 是否已经开始计数（找到第一个 {）

        for i in range(open_line_idx, len(lines)):
            line = lines[i]
            for j, ch in enumerate(line):
                if ch == '{':
                    depth += 1
                    started = True
                elif ch == '}':
                    depth -= 1
                    if depth == 0 and started:
                        return i
        return len(lines) - 1

    def _find_body_start(self, lines: List[str], start_line: int) -> int:
        """从 start_line 开始向后查找第一个包含 { 的行"""
        for i in range(start_line, min(start_line + 5, len(lines))):
            if '{' in lines[i]:
                return i
        return start_line

    def _extract_classes(self, lines: List[str]) -> List[ClassInfo]:
        """提取所有类/结构体/枚举信息"""
        classes = []
        full_text = ''.join(lines)
        # 移除注释后再匹配，避免匹配到注释中的声明
        text_no_comment = self.COMMENT_PATTERN.sub(' ', full_text)

        for match in self.CLASS_PATTERN.finditer(text_no_comment):
            name = match.group('name')
            code_type = match.group('type')
            modifiers = match.group('modifiers').strip()

            # 计算行号（从字符偏移量）
            pos = match.start()
            line_idx = full_text[:pos].count('\n')

            # 查找大括号范围
            body_start = self._find_body_start(lines, line_idx)
            body_end = self._match_brace(lines, body_start)

            class_info = ClassInfo(
                name=name,
                code_type=code_type,
                start_line=line_idx,
                end_line=body_end,
                body_start=body_start,
                body_end=body_end,
                modifiers=modifiers,
            )
            classes.append(class_info)

        return classes

    def _extract_methods(self, lines: List[str], class_info: ClassInfo) -> List[MethodInfo]:
        """在类范围内提取方法"""
        methods = []
        class_text = ''.join(lines[class_info.body_start:class_info.body_end + 1])

        for match in self.METHOD_PATTERN.finditer(class_text):
            name = match.group('name')
            return_type = match.group('return_type').strip()
            modifiers = match.group('modifiers').strip()

            # 跳过一些非方法关键字
            if name in ('if', 'while', 'for', 'foreach', 'switch', 'catch', 'using',
                         'get', 'set', 'add', 'remove', 'class', 'struct', 'enum',
                         'new', 'return', 'throw', 'case', 'default', 'typeof', 'sizeof',
                         'nameof', 'var', 'in', 'out', 'ref', 'where', 'select',
                         'from', 'group', 'into', 'orderby', 'join', 'let', 'on',
                         'equals', 'lock', 'fixed', 'checked', 'unchecked'):
                continue

            if return_type in ('class', 'struct', 'enum', 'if', 'while', 'for'):
                continue

            pos_in_class = match.start()
            # 计算在 lines 中的实际行号
            line_idx = class_info.body_start + class_text[:pos_in_class].count('\n')

            # 找到方法体的大括号范围
            body_start = self._find_body_start(lines, line_idx)
            if body_start > class_info.body_end:
                continue

            body_end = self._match_brace(lines, body_start)
            if body_end > class_info.body_end:
                body_end = class_info.body_end

            method_info = MethodInfo(
                name=name,
                return_type=return_type,
                start_line=line_idx,
                end_line=body_end,
                body_start=body_start,
                body_end=body_end,
                modifiers=modifiers,
                is_static='static' in modifiers,
                is_coroutine='IEnumerator' in return_type,
            )
            methods.append(method_info)

        return methods

    def _extract_usings(self, lines: List[str]) -> str:
        """提取 using 语句"""
        usings = []
        for line in lines:
            if line.strip().startswith('using '):
                usings.append(line.rstrip())
            elif usings and line.strip() and not line.strip().startswith('using '):
                break
        return '\n'.join(usings)

    def _extract_properties_and_fields(self, lines: List[str], class_info: ClassInfo) -> Tuple[List[str], List[str]]:
        """提取类内的属性和字段声明"""
        fields = []
        properties = []

        for i in range(class_info.body_start + 1, class_info.body_end):
            line = lines[i].strip()

            # 跳过空行、注释、方法内的代码
            if not line or line.startswith('//') or line.startswith('['):
                continue

            # 检查是否是属性（包含 get/set）
            if '{' in line and ('get' in line or 'set' in line):
                if line.startswith('public ') or line.startswith('private ') or line.startswith('protected '):
                    properties.append(lines[i].rstrip())
            # 检查是否是字段
            elif '=' in line or line.endswith(';'):
                if any(line.startswith(prefix) for prefix in
                       ['public ', 'private ', 'protected ', 'internal ',
                        '[SerializeField]', 'static ', 'readonly ', 'const ']):
                    # 排除方法调用（包含括号）
                    if '(' not in line or line.endswith(';'):
                        fields.append(lines[i].rstrip())

        return properties, fields

    def _extract_method_code(self, lines: List[str], method_info: MethodInfo) -> str:
        """提取方法的完整代码（含签名和注释上方的注释）"""
        # 先向上查找注释（XML文档注释或普通注释）
        comment_start = method_info.start_line
        for i in range(method_info.start_line - 1, max(method_info.start_line - 10, 0), -1):
            stripped = lines[i].strip()
            if stripped.startswith('///') or stripped.startswith('//') or stripped.startswith('/*'):
                comment_start = i
            elif stripped.startswith('['):
                # [SerializeField] 等属性注解
                comment_start = i
            elif stripped == '':
                continue
            else:
                break

        code = ''.join(lines[comment_start:method_info.end_line + 1])
        return code.strip()

    def _create_chunk_id(self, game_name: str, class_name: str,
                         method_name: str = None, chunk_index: int = 0,
                         file_path: Path = None) -> str:
        """生成唯一的分块 ID"""
        # 用文件路径的短哈希区分同名类
        suffix = ""
        if file_path:
            suffix = f"_{hash(str(file_path)) & 0xFFFF:04x}"
        if method_name:
            return f"{game_name}/{class_name}{suffix}/{method_name}/chunk_{chunk_index}"
        return f"{game_name}/{class_name}{suffix}/overview/chunk_{chunk_index}"

    def process_file(self, file_path: Path, game_name: str) -> Generator[CodeChunk, None, None]:
        """
        处理单个 .cs 文件，生成分块

        Args:
            file_path: .cs 文件路径
            game_name: 游戏名称

        Yields:
            CodeChunk 对象
        """
        lines = self._read_file_lines(file_path)
        if not lines:
            return

        full_text = ''.join(lines)

        # 提取 using 语句
        usings = self._extract_usings(lines)

        # 提取类信息
        classes = self._extract_classes(lines)
        if not classes:
            # 尝试宽松匹配（可能包含嵌套类或被注释影响）
            logger.debug(f"未找到类声明: {file_path.name}，将整个文件作为一个块")
            # 整个文件作为一个块
            rel_path = self._get_relative_path(file_path, game_name)
            chunk_id = f"{game_name}/{file_path.stem}_{hash(str(file_path)) & 0xFFFF:04x}/file/chunk_0"
            yield CodeChunk(
                id=chunk_id,
                text=full_text.strip(),
                metadata={
                    'game_name': game_name,
                    'file_path': rel_path,
                    'file_name': file_path.name,
                    'class_name': file_path.stem,
                    'method_name': '',
                    'code_type': 'full_file',
                },
                doc_id=f"{game_name}/{rel_path}",
                chunk_index=0,
            )
            return

        # 为每个类生成块
        for cls in classes:
            rel_path = self._get_relative_path(file_path, game_name)

            # 1. 类概览块
            props, fields = self._extract_properties_and_fields(lines, cls)

            overview_text = self._build_overview_text(
                usings=usings,
                cls=cls,
                lines=lines,
                props=props,
                fields=fields,
            )

            overview_chunk_id = self._create_chunk_id(game_name, cls.name, chunk_index=0, file_path=file_path)
            yield CodeChunk(
                id=overview_chunk_id,
                text=overview_text,
                metadata={
                    'game_name': game_name,
                    'file_path': rel_path,
                    'file_name': file_path.name,
                    'class_name': cls.name,
                    'method_name': '',
                    'code_type': f'{cls.code_type}_overview',
                    'modifiers': cls.modifiers,
                    'line_start': str(cls.start_line + 1),
                    'line_end': str(cls.end_line + 1),
                },
                doc_id=f"{game_name}/{rel_path}",
                chunk_index=0,
            )

            # 2. 方法详细块
            methods = self._extract_methods(lines, cls)
            for idx, method in enumerate(methods):
                method_code = self._extract_method_code(lines, method)
                # 增强：添加类名前缀
                enhanced_text = (
                    f"// Class: {cls.name} (in {game_name})\n"
                    f"// File: {rel_path}\n"
                    f"// Method: {method.return_type} {method.name}()"
                    f"{' [static]' if method.is_static else ''}"
                    f"{' [coroutine]' if method.is_coroutine else ''}\n\n"
                    f"{method_code}"
                )

                method_chunk_id = self._create_chunk_id(
                    game_name, cls.name, method.name, chunk_index=idx, file_path=file_path
                )
                yield CodeChunk(
                    id=method_chunk_id,
                    text=enhanced_text,
                    metadata={
                        'game_name': game_name,
                        'file_path': rel_path,
                        'file_name': file_path.name,
                        'class_name': cls.name,
                        'method_name': method.name,
                        'code_type': 'method_detail',
                        'return_type': method.return_type,
                        'modifiers': method.modifiers,
                        'is_static': str(method.is_static),
                        'is_coroutine': str(method.is_coroutine),
                        'line_start': str(method.start_line + 1),
                        'line_end': str(method.end_line + 1),
                    },
                    doc_id=f"{game_name}/{rel_path}",
                    chunk_index=idx + 1,
                )

    def _build_overview_text(self, usings: str, cls: ClassInfo, lines: List[str],
                              props: List[str], fields: List[str]) -> str:
        """构建类概览文本"""
        parts = []

        if usings:
            parts.append(f"{usings}\n")

        # 类声明头
        class_header = ''.join(lines[cls.start_line:cls.body_start + 1]).rstrip()
        parts.append(f"class {cls.name} overview:\n")
        parts.append(f"{class_header}")

        # 只添加字段和属性声明，不添加方法体
        if fields or props:
            parts.append("")
            parts.append("// --- Fields & Properties ---")
            for f in fields:
                parts.append(f"  {f}")
            for p in props:
                parts.append(f"  {p}")

        return '\n'.join(parts).strip()

    def _get_relative_path(self, file_path: Path, game_name: str) -> str:
        """获取文件在游戏目录下的相对路径"""
        try:
            return str(file_path.relative_to(self.source_root)).replace('\\', '/')
        except ValueError:
            return f"{game_name}/{file_path.name}"

    def get_game_name(self, game_dir: Path) -> str:
        """从目录路径提取游戏名称"""
        return game_dir.name

    def process_all(self) -> Generator[CodeChunk, None, None]:
        """
        处理所有游戏源码，生成所有分块

        Yields:
            CodeChunk 对象
        """
        games = self.scan_game_dirs()
        if not games:
            logger.warning("未找到任何游戏项目")
            return

        for game_dir in games:
            game_name = self.get_game_name(game_dir)
            logger.info(f"处理游戏: {game_name}")

            cs_files = self.find_cs_files(game_dir)
            logger.info(f"  找到 {len(cs_files)} 个 .cs 文件")

            for cs_file in cs_files:
                try:
                    yield from self.process_file(cs_file, game_name)
                except Exception as e:
                    logger.warning(f"处理文件失败: {cs_file}, 错误: {e}")
                    continue

        logger.info("所有游戏源码处理完成")


def create_processor(source_root: str, config: Optional[dict] = None) -> CodeProcessor:
    """创建代码处理器的工厂函数"""
    return CodeProcessor(source_root, config)

"""代码解析器 — 解析 C# / Shader 文件，提取结构化信息"""

import re
from pathlib import Path
from typing import List, Dict, Any, Optional


class CSharpParser:
    """C# 文件解析器"""
    
    # 常见 Unity 组件类型映射
    COMPONENT_TYPES = {
        'MonoBehaviour', 'Component', 'GameObject', 'Transform',
        'Rigidbody', 'Rigidbody2D', 'Collider', 'Collider2D',
        'Renderer', 'MeshRenderer', 'SpriteRenderer',
        'AudioSource', 'Camera', 'Light', 'Animator',
        'Canvas', 'Image', 'Text', 'Button',
        'ScriptableObject', 'Editor', 'EditorWindow',
        'StateMachineBehaviour', 'NetworkBehaviour',
    }
    
    def __init__(self, file_path: str):
        self.file_path = Path(file_path)
        self.content = self.file_path.read_text(encoding='utf-8', errors='replace')
        self.lines = self.content.split('\n')
    
    def parse(self) -> Dict[str, Any]:
        """解析 C# 文件"""
        return {
            "type": "csharp",
            "file_name": self.file_path.name,
            "project_name": self._extract_project_name(),
            "namespace": self._extract_namespace(),
            "classes": self._extract_classes(),
            "interfaces": self._extract_interfaces(),
            "enums": self._extract_enums(),
            "using_statements": self._extract_usings(),
            "summary": self._extract_summary(),
        }
    
    def _extract_project_name(self) -> str:
        """从路径提取项目名"""
        parts = self.file_path.parts
        # 查找 Assets 目录之前的路径作为项目名
        for i, part in enumerate(parts):
            if part == 'Assets':
                return parts[i-1] if i > 0 else ""
        return parts[-3] if len(parts) > 3 else ""
    
    def _extract_namespace(self) -> str:
        """提取命名空间"""
        match = re.search(r'namespace\s+([\w.]+)', self.content)
        return match.group(1) if match else ""
    
    def _extract_usings(self) -> List[str]:
        """提取 using 语句"""
        usings = re.findall(r'using\s+([\w.]+)\s*;', self.content)
        return usings
    
    def _extract_classes(self) -> List[Dict[str, Any]]:
        """提取类定义"""
        classes = []
        # 匹配类声明
        pattern = r'(?:public|internal|private|protected)?\s*(?:sealed|abstract|static|partial)?\s*class\s+(\w+)(?:\s*:\s*([^{]+?))?\s*\{'
        for match in re.finditer(pattern, self.content):
            name = match.group(1)
            inherits = match.group(2).strip() if match.group(2) else ""
            # 清理继承列表
            inherits = re.sub(r'\s+', ' ', inherits)
            
            classes.append({
                "name": name,
                "inherits": inherits,
                "is_unity_component": any(c in inherits for c in self.COMPONENT_TYPES),
                "methods": self._extract_class_methods(match.start()),
                "fields": self._extract_class_fields(match.start()),
            })
        return classes
    
    def _extract_interfaces(self) -> List[str]:
        """提取接口定义"""
        return re.findall(r'(?:public|internal)?\s*interface\s+(\w+)', self.content)
    
    def _extract_enums(self) -> List[str]:
        """提取枚举定义"""
        return re.findall(r'(?:public|internal)?\s*enum\s+(\w+)', self.content)
    
    def _extract_class_methods(self, start_pos: int) -> List[Dict[str, str]]:
        """提取类中的方法"""
        # 获取类开始后的部分
        text = self.content[start_pos:start_pos + 5000]  # 限制搜索范围
        methods = []
        # 匹配方法声明
        pattern = r'(?:public|private|protected|internal)\s+(?:static\s+|virtual\s+|override\s+|abstract\s+|async\s+)*(?:\w+(?:<[^>]+>)?(?:\[\])?\s+)(\w+)\s*\(([^)]*)\)'
        for match in re.finditer(pattern, text):
            name = match.group(1)
            params = match.group(2).strip()
            if name not in ('class', 'struct', 'interface', 'enum', 'get', 'set', 'if', 'for', 'while', 'switch', 'catch', 'using'):
                methods.append({"name": name, "parameters": params})
        return methods[:50]  # 限制方法数
    
    def _extract_class_fields(self, start_pos: int) -> List[Dict[str, str]]:
        """提取类中的字段"""
        text = self.content[start_pos:start_pos + 3000]
        fields = []
        pattern = r'(?:public|private|protected|internal)\s+(?:static\s+|readonly\s+|const\s+)*(?:\w+(?:<[^>]+>)?(?:\[\])?\s+)(\w+)\s*[=;]'
        for match in re.finditer(pattern, text):
            name = match.group(1)
            if name not in ('class', 'void', 'int', 'float', 'string', 'bool', 'var', 'new', 'return', 'if', 'for', 'while'):
                fields.append({"name": name})
        return fields[:30]
    
    def _extract_summary(self) -> str:
        """提取文件摘要（XML 注释或文件头注释）"""
        # XML 注释
        match = re.search(r'///\s*<summary>\s*(.*?)\s*///\s*</summary>', self.content, re.DOTALL)
        if match:
            summary = re.sub(r'///\s*', '', match.group(1)).strip()
            return summary[:500]
        
        # 多行注释
        match = re.search(r'/\*\s*(.*?)\s*\*/', self.content, re.DOTALL)
        if match:
            return match.group(1).strip()[:500]
        
        return ""


class ShaderParser:
    """Shader 文件解析器"""
    
    def __init__(self, file_path: str):
        self.file_path = Path(file_path)
        self.content = self.file_path.read_text(encoding='utf-8', errors='replace')
    
    def parse(self) -> Dict[str, Any]:
        """解析 Shader 文件"""
        return {
            "type": "shader",
            "file_name": self.file_path.name,
            "project_name": self._extract_project_name(),
            "shader_name": self._extract_shader_name(),
            "properties": self._extract_properties(),
            "sub_shaders": self._extract_sub_shaders(),
            "fallback": self._extract_fallback(),
        }
    
    def _extract_project_name(self) -> str:
        parts = self.file_path.parts
        for i, part in enumerate(parts):
            if part == 'Assets':
                return parts[i-1] if i > 0 else ""
        return ""
    
    def _extract_shader_name(self) -> str:
        match = re.search(r'Shader\s+"([^"]+)"', self.content)
        return match.group(1) if match else ""
    
    def _extract_properties(self) -> List[Dict[str, str]]:
        """提取 Shader 属性"""
        props = []
        match = re.search(r'Properties\s*\{([^}]*(?:\{[^}]*\}[^}]*)*)\}', self.content)
        if match:
            prop_text = match.group(1)
            for line in prop_text.split('\n'):
                line = line.strip()
                if line and not line.startswith('//') and '(' in line:
                    props.append({"raw": line.strip()})
        return props
    
    def _extract_sub_shaders(self) -> int:
        """统计 SubShader 数量"""
        return len(re.findall(r'SubShader\s*\{', self.content))
    
    def _extract_fallback(self) -> str:
        match = re.search(r'Fallback\s+"([^"]*)"', self.content)
        return match.group(1) if match else ""


def parse_code_file(file_path: str) -> Optional[Dict[str, Any]]:
    """解析代码文件（自动判断类型）"""
    path = Path(file_path)
    ext = path.suffix.lower()
    
    if ext == '.cs':
        try:
            return CSharpParser(file_path).parse()
        except Exception:
            return None
    elif ext in ('.shader', '.cginc', '.hlsl'):
        try:
            return ShaderParser(file_path).parse()
        except Exception:
            return None
    return None


def find_code_files(root_dir: str) -> Dict[str, List[Path]]:
    """查找所有代码文件"""
    root = Path(root_dir)
    files = {'cs': [], 'shader': []}
    
    for f in root.rglob('*.cs'):
        # 排除 Editor 和插件目录
        rel = str(f.relative_to(root))
        if not any(x in rel for x in ['Editor', 'Plugins', 'ThirdParty', 'node_modules', 'Library']):
            files['cs'].append(f)
    
    for f in root.rglob('*.shader'):
        files['shader'].append(f)
    
    return files

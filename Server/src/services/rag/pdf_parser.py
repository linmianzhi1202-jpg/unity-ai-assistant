"""
Unity Script Reference PDF 解析器 V3
支持类级别和方法级别 PDF，增强代码示例和参数提取
使用 pdfplumber 字体信息区分代码块
"""

import json
import re
from pathlib import Path
from typing import List, Dict, Any, Optional
import pdfplumber


# HTML 反馈表单噪声模式（用于清理文本）
NOISE_PATTERNS = [
    r'Leave feedback',
    r'Suggest a change',
    r'Success!',
    r'Thank you for helping us improve.*?Close',
    r'Submission failed.*?Close',
    r'Your name\s+Your email\s+Suggestion\*',
    r'Submit suggestion',
    r'Cancel',
    r'Switch to Manual',
    r'Did you find this page useful\?',
    r'Give feedback',
    r'Is something described here not working.*?Known Issue.*?$',
    r'For some reason your suggested change.*?Close',
    r'Please\s*<a>try again</a>.*?Close',
    r'Copyright.*?Unity Technologies',
]


def clean_text(text: str) -> str:
    """清理文本中的 HTML 表单噪声"""
    for pattern in NOISE_PATTERNS:
        text = re.sub(pattern, '', text, flags=re.DOTALL)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


class UnityAPIParser:
    """Unity Script Reference PDF 解析器（V3）"""
    
    def __init__(self, pdf_path: str):
        self.pdf_path = Path(pdf_path)
        self.raw_name = self._extract_raw_name()
        self.is_method_page = "." in self.raw_name
        self.class_name = self.raw_name.split(".")[0] if self.is_method_page else self.raw_name
        self.method_name = self.raw_name.split(".", 1)[1] if self.is_method_page else None
        
    def _extract_raw_name(self) -> str:
        """从文件名提取 API 名称"""
        filename = self.pdf_path.name
        match = re.search(r'ScriptReference_(.+)\.pdf$', filename)
        if match:
            return match.group(1)
        return self.pdf_path.stem
        
    def parse(self) -> Dict[str, Any]:
        """解析 PDF，提取结构化数据"""
        with pdfplumber.open(self.pdf_path) as pdf:
            # 提取原始文本（不清理，用于提取声明等结构化信息）
            raw_text = ""
            code_blocks = []
            
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    raw_text += text + "\n"
                
                # 使用字符级字体信息提取代码块
                chars = page.chars
                if chars:
                    code_blocks.extend(self._extract_code_blocks_by_font(chars, page))
            
            # 提取表格
            all_tables = []
            for page in pdf.pages:
                tables = page.extract_tables()
                if tables:
                    all_tables.extend(tables)
            
            # 先从原始文本提取声明（避免 clean_text 破坏 C# 语法）
            raw_declarations = self._extract_declarations(raw_text) if self.is_method_page else []
            
            # 清理文本（用于描述等）
            clean = clean_text(raw_text)
            
            if self.is_method_page:
                return self._parse_method_page(clean, all_tables, code_blocks, raw_declarations)
            else:
                return self._parse_class_page(clean, all_tables, code_blocks)
    
    def _extract_code_blocks_by_font(self, chars: List, page) -> List[str]:
        """通过字体大小和名称识别代码块"""
        if not chars:
            return []
        
        # Unity 文档中代码使用等宽字体（如 Courier）
        code_lines = []
        current_line = []
        current_y = None
        
        for ch in chars:
            fontname = ch.get('fontname', '')
            size = ch.get('size', 0)
            
            # 代码字体特征：等宽字体或特定字体名
            is_code_font = any(x in fontname.lower() for x in ['courier', 'mono', 'consolas', 'code'])
            # Unity PDF 代码通常用较小字体
            is_small_font = size < 9.5 and size > 7
            
            y = round(ch['top'], 0)
            
            if y != current_y:
                if current_line:
                    line_text = ''.join(current_line).strip()
                    if line_text:
                        code_lines.append((current_y, line_text, is_code_font or is_small_font))
                    current_line = []
                current_y = y
            
            current_line.append(ch['text'])
        
        # 最后一行
        if current_line:
            line_text = ''.join(current_line).strip()
            if line_text:
                code_lines.append((current_y, line_text, True))
        
        # 收集连续的代码行
        code_blocks = []
        block = []
        in_block = False
        
        for y, text, is_code in code_lines:
            if is_code:
                # 代码行特征检测
                is_csharp = bool(re.match(
                    r'^(using\s|namespace\s|public\s|private\s|protected\s|internal\s|'
                    r'static\s|virtual\s|override\s|abstract\s|sealed\s|'
                    r'void\s|int\s|float\s|string\s|bool\s|var\s|new\s|return\s|'
                    r'if\s*\(|for\s*\(|while\s*\(|foreach\s*\(|switch\s*\(|'
                    r'class\s|struct\s|interface\s|enum\s|'
                    r'//|/\*|\*/|\{|\}|GameObject|Transform|Vector3|MonoBehaviour|'
                    r'GetComponent|AddComponent|Debug\.|transform\.|gameObject\.)',
                    text
                ))
                
                if is_csharp or in_block:
                    block.append(text)
                    in_block = True
                else:
                    if block:
                        code_blocks.append('\n'.join(block))
                        block = []
                    in_block = False
            else:
                if in_block and block:
                    # 普通文本行可能只是代码中的注释间隔
                    if len(text) < 20:
                        block.append(text)
                    else:
                        code_blocks.append('\n'.join(block))
                        block = []
                        in_block = False
        
        if block:
            code_blocks.append('\n'.join(block))
        
        return code_blocks
    
    def _parse_class_page(self, text: str, tables: List, code_blocks: List[str]) -> Dict[str, Any]:
        """解析类级别 PDF"""
        data = {
            "type": "class",
            "class_name": self.class_name,
            "namespace": self._extract_section(text, r'Namespace:\s*(\S+)'),
            "description": self._extract_class_description(text),
            "inherits_from": self._extract_section(text, r'Inherits\s*from:\s*(\S+)'),
            "properties": self._extract_from_tables(tables, "Property"),
            "methods": self._extract_from_tables(tables, "Method"),
            "constructors": self._extract_from_tables(tables, "Constructor"),
            "operators": self._extract_from_tables(tables, "Operator"),
            "messages": self._extract_from_tables(tables, "Message"),
            "code_examples": code_blocks[:10] if code_blocks else self._extract_code_from_text(text),
        }
        # 保留关键字段，移除空列表
        return {k: v for k, v in data.items() if v or k in ("type", "class_name", "description")}
        
    def _parse_method_page(self, text: str, tables: List, code_blocks: List[str], raw_declarations: List[str] = None) -> Dict[str, Any]:
        """解析方法级别 PDF"""
        declarations = raw_declarations or self._extract_declarations(text)
        descriptions = self._extract_method_descriptions(text)
        parameters = self._extract_parameters(text, tables)
        returns = self._extract_returns(text)
        
        data = {
            "type": "method",
            "class_name": self.class_name,
            "method_name": self.method_name,
            "full_name": self.raw_name,
            "declarations": declarations,
            "descriptions": descriptions,
            "parameters": parameters,
            "returns": returns,
            "code_examples": code_blocks[:10] if code_blocks else self._extract_code_from_text(text),
        }
        return {k: v for k, v in data.items() if v or k in ("type", "class_name", "method_name", "full_name")}
    
    def _extract_section(self, text: str, pattern: str) -> str:
        """提取文本中的特定部分"""
        match = re.search(pattern, text)
        return match.group(1) if match else ""
    
    def _extract_class_description(self, text: str) -> str:
        """提取类描述"""
        # 模式1：Description 标签之后
        patterns = [
            r'Description\s+(.*?)(?=\s+Properties|\s+Public\s*Methods|\s+Inherited\s*Members|\s+Static\s*Methods|\s+Messages|\s+Constructors)',
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                desc = match.group(1).strip()
                if len(desc) > 20:
                    return desc
        
        # 后备
        pattern2 = rf'{re.escape(self.class_name)}\s+(.*?)(?=Properties|Public\s*Methods|Inherited|Messages)'
        match2 = re.search(pattern2, text, re.DOTALL)
        if match2:
            return match2.group(1).strip()
        return ""
    
    def _extract_declarations(self, text: str) -> List[str]:
        """提取方法声明（支持多个重载）— 在原始文本上操作"""
        escaped_name = re.escape(self.method_name or "")
        # 简化正则：匹配 public ... MethodName(...) 形式
        declarations = []
        # 模式1: public [static] [override] Type MethodName(params)
        pattern = rf'(public\s+(?:static\s+)?(?:override\s+)?(?:virtual\s+)?(?:sealed\s+)?(?:extern\s+)?(?:unsafe\s+)?(?:async\s+)?\w+(?:<[^>]+>)?(?:\[\])?\s+{escaped_name}\s*(?:<[^>]+>)?\s*\([^)]*\))'
        for match in re.finditer(pattern, text):
            decl = match.group(1).strip().rstrip(';')
            if decl not in declarations:
                declarations.append(decl)
        # 模式2: public T MethodName() (泛型方法)
        if not declarations:
            pattern2 = rf'(public\s+(?:static\s+)?\w+\s+{escaped_name}\s*\([^)]*\))'
            for match in re.finditer(pattern2, text):
                decl = match.group(1).strip().rstrip(';')
                if decl not in declarations:
                    declarations.append(decl)
        return declarations
    
    def _extract_method_descriptions(self, text: str) -> List[str]:
        """提取方法描述（每个重载一个）"""
        descriptions = []
        # 按 Declaration 分割文本
        parts = re.split(r'Declaration', text)
        for part in parts[1:]:  # 跳过第一部分（Declaration之前的内容）
            # Description 之后的文本，到下一个 Declaration 或 Parameters 或 Returns
            match = re.search(r'Description\s+(.*?)(?=Declaration|Parameters|Returns|Examples|Did you find|Is something)', part, re.DOTALL)
            if match:
                desc = match.group(1).strip()
                if len(desc) > 10:
                    descriptions.append(desc)
        
        if not descriptions:
            # 后备：整体描述
            match = re.search(r'Description\s+(.*?)(?=Declaration|Parameters|Returns|Examples)', text, re.DOTALL)
            if match:
                descriptions.append(match.group(1).strip())
        
        return descriptions
    
    def _extract_parameters(self, text: str, tables: List) -> List[Dict[str, str]]:
        """提取方法参数"""
        params = []
        # 优先从表格提取
        for table in tables:
            if not table or len(table) < 2:
                continue
            header = table[0]
            if header and "Parameter" in str(header) and "Description" in str(header):
                for row in table[1:]:
                    if row and len(row) >= 2:
                        param_name = (row[0] or "").strip()
                        param_desc = (row[1] or "").strip()
                        if param_name and param_name != "Parameter":
                            params.append({"name": param_name, "description": param_desc})
        
        if params:
            return params
        
        # 后备：从文本提取
        match = re.search(r'Parameters\s+(.*?)(?=Returns|Examples|Did you find|Declaration)', text, re.DOTALL)
        if match:
            param_text = match.group(1)
            # 尝试按 "paramName description" 格式解析
            for line in param_text.split('\n'):
                line = line.strip()
                if line and ':' in line:
                    parts = line.split(':', 1)
                    if parts[0].strip() and len(parts[0].strip()) < 30:
                        params.append({"name": parts[0].strip(), "description": parts[1].strip()})
        return params
    
    def _extract_returns(self, text: str) -> str:
        """提取返回值描述"""
        match = re.search(r'Returns\s+(.*?)(?=Examples|Did you find|Is something|Declaration)', text, re.DOTALL)
        if match:
            return match.group(1).strip()
        return ""
    
    def _extract_from_tables(self, tables: List, keyword: str) -> List[Dict[str, str]]:
        """从表格中提取指定类型的数据"""
        results = []
        for table in tables:
            if not table or len(table) < 2:
                continue
            header = table[0]
            if header and keyword in str(header) and "Description" in str(header):
                for row in table[1:]:
                    if row and len(row) >= 2:
                        name = (row[0] or "").strip()
                        desc = (row[1] or "").strip()
                        if name and name != keyword:
                            results.append({"name": name, "description": desc})
        return results
    
    def _extract_code_from_text(self, text: str) -> List[str]:
        """从纯文本提取代码示例（后备方案）"""
        examples = []
        lines = text.split('\n')
        
        in_code = False
        block = []
        brace_depth = 0
        
        for line in lines:
            stripped = line.strip()
            is_csharp_line = bool(re.match(
                r'^(using\s|namespace\s|public\s+class\s|public\s+void\s|public\s+static\s|'
                r'private\s+void\s|protected\s+void\s|IEnumerator\s|void\s+Start|void\s+Update|'
                r'void\s+Awake|void\s+On|class\s+\w+|struct\s+\w+|'
                r'if\s*\(|for\s*\(|while\s*\(|foreach\s*\(|switch\s*\(|'
                r'var\s|int\s|float\s|string\s|bool\s|return\s|new\s|'
                r'GetComponent|AddComponent|Debug\.|transform\.|gameObject\.)',
                stripped
            ))
            
            if is_csharp_line:
                in_code = True
                brace_depth += stripped.count('{') - stripped.count('}')
                block.append(stripped)
            elif in_code:
                if stripped:
                    brace_depth += stripped.count('{') - stripped.count('}')
                    block.append(stripped)
                elif brace_depth <= 0:
                    if len(block) >= 3:
                        examples.append('\n'.join(block))
                    block = []
                    in_code = False
                    brace_depth = 0
        
        if block and len(block) >= 3:
            examples.append('\n'.join(block))
        
        return examples[:10]


def convert_pdf_to_json(pdf_path: str, output_dir: str) -> Path:
    """转换单个 PDF 为 JSON"""
    parser = UnityAPIParser(pdf_path)
    data = parser.parse()
    
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    if parser.is_method_page:
        method_dir = output_path / parser.class_name
        method_dir.mkdir(parents=True, exist_ok=True)
        output_file = method_dir / f"{parser.raw_name}.json"
    else:
        output_file = output_path / f"{parser.class_name}.json"
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    return output_file


def find_all_pdfs(pdf_dir: str, include_methods: bool = True) -> List[Path]:
    """查找所有 PDF 文件"""
    pdf_path = Path(pdf_dir)
    pdf_files = []
    
    # 使用 rglob 递归查找所有 PDF
    for pdf_file in pdf_path.rglob("2022.3_Documentation_ScriptReference_*.pdf"):
        name_part = pdf_file.stem.replace("2022.3_Documentation_ScriptReference_", "")
        
        if "." not in name_part:
            # 类级别
            pdf_files.append(pdf_file)
        elif include_methods:
            # 方法级别
            pdf_files.append(pdf_file)
    
    return pdf_files


def batch_convert(pdf_dir: str, output_dir: str, include_methods: bool = True,
                  progress_file: str = None, batch_size: int = 500) -> Dict[str, int]:
    """批量转换 PDF 为 JSON（支持断点续传）"""
    import time
    
    pdf_files = find_all_pdfs(pdf_dir, include_methods)
    
    class_count = sum(1 for f in pdf_files if "." not in f.stem.replace("2022.3_Documentation_ScriptReference_", ""))
    method_count = len(pdf_files) - class_count
    print(f"找到 {len(pdf_files)} 个 PDF（类: {class_count}, 方法: {method_count}）")
    
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # 加载进度
    processed = set()
    if progress_file and Path(progress_file).exists():
        with open(progress_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            processed = set(data.get('processed_files', []))
        print(f"已处理 {len(processed)} 个文件（断点续传）")
    
    remaining = [f for f in pdf_files if str(f) not in processed]
    print(f"剩余 {len(remaining)} 个文件待处理")
    
    if not remaining:
        print("所有文件已处理完成！")
        return {"total": len(pdf_files), "success": 0, "error": 0, "skipped": len(pdf_files)}
    
    success_count = 0
    error_count = 0
    start_time = time.time()
    
    for i, pdf_file in enumerate(remaining, 1):
        name_part = pdf_file.stem.replace("2022.3_Documentation_ScriptReference_", "")
        
        try:
            parser = UnityAPIParser(str(pdf_file))
            data = parser.parse()
            
            # 保存
            if parser.is_method_page:
                method_dir = output_path / parser.class_name
                method_dir.mkdir(parents=True, exist_ok=True)
                output_file = method_dir / f"{parser.raw_name}.json"
            else:
                output_file = output_path / f"{parser.class_name}.json"
            
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            processed.add(str(pdf_file))
            success_count += 1
            
            if i % 500 == 0 or i == len(remaining):
                elapsed = time.time() - start_time
                avg = elapsed / i
                eta = (len(remaining) - i) * avg / 60
                print(f"[{i}/{len(remaining)}] OK:{success_count} ERR:{error_count} ETA:{eta:.1f}min")
            
            if progress_file and i % batch_size == 0:
                with open(progress_file, 'w', encoding='utf-8') as f:
                    json.dump({
                        'processed_files': list(processed),
                        'last_update': time.strftime('%Y-%m-%d %H:%M:%S'),
                        'stats': {'success': success_count, 'error': error_count}
                    }, f)
                    
        except Exception as e:
            error_count += 1
            if error_count <= 20:
                print(f"  [ERROR] {name_part}: {e}")
    
    # 最终保存进度
    if progress_file:
        with open(progress_file, 'w', encoding='utf-8') as f:
            json.dump({
                'processed_files': list(processed),
                'last_update': time.strftime('%Y-%m-%d %H:%M:%S'),
                'stats': {'success': success_count, 'error': error_count}
            }, f)
    
    total_time = time.time() - start_time
    print(f"\n批量转换完成！成功: {success_count}, 失败: {error_count}, 耗时: {total_time/60:.1f}分钟")
    
    return {"total": len(pdf_files), "success": success_count, "error": error_count}


def api_data_to_text(data: Dict[str, Any]) -> str:
    """将 API JSON 数据转换为可索引的文本"""
    parts = []
    api_type = data.get('type', 'class')
    
    if api_type == 'method':
        full_name = data.get('full_name', '')
        if full_name:
            parts.append(f"Method: {full_name}")
        for decl in data.get('declarations', []):
            parts.append(f"Declaration: {decl}")
        for desc in data.get('descriptions', []):
            parts.append(f"Description: {desc}")
        for param in data.get('parameters', []):
            parts.append(f"Parameter {param['name']}: {param.get('description', '')}")
        returns = data.get('returns', '')
        if returns:
            parts.append(f"Returns: {returns}")
    else:
        class_name = data.get('class_name', '')
        namespace = data.get('namespace', '')
        if namespace:
            parts.append(f"Class: {namespace}.{class_name}")
        else:
            parts.append(f"Class: {class_name}")
        desc = data.get('description', '')
        if desc:
            parts.append(f"Description: {desc}")
        inherits = data.get('inherits_from', '')
        if inherits:
            parts.append(f"Inherits from: {inherits}")
        for prop in data.get('properties', []):
            parts.append(f"Property {prop['name']}: {prop.get('description', '')}")
        for method in data.get('methods', []):
            parts.append(f"Method {method['name']}: {method.get('description', '')}")
        for ctor in data.get('constructors', []):
            parts.append(f"Constructor {ctor['name']}: {ctor.get('description', '')}")
        for op in data.get('operators', []):
            parts.append(f"Operator {op['name']}: {op.get('description', '')}")
        for msg in data.get('messages', []):
            parts.append(f"Message {msg['name']}: {msg.get('description', '')}")
    
    for i, example in enumerate(data.get('code_examples', [])[:3]):
        parts.append(f"Example {i+1}: {example[:500]}")
    
    return '\n'.join(parts)

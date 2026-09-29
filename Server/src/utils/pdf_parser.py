"""
Unity Script Reference PDF 解析器
将 Unity 2022.3 Script Reference PDF 转换为结构化 JSON
"""
import json
import pdfplumber
from pathlib import Path
from typing import Dict, List, Any
import re

class UnityAPIParser:
    """解析 Unity Script Reference PDF 文件"""
    
    # 需要过滤的导航/页脚关键词
    NAVIGATION_KEYWORDS = [
        'Search scripting', 'Submit', 'Manual', 'Scripting API', 
        'unity.com', 'Version:', 'Language', 'C#', 'Search manual',
        'Select a different version', 'Leave feedback', 'Suggest a change',
        'Success!', 'Thank you', 'Submission failed', 'try again',
        'Switch to Manual', 'Issue Tracker', 'Copyright', 'Unity Technologies',
        'Publication Date:', 'Tutorials', 'Community', 'Answers', 
        'Knowledge Base', 'Forums', 'Asset Store', 'Terms of use', 
        'Legal', 'Privacy Policy', 'Cookies', 'Do Not Sell'
    ]
    
    def __init__(self, pdf_path: str):
        self.pdf_path = Path(pdf_path)
        self.class_name = self._extract_class_name_from_path()
        
    def _extract_class_name_from_path(self) -> str:
        """从文件路径提取类名"""
        # 路径格式: .../GameObject/2022.3_Documentation_ScriptReference_GameObject.pdf
        return self.pdf_path.parent.name
    
    def parse(self) -> Dict[str, Any]:
        """解析 PDF 并返回结构化数据"""
        try:
            with pdfplumber.open(self.pdf_path) as pdf:
                # 提取所有页面的文本
                full_text = ""
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        full_text += text + "\n"
                
                if not full_text:
                    return {"error": "No text extracted"}
                
                # 解析结构化数据
                result = {
                    "class_name": self.class_name,
                    "source_file": str(self.pdf_path),
                    "namespace": self._extract_namespace(full_text),
                    "inherits_from": self._extract_inheritance(full_text),
                    "implemented_in": self._extract_implementation(full_text),
                    "description": self._extract_description(full_text),
                    "properties": self._extract_section(full_text, "Properties"),
                    "constructors": self._extract_section(full_text, "Constructors"),
                    "methods": self._extract_section(full_text, "Public Methods"),
                    "static_methods": self._extract_section(full_text, "Static Methods"),
                    "operators": self._extract_section(full_text, "Operators"),
                    "inherited_members": self._extract_inherited_members(full_text)
                }
                return result
                
        except Exception as e:
            return {"error": str(e), "class_name": self.class_name}
    
    def _extract_namespace(self, text: str) -> str:
        """提取命名空间"""
        # 格式: "class in UnityEngine"
        match = re.search(r'class in (\w+)', text)
        return match.group(1) if match else ""
    
    def _extract_inheritance(self, text: str) -> str:
        """提取继承信息"""
        # 格式: "Inherits from:Object"
        match = re.search(r'Inherits from:(\w+)', text)
        return match.group(1) if match else ""
    
    def _extract_implementation(self, text: str) -> str:
        """提取实现模块"""
        # 格式: "Implemented in:UnityEngine.CoreModule"
        match = re.search(r'Implemented in:([\w.]+)', text)
        return match.group(1) if match else ""
    
    def _extract_description(self, text: str) -> str:
        """提取类描述"""
        # 描述在 "Description" 和 "Properties" 之间
        desc_match = re.search(r'Description\s+(.*?)(?=Properties|$)', text, re.DOTALL)
        if desc_match:
            desc = desc_match.group(1).strip()
            # 清理多行描述
            desc = re.sub(r'\s+', ' ', desc)
            return desc
        return ""
    
    def _extract_section(self, text: str, section_name: str) -> List[Dict[str, str]]:
        """提取指定部分的内容（如 Properties, Public Methods 等）"""
        items = []
        
        # 部分格式: "Properties\nProperty Description\nprop1 desc1\nprop2 desc2"
        # 或: "Public Methods\nMethod Description\nmethod1 desc1\nmethod2 desc2"
        
        # 构建正则表达式（更通用）
        pattern = rf'{section_name}\s+(?:Property|Method)\s+Description\s+(.*?)(?=Public Methods|Static Methods|Inherited Members|Operators|$)'
        match = re.search(pattern, text, re.DOTALL)
        
        if match:
            section_text = match.group(1).strip()
            
            # 按行分割，每行格式: "PropertyName Description here"
            lines = [line.strip() for line in section_text.split('\n') if line.strip()]
            
            for line in lines:
                # 按第一个空格分割（属性名/方法名和描述之间）
                # 但是描述可能也以大写字母开头，所以需要更智能的分割
                
                # 启发式：找到第一个小写字母的位置，前面的是属性名/方法名
                match_name_desc = re.match(r'^([A-Z][a-zA-Z0-9]*)\s+(.*)', line)
                if match_name_desc:
                    name = match_name_desc.group(1)
                    desc = match_name_desc.group(2).strip()
                    items.append({"name": name, "description": desc})
                else:
                    # 无法解析，保存整行作为名称
                    items.append({"name": line, "description": ""})
                
        return items
    
    def _parse_item(self, text: str) -> Dict[str, str]:
        """解析单个属性/方法文本"""
        # 格式: "PropertyName Property description here"
        # 或: "MethodName Method description here"
        
        # 尝试按第一个空格分割
        parts = text.split(' ', 1)
        if len(parts) == 2:
            return {
                "name": parts[0],
                "description": parts[1].strip()
            }
        else:
            return {"name": text, "description": ""}
    
    def _extract_inherited_members(self, text: str) -> Dict[str, Any]:
        """提取继承的成员"""
        result = {"properties": [], "methods": [], "static_methods": []}
        
        # 查找 "Inherited Members" 部分
        inherited_match = re.search(r'Inherited Members\s+Properties\s+(.*?)(?=Public Methods|Static Methods|$)', text, re.DOTALL)
        if inherited_match:
            result["properties"] = self._extract_simple_list(inherited_match.group(1))
            
        method_match = re.search(r'Inherited Members.*?Public Methods\s+(.*?)(?=Static Methods|Operators|$)', text, re.DOTALL)
        if method_match:
            result["methods"] = self._extract_simple_list(method_match.group(1))
            
        static_match = re.search(r'Inherited Members.*?Static Methods\s+(.*?)(?=Operators|$)', text, re.DOTALL)
        if static_match:
            result["static_methods"] = self._extract_simple_list(static_match.group(1))
            
        return result
    
    def _extract_simple_list(self, text: str) -> List[str]:
        """从文本中提取简单列表（每行一个项）"""
        items = []
        for line in text.split('\n'):
            line = line.strip()
            if line and not any(kw in line for kw in self.NAVIGATION_KEYWORDS):
                items.append(line)
        return items


def batch_convert_pdf_to_json(pdf_dir: str, output_dir: str, limit: int = None):
    """
    批量转换 PDF 为 JSON
    
    Args:
        pdf_dir: PDF 文件所在目录（包含子目录，每个子目录代表一个类）
        output_dir: 输出 JSON 文件的目录
        limit: 限制处理数量（用于测试）
    """
    pdf_path = Path(pdf_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # 查找所有 PDF 文件
    # 路径格式: pdf_dir/ClassName/2022.3_Documentation_ScriptReference_ClassName.pdf
    pdf_files = []
    for class_dir in pdf_path.iterdir():
        if class_dir.is_dir():
            # 只查找匹配的 PDF 文件（格式: 2022.3_Documentation_ScriptReference_ClassName.pdf）
            matching_pdfs = list(class_dir.glob("2022.3_Documentation_ScriptReference_*.pdf"))
            if matching_pdfs:
                pdf_files.append(matching_pdfs[0])  # 每个类只取第一个匹配的 PDF
            else:
                # 如果没有匹配的文件，查找任何 PDF
                any_pdfs = list(class_dir.glob("*.pdf"))
                if any_pdfs:
                    pdf_files.append(any_pdfs[0])
    
    print(f"找到 {len(pdf_files)} 个 PDF 文件")
    
    # 限制处理数量（用于测试）
    if limit:
        pdf_files = pdf_files[:limit]
        print(f"限制处理前 {limit} 个文件")
    
    success_count = 0
    error_count = 0
    
    for i, pdf_file in enumerate(pdf_files, 1):
        print(f"[{i}/{len(pdf_files)}] 处理: {pdf_file.parent.name}")
        
        try:
            parser = UnityAPIParser(str(pdf_file))
            data = parser.parse()
            
            # 保存为 JSON
            output_file = output_path / f"{parser.class_name}.json"
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            success_count += 1
            print(f"  [OK] 成功: {output_file.name}")
            
        except Exception as e:
            error_count += 1
            print(f"  [ERROR] 错误: {e}")
    
    print(f"\n转换完成! 成功: {success_count}, 失败: {error_count}")


if __name__ == "__main__":
    # 测试：转换 GameObject PDF
    test_pdf = r"e:\20260426\referrence\UnityScriptReference_2022.3\GameObject\2022.3_Documentation_ScriptReference_GameObject.pdf"
    output_dir = r"e:\20260426\unified-mcp-unity\Server\data\unity_api_json"
    
    print("=== 测试单个 PDF 解析 ===")
    parser = UnityAPIParser(test_pdf)
    data = parser.parse()
    print(f"类名: {data.get('class_name')}")
    print(f"命名空间: {data.get('namespace')}")
    print(f"继承: {data.get('inherits_from')}")
    print(f"描述: {data.get('description')[:100]}...")
    print(f"属性数量: {len(data.get('properties', []))}")
    print(f"方法数量: {len(data.get('methods', []))}")
    print(f"静态方法数量: {len(data.get('static_methods', []))}")
    
    # 保存测试结果
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    output_file = Path(output_dir) / f"{data['class_name']}.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n测试结果已保存: {output_file}")
    
    # 批量转换（限制 10 个用于测试）
    print("\n=== 批量转换测试（前 10 个）===")
    batch_convert_pdf_to_json(
        pdf_dir=r"e:\20260426\referrence\UnityScriptReference_2022.3",
        output_dir=output_dir,
        limit=10
    )

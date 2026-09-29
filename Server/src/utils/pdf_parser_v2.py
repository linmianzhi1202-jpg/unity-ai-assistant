"""
Unity Script Reference PDF 解析器 V2
使用 pdfplumber 的表格提取功能，获得高质量结构化数据
"""

import json
import re
from pathlib import Path
from typing import List, Dict, Any
import pdfplumber


class UnityAPIParserV2:
    """Unity Script Reference PDF 解析器（V2 - 表格提取）"""
    
    def __init__(self, pdf_path: str):
        self.pdf_path = Path(pdf_path)
        self.class_name = self._extract_class_name()
        
    def _extract_class_name(self) -> str:
        """从文件名提取类名"""
        filename = self.pdf_path.name
        # 格式: 2022.3_Documentation_ScriptReference_ClassName.pdf
        match = re.search(r'ScriptReference_(\w+)\.pdf$', filename)
        if match:
            return match.group(1)
        return self.pdf_path.stem
        
    def parse(self) -> Dict[str, Any]:
        """解析 PDF，提取结构化数据"""
        with pdfplumber.open(self.pdf_path) as pdf:
            # 提取所有页面的文本
            full_text = ""
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    full_text += text + "\n"
            
            # 提取所有表格
            all_tables = []
            for page in pdf.pages:
                tables = page.extract_tables()
                if tables:
                    all_tables.extend(tables)
            
            # 解析结构化数据
            data = {
                "class_name": self.class_name,
                "namespace": self._extract_namespace(full_text),
                "description": self._extract_description(full_text),
                "inherits_from": self._extract_inheritance(full_text),
                "properties": self._extract_properties_from_tables(all_tables),
                "methods": self._extract_methods_from_tables(all_tables),
                "constructors": self._extract_constructors_from_tables(all_tables),
                "operators": self._extract_operators_from_tables(all_tables),
                "code_examples": self._extract_code_examples(full_text),
            }
            
            return data
            
    def _extract_namespace(self, text: str) -> str:
        """提取命名空间"""
        match = re.search(r'Namespace:\s*(\S+)', text)
        if match:
            return match.group(1)
        return ""
        
    def _extract_description(self, text: str) -> str:
        """提取类描述（在第一页，在类名之后，在 Properties 之前）"""
        # 查找 "Description" 部分之后的文本
        # Unity 文档结构: "Description\nBase class for all entities...\n\nProperties"
        pattern = r'Description\s+(.*?)(?=\s+Properties|\s+Public Methods|\s+Inherited Members)'
        match = re.search(pattern, text, re.DOTALL)
        if match:
            desc = match.group(1).strip()
            # 清理多行
            desc = re.sub(r'\s+', ' ', desc)
            
            # 清理 HTML 反馈表单内容
            desc = re.sub(r'Leave feedback.*$', '', desc)
            desc = re.sub(r'Suggest a change.*$', '', desc)
            desc = re.sub(r'Success!.*$', '', desc)
            desc = re.sub(r'Thank you for helping.*$', '', desc)
            desc = re.sub(r'Submission failed.*$', '', desc)
            desc = re.sub(r'Your name.*$', '', desc)
            desc = re.sub(r'Suggestion\*.*$', '', desc)
            desc = re.sub(r'Submit suggestion.*$', '', desc)
            desc = re.sub(r'Cancel.*$', '', desc)
            desc = re.sub(r'Switch to Manual.*$', '', desc)
            
            return desc.strip()
        
        # 后备方案：查找类名之后的第一段描述
        pattern2 = rf'{self.class_name}\s+(.*?)(?=Properties|Public Methods|Inherited Members)'
        match2 = re.search(pattern2, text, re.DOTALL)
        if match2:
            desc = match2.group(1).strip()
            desc = re.sub(r'\s+', ' ', desc)
            return desc.strip()
            
        return ""
        
    def _extract_inheritance(self, text: str) -> str:
        """提取继承信息"""
        match = re.search(r'Inherits from:\s*(\S+)', text)
        if match:
            return match.group(1)
        return ""
        
    def _extract_properties_from_tables(self, tables: List) -> List[Dict[str, str]]:
        """从表格中提取属性（合并所有 Property 表格）"""
        properties = []
        
        for table in tables:
            if not table or len(table) < 2:
                continue
                
            # 检查表头是否包含 "Property" 和 "Description"
            header = table[0]
            if header and "Property" in str(header) and "Description" in str(header):
                # 数据行
                for row in table[1:]:
                    if row and len(row) >= 2:
                        prop_name = row[0].strip() if row[0] else ""
                        prop_desc = row[1].strip() if row[1] else ""
                        if prop_name:
                            properties.append({
                                "name": prop_name,
                                "description": prop_desc
                            })
                            
        return properties
        
    def _extract_methods_from_tables(self, tables: List) -> List[Dict[str, str]]:
        """从表格中提取方法（合并所有 Method 表格，包括静态方法）"""
        methods = []
        
        for table in tables:
            if not table or len(table) < 2:
                continue
                
            # 检查表头是否包含 "Method" 和 "Description"
            header = table[0]
            if header and "Method" in str(header) and "Description" in str(header):
                # 数据行
                for row in table[1:]:
                    if row and len(row) >= 2:
                        method_name = row[0].strip() if row[0] else ""
                        method_desc = row[1].strip() if row[1] else ""
                        if method_name:
                            methods.append({
                                "name": method_name,
                                "description": method_desc
                            })
                                
        return methods
        
    def _extract_constructors_from_tables(self, tables: List) -> List[Dict[str, str]]:
        """从表格中提取构造函数"""
        constructors = []
        
        for table in tables:
            if not table or len(table) < 2:
                continue
                
            # 检查表头是否包含 "Constructor"
            header = table[0]
            if header and "Constructor" in str(header):
                # 数据行
                for row in table[1:]:
                    if row and len(row) >= 2:
                        ctor_name = row[0].strip() if row[0] else ""
                        ctor_desc = row[1].strip() if row[1] else ""
                        if ctor_name:
                            constructors.append({
                                "name": ctor_name,
                                "description": ctor_desc
                            })
                            
        return constructors
        
    def _extract_operators_from_tables(self, tables: List) -> List[Dict[str, str]]:
        """从表格中提取操作符"""
        operators = []
        
        for table in tables:
            if not table or len(table) < 2:
                continue
                
            # 检查表头是否包含 "Operator"
            header = table[0]
            if header and "Operator" in str(header):
                # 数据行
                for row in table[1:]:
                    if row and len(row) >= 2:
                        op_name = row[0].strip() if row[0] else ""
                        op_desc = row[1].strip() if row[1] else ""
                        if op_name:
                            operators.append({
                                "name": op_name,
                                "description": op_desc
                            })
                            
        return operators
        
    def _extract_code_examples(self, text: str) -> List[str]:
        """提取代码示例（在代码块中）"""
        # 查找代码块（等宽字体区域）
        # 简单启发式：查找缩进的代码行
        examples = []
        lines = text.split('\n')
        
        in_code_block = False
        current_example = []
        
        for line in lines:
            # 检测代码行（以空格开头，包含常见编程关键字）
            if re.match(r'^\s+(void|int|float|string|var|public|private|if|for|while)', line):
                in_code_block = True
                current_example.append(line.strip())
            elif in_code_block:
                # 代码块结束
                if line.strip() == "":
                    if current_example:
                        examples.append('\n'.join(current_example))
                        current_example = []
                        in_code_block = False
                else:
                    current_example.append(line.strip())
                    
        # 保存最后一个代码块
        if current_example:
            examples.append('\n'.join(current_example))
            
        return examples


def convert_pdf_to_json(pdf_path: str, output_path: str):
    """转换单个 PDF 为 JSON"""
    parser = UnityAPIParserV2(pdf_path)
    data = parser.parse()
    
    # 保存
    output_file = Path(output_path) / f"{parser.class_name}.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    return output_file


def batch_convert_pdf_to_json(pdf_dir: str, output_dir: str, limit: int = None):
    """批量转换 PDF 为 JSON"""
    pdf_path = Path(pdf_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # 查找所有 PDF 文件
    pdf_files = []
    for class_dir in pdf_path.iterdir():
        if class_dir.is_dir():
            # 查找匹配的 PDF 文件
            matching_pdfs = list(class_dir.glob("2022.3_Documentation_ScriptReference_*.pdf"))
            if matching_pdfs:
                pdf_files.append(matching_pdfs[0])
    
    print(f"找到 {len(pdf_files)} 个 PDF 文件")
    
    # 限制数量
    if limit:
        pdf_files = pdf_files[:limit]
        print(f"限制处理前 {limit} 个文件")
    
    # 批量转换
    success_count = 0
    error_count = 0
    
    for i, pdf_file in enumerate(pdf_files, 1):
        print(f"[{i}/{len(pdf_files)}] 处理: {pdf_file.name}")
        
        try:
            output_file = convert_pdf_to_json(str(pdf_file), str(output_path))
            success_count += 1
            print(f"  [OK] 成功: {output_file.name}")
            
        except Exception as e:
            error_count += 1
            print(f"  [ERROR] 错误: {e}")
    
    print(f"\n转换完成: 成功 {success_count} 个, 失败 {error_count} 个")


if __name__ == "__main__":
    # 测试单个文件
    print("=" * 60)
    print("测试 V2 解析器（表格提取）")
    print("=" * 60)
    
    test_pdf = r"e:\20260426\referrence\UnityScriptReference_2022.3\GameObject\2022.3_Documentation_ScriptReference_GameObject.pdf"
    output_dir = r"e:\20260426\unified-mcp-unity\Server\data\unity_api_json_v2"
    
    print(f"\n测试文件: {test_pdf}")
    output_file = convert_pdf_to_json(test_pdf, output_dir)
    print(f"输出文件: {output_file}")
    
    # 显示解析结果
    with open(output_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    print(f"\n解析结果:")
    print(f"  类名: {data['class_name']}")
    print(f"  命名空间: {data['namespace']}")
    print(f"  继承: {data['inherits_from']}")
    print(f"  描述: {data['description'][:100]}...")
    print(f"  属性数量: {len(data['properties'])}")
    print(f"  方法数量: {len(data['methods'])}")
    print(f"  静态方法数量: {len(data['static_methods'])}")
    print(f"  代码示例数量: {len(data['code_examples'])}")
    
    # 显示前3个属性
    if data['properties']:
        print(f"\n前3个属性:")
        for prop in data['properties'][:3]:
            print(f"  - {prop['name']}: {prop['description'][:50]}...")
    
    # 显示前3个方法
    if data['methods']:
        print(f"\n前3个方法:")
        for method in data['methods'][:3]:
            print(f"  - {method['name']}: {method['description'][:50]}...")

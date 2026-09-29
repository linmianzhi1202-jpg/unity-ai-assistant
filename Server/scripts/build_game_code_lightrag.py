#!/usr/bin/env python3
"""
一键将 game_code_graph.json 注入 LightRAG 知识图谱（零 LLM 调用）

用法:
    cd unity-ai-assistant-product/Server
    python scripts/build_game_code_lightrag.py

选项:
    --graph-path PATH    game_code_graph.json 路径（默认自动探测）
    --batch-size N       每批最大实体数（默认 200）
    --dry-run            只读取图谱打印统计，不实际注入
"""

import argparse
import json
import sys
import time
from pathlib import Path

# 确保可以导入项目模块
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def auto_detect_graph_path() -> str:
    """自动探测 game_code_graph.json 位置"""
    candidates = [
        # 相对项目根目录
        Path(__file__).resolve().parent.parent / "data" / "game-rag-knowledge-base" / "data" / "game_code_graph.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    raise FileNotFoundError(
        "无法找到 game_code_graph.json。请使用 --graph-path 指定路径。\n"
        f"尝试过的路径: {[str(c) for c in candidates]}"
    )


def dry_run(graph_path: str):
    """只读取图谱，打印统计"""
    import json
    with open(graph_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    nodes = data["nodes"]
    edges = data["edges"]
    
    # 统计实体类型
    type_counts = {}
    for n in nodes:
        t = n.get("entity_type", "?")
        type_counts[t] = type_counts.get(t, 0) + 1
    
    # 统计关系类型
    rel_counts = {}
    for e in edges:
        t = e.get("relation_type", "?")
        rel_counts[t] = rel_counts.get(t, 0) + 1
    
    # 统计游戏项目
    games = set()
    for n in nodes:
        gn = n.get("metadata", {}).get("game_name", "unknown")
        games.add(gn)
    
    # 每个游戏的实体数
    game_entity_counts = {}
    for n in nodes:
        gn = n.get("metadata", {}).get("game_name", "unknown")
        game_entity_counts[gn] = game_entity_counts.get(gn, 0) + 1
    
    print("=" * 70)
    print("  game_code_graph.json 统计")
    print("=" * 70)
    print(f"  总节点:  {len(nodes):,}")
    print(f"  总边数:  {len(edges):,}")
    print(f"  游戏数:  {len(games)}")
    print()
    
    print("  实体类型分布:")
    for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"    {t:12s}: {c:>6,}")
    print()
    
    print("  关系类型分布:")
    for t, c in sorted(rel_counts.items(), key=lambda x: -x[1]):
        skip_mark = " [跳过]" if t == "same_game" else ""
        print(f"    {t:20s}: {c:>6,}{skip_mark}")
    print()
    
    print("  游戏项目:")
    for gn, count in sorted(game_entity_counts.items(), key=lambda x: -x[1]):
        print(f"    {gn[:55]:55s}: {count:>5,} 实体")
    
    # 估算注入量
    rel_to_inject = sum(c for t, c in rel_counts.items() if t != "same_game")
    print()
    print(f"  预计注入: {len(nodes):,} 实体 + {rel_to_inject:,} 关系")
    print(f"  跳过:     same_game 关系 {rel_counts.get('same_game', 0):,} 条")


def main():
    parser = argparse.ArgumentParser(
        description="将 game_code_graph.json 注入 LightRAG 游戏源码知识图谱"
    )
    parser.add_argument(
        "--graph-path",
        type=str,
        default="",
        help="game_code_graph.json 路径（默认自动探测）",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help="每批最大实体数（默认 200）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只读取图谱并打印统计，不实际注入",
    )
    
    args = parser.parse_args()
    
    # 确定图谱路径
    graph_path = args.graph_path or auto_detect_graph_path()
    print(f"\n[Build] 图谱路径: {graph_path}")
    
    if args.dry_run:
        dry_run(graph_path)
        return
    
    # 导入 LightRAG 模块
    from services.rag.lightrag_store import (
        get_game_code_lightrag_store,
        GAME_CODE_DEFAULT_WORKING_DIR,
    )
    
    print(f"\n[Build] LightRAG 工作目录: {GAME_CODE_DEFAULT_WORKING_DIR}")
    print(f"[Build] 批大小: {args.batch_size}")
    print()
    
    # 获取游戏源码 LightRAG 实例
    print("[Build] 初始化游戏源码 LightRAG 实例...")
    store = get_game_code_lightrag_store(working_dir=GAME_CODE_DEFAULT_WORKING_DIR)
    
    # 注入图谱
    print("[Build] 开始注入游戏源码图谱...")
    print("=" * 70)
    
    t_start = time.time()
    
    try:
        result = store.insert_game_code_graph(
            graph_path=graph_path,
            max_entities_per_batch=args.batch_size,
        )
        
        t_elapsed = time.time() - t_start
        
        print()
        print("=" * 70)
        print("  注入完成!")
        print("=" * 70)
        print(f"  处理游戏:    {result['games_processed']}")
        print(f"  注入实体:    {result['total_entities']:,}")
        print(f"  注入关系:    {result['total_relationships']:,}")
        print(f"  注入 chunks: {result['total_chunks']:,}")
        print(f"  跳过 same_game: {result.get('skipped_same_game', 0):,}")
        print(f"  耗时:        {t_elapsed:.1f}s ({t_elapsed/60:.1f}m)")
        print(f"  状态:        {result['status'].upper()}")
        print()
        
        # 验证
        print("[Build] 验证图谱状态...")
        status = store.get_status()
        print(f"  graph_exists:    {status.get('graph_exists', False)}")
        print(f"  graph_size_kb:   {status.get('graph_size_kb', 0):,.1f} KB")
        print(f"  doc_count:       {status.get('doc_count', 0)}")
        
    except Exception as e:
        t_elapsed = time.time() - t_start
        print(f"\n[Build] 注入失败 ({t_elapsed:.1f}s)")
        print(f"  错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

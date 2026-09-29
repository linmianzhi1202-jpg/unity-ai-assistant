#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
游戏源码 RAG 知识库构建脚本
一键构建：扫描 .cs 文件 → 智能分块 → 嵌入向量 → 存入 ChromaDB

用法：
    # 首次构建
    python build_game_rag.py

    # 重建（清空现有数据）
    python build_game_rag.py --clear

    # 使用自定义配置
    python build_game_rag.py --config custom_config.yaml

    # 查看统计
    python build_game_rag.py --stats
"""

import sys
import os
import argparse
import logging
from pathlib import Path

# ---- 添加项目路径 ----
_PROJECT_ROOT = Path(__file__).parent.parent  # data/
_KB_DIR = Path(__file__).parent               # game-rag-knowledge-base/
_GAME_RAG_SRC = _PROJECT_ROOT / "game-rag-knowledge-base" / "src"
_SERVER_SRC = _PROJECT_ROOT.parent / "src"   # Server/src

sys.path.insert(0, str(_GAME_RAG_SRC))
sys.path.insert(0, str(_SERVER_SRC))

from code_processor import CodeProcessor, create_processor, CodeChunk

# chromadb 是独立 pip 包，分离导入避免被 services 错误连累
try:
    import chromadb
except ImportError:
    chromadb = None

try:
    from services.rag.embedding_manager import EmbeddingManager
    _PRODUCT_MODULES_LOADED = True
except ImportError as exc:
    EmbeddingManager = None
    _PRODUCT_MODULES_LOADED = False
    print(f"[WARN] 产品 RAG 模块加载失败: {exc}")

# ---- 日志配置 ----
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)


def _resolve_path(p: str) -> str:
    """把相对路径解析为相对于 game-rag-knowledge-base 目录的绝对路径。"""
    if not p:
        return p
    path = Path(p)
    if not path.is_absolute():
        path = _KB_DIR / path
    return str(path)


def load_config(config_path: str = None) -> dict:
    """加载 YAML 配置文件"""
    import yaml

    if config_path is None:
        config_path = _PROJECT_ROOT / "game-rag-knowledge-base" / "config" / "config_game.yaml"
    else:
        config_path = Path(config_path)

    if not config_path.exists():
        logger.error(f"配置文件不存在: {config_path}")
        sys.exit(1)

    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    logger.info(f"已加载配置: {config_path}")
    return config


def setup_logging(config: dict):
    """配置文件日志"""
    log_config = config.get('logging', {})
    log_level = getattr(logging, log_config.get('level', 'INFO'))
    log_file = _resolve_path(log_config.get('file') or '')

    handlers = [logging.StreamHandler()]
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding='utf-8'))

    logging.getLogger().setLevel(log_level)
    for handler in logging.getLogger().handlers[:]:
        logging.getLogger().removeHandler(handler)
    for handler in handlers:
        logging.getLogger().addHandler(handler)


def build_knowledge_base(
    config: dict,
    clear_existing: bool = False,
    batch_size: int = 100,
    progress_callback=None,
    skip_games: set = None,
) -> dict:
    """
    构建知识库

    Args:
        config: 配置字典
        clear_existing: 是否清空现有数据
        batch_size: 批处理大小
        progress_callback: 进度回调
        skip_games: 要跳过的游戏名集合（增量构建用）

    Returns:
        构建统计信息
    """
    skip_games = skip_games or set()
    logger.info("=" * 60)
    logger.info("开始构建游戏源码 RAG 知识库" + (" [增量]" if skip_games else " [全量]"))
    logger.info("=" * 60)

    if not _PRODUCT_MODULES_LOADED:
        logger.error("产品 RAG 模块未加载，无法构建知识库")
        return {"error": "产品 RAG 模块未加载"}

    # 1. 初始化嵌入模型（使用产品 EmbeddingManager）
    logger.info("初始化嵌入模型...")
    embedding_config = config.get('embedding', {})
    model_name = embedding_config.get('local', {}).get('model_name', 'BAAI/bge-small-zh-v1.5')
    trust_remote_code = embedding_config.get('local', {}).get('trust_remote_code', False)
    embedding_manager = EmbeddingManager(model_name=model_name, trust_remote_code=trust_remote_code)
    if embedding_manager.model is None:
        logger.error("嵌入模型加载失败")
        return {"error": "嵌入模型加载失败"}
    logger.info(f"嵌入模型: {model_name}, 维度: {embedding_manager.model.get_sentence_embedding_dimension()}")

    # 2. 初始化向量数据库（直接操作 ChromaDB）
    logger.info("初始化向量数据库...")
    vs_config = config.get('vector_store', {})
    persist_dir = _resolve_path(vs_config.get('persist_directory', ''))
    collection_name = vs_config.get('collection_name', 'game_source_code')
    if persist_dir:
        Path(persist_dir).mkdir(parents=True, exist_ok=True)

    client = chromadb.PersistentClient(path=persist_dir)
    if clear_existing:
        logger.info("清空现有数据...")
        try:
            client.delete_collection(name=collection_name)
        except Exception:
            pass
        collection = client.create_collection(name=collection_name)
    else:
        try:
            collection = client.get_collection(name=collection_name)
        except Exception:
            collection = client.create_collection(name=collection_name)
    logger.info(f"集合名: {collection_name}, 存储目录: {persist_dir}")

    # 3. 扫描并分块
    logger.info("扫描游戏源码...")
    source_root = _resolve_path(config.get('source', {}).get('root_directory', ''))
    if not source_root:
        logger.error("未配置游戏源码根目录")
        return {"error": "未配置 source.root_directory"}

    processor = create_processor(source_root, config.get('source', {}))

    # 增量模式：过滤已处理的游戏
    all_game_dirs = processor.scan_game_dirs()
    new_game_dirs = []
    for gd in all_game_dirs:
        gn = processor.get_game_name(gd)
        if gn in skip_games:
            logger.info(f"跳过已处理: {gn}")
        else:
            new_game_dirs.append(gd)

    if not new_game_dirs:
        logger.info("没有新游戏需要处理。")
        return {
            'games': len(all_game_dirs),
            'cs_files': 0, 'total_chunks': 0,
            'class_chunks': 0, 'method_chunks': 0, 'file_chunks': 0,
            'errors': 0, 'vector_count': collection.count(),
            'skipped': True,
        }

    # 统计信息
    stats = {
        'games': len(all_game_dirs),
        'new_games': len(new_game_dirs),
        'cs_files': 0,
        'total_chunks': 0,
        'class_chunks': 0,
        'method_chunks': 0,
        'file_chunks': 0,
        'errors': 0,
    }

    # 4. 批量嵌入和存储
    def flush_file_chunks(file_chunks: list) -> int:
        """提交单个文件的代码块，返回成功写入数。
        失败时只丢弃当前文件的块，不影响其他文件。"""
        if not file_chunks:
            return 0

        ids = [c.id for c in file_chunks]
        texts = [c.text for c in file_chunks]
        metas = [c.metadata for c in file_chunks]

        # 生成嵌入（使用产品 EmbeddingManager）
        try:
            embeddings = embedding_manager.encode(texts, show_progress_bar=False)
        except Exception:
            embeddings = []
            for t in texts:
                try:
                    embeddings.append(embedding_manager.encode([t], show_progress_bar=False)[0])
                except Exception:
                    embeddings.append(None)

        # 过滤无效，转为 Python list（ChromaDB 需要）
        v_ids, v_texts, v_metas, v_vecs = [], [], [], []
        for i, emb in enumerate(embeddings):
            if emb is not None:
                v_ids.append(ids[i])
                v_texts.append(texts[i])
                v_metas.append(metas[i])
                vec = emb.tolist() if hasattr(emb, 'tolist') else emb
                v_vecs.append(vec)

        if v_ids:
            collection.upsert(ids=v_ids, documents=v_texts, metadatas=v_metas, embeddings=v_vecs)
        return len(v_ids)

    # 处理所有文件（仅新游戏）—— 逐文件提交，失败不连累
    for game_dir in new_game_dirs:
        game_name = processor.get_game_name(game_dir)
        cs_files = processor.find_cs_files(game_dir)
        stats['cs_files'] += len(cs_files)

        for cs_file in cs_files:
            try:
                file_chunks = list(processor.process_file(cs_file, game_name))
                written = flush_file_chunks(file_chunks)
                stats['total_chunks'] += len(file_chunks)

                for chunk in file_chunks:
                    ct = chunk.metadata.get('code_type', '')
                    if 'overview' in ct:
                        stats['class_chunks'] += 1
                    elif ct == 'method_detail':
                        stats['method_chunks'] += 1
                    elif ct == 'full_file':
                        stats['file_chunks'] += 1

            except Exception as e:
                logger.warning(f"处理文件失败: {cs_file.name}, 错误: {e}")
                stats['errors'] += 1

        # 处理包依赖文件
        for pkg_file in processor.find_package_files(game_dir):
            try:
                chunk = processor.process_package_file(pkg_file, game_name)
                if chunk:
                    flush_file_chunks([chunk])
                    stats['total_chunks'] += 1
                    stats['package_chunks'] = stats.get('package_chunks', 0) + 1
            except Exception as e:
                logger.debug(f"包文件处理失败: {pkg_file.name}: {e}")

        # 处理资产文件（图片、预制体、场景、材质等）
        stats.setdefault('asset_files', 0)
        asset_files = processor.find_asset_files(game_dir)
        stats['asset_files'] += len(asset_files)
        for asset_file in asset_files:
            try:
                chunk = processor.process_asset_file(asset_file, game_name)
                if chunk:
                    flush_file_chunks([chunk])
                    stats['total_chunks'] += 1
                    stats['asset_chunks'] = stats.get('asset_chunks', 0) + 1
            except Exception as e:
                logger.debug(f"资产处理失败: {asset_file.name}: {e}")

    # 5. 构建/合并代码知识图谱 (GraphRAG)
    try:
        from code_graph_extractor import CodeGraphExtractor
        import json as _json

        graph_path = os.path.join(os.path.dirname(persist_dir), 'game_code_graph.json')

        # 收集本次新增的代码块
        new_chunks = []
        for game_dir in new_game_dirs:
            game_name = processor.get_game_name(game_dir)
            cs_files = processor.find_cs_files(game_dir)
            for cs_file in cs_files:
                try:
                    for chunk in processor.process_file(cs_file, game_name):
                        new_chunks.append(chunk)
                except Exception:
                    pass

        if new_chunks:
            logger.info("构建/合并代码知识图谱...")
            extractor = CodeGraphExtractor()
            new_graph = extractor.build_from_chunks(new_chunks)

            # 为资产文件和代码类建立关联（Sprite/GameObject 字段 ↔ .png/.prefab 文件）
            logger.info("建立代码→资产关联...")
            asset_entities, asset_relations = _build_asset_code_links(
                processor, new_game_dirs, new_graph, extractor._entity_counter
            )
            for ae in asset_entities:
                new_graph['nodes'].append(ae)
            new_graph['edges'].extend(asset_relations)
            new_graph['stats']['entity_count'] += len(asset_entities)
            new_graph['stats']['relation_count'] += len(asset_relations)
            logger.info(f"  资产关联: {len(asset_entities)} 资产实体, {len(asset_relations)} 关系")

            # 增量合并到已有图谱
            if not clear_existing and os.path.exists(graph_path):
                logger.info("合并到已有图谱...")
                with open(graph_path, 'r', encoding='utf-8') as f:
                    old_data = _json.load(f)

                # 合并节点（新节点覆盖旧节点）
                merged_nodes = {n['id']: n for n in old_data.get('nodes', [])}
                for n in new_graph['nodes']:
                    merged_nodes[n['id']] = n

                # 合并边（去重）
                edge_keys = set()
                merged_edges = []
                for e in old_data.get('edges', []):
                    key = f"{e['source']}|{e['target']}|{e['relation_type']}"
                    if key not in edge_keys:
                        edge_keys.add(key)
                        merged_edges.append(e)
                for e in new_graph['edges']:
                    key = f"{e['source']}|{e['target']}|{e['relation_type']}"
                    if key not in edge_keys:
                        edge_keys.add(key)
                        merged_edges.append(e)

                graph_data = {
                    "nodes": list(merged_nodes.values()),
                    "edges": merged_edges,
                    "stats": {
                        "entity_count": len(merged_nodes),
                        "relation_count": len(merged_edges),
                    }
                }
            else:
                graph_data = new_graph

            extractor.save(graph_data, graph_path)
            stats['graph_entities'] = len(graph_data['nodes'])
            stats['graph_relations'] = len(graph_data['edges'])
            logger.info(f"  图谱: {stats['graph_entities']} 实体, "
                       f"{stats['graph_relations']} 关系")
    except ImportError:
        logger.warning("code_graph_extractor 模块不可用，跳过图谱构建")
    except Exception as e:
        logger.warning(f"图谱构建失败: {e}")

    # 最终统计
    logger.info("=" * 60)
    logger.info("构建完成!")
    logger.info(f"  游戏项目: {stats['games']}")
    logger.info(f"  C# 文件: {stats['cs_files']}")
    logger.info(f"  总块数:   {stats['total_chunks']}")
    logger.info(f"    - 类概览: {stats['class_chunks']}")
    logger.info(f"    - 方法:   {stats['method_chunks']}")
    logger.info(f"    - 文件:   {stats['file_chunks']}")
    logger.info(f"  错误:     {stats['errors']}")
    logger.info(f"  向量库文档数: {collection.count()}")
    logger.info("=" * 60)

    stats['vector_count'] = collection.count()
    return stats


def _build_asset_code_links(processor, game_dirs, graph, entity_counter):
    """为资产文件和代码建立关联"""
    import re as _re
    ents = []
    rels = []

    for gd in game_dirs:
        gname = processor.get_game_name(gd)
        # 找该游戏的所有 asset 文件
        asset_files = processor.find_asset_files(gd)
        asset_map = {}  # stem → file_path
        for af in asset_files[:2000]:
            stem = af.stem.lower()
            asset_map.setdefault(stem, []).append(af)

        # 找该游戏的代码实体中 Sprite/GameObject/Texture 类型字段
        # graph['nodes'] is a list of dicts; iterate directly
        nodes_iter = graph.get('nodes', []) if isinstance(graph, dict) else graph.nodes(data=True)
        for item in nodes_iter:
            if isinstance(item, dict):
                node = item
                nid = node.get('id', '')
            else:
                # networkx tuple: (node_id, node_data)
                nid, node = item
            if isinstance(node, dict) and node.get('entity_type') == 'field':
                ftype = (node.get('metadata', {}).get('field_type', '') or '').lower()
                if any(t in ftype for t in ('sprite', 'gameobject', 'texture', 'material')):
                    fname = node.get('name', '').lower()
                    # 尝试匹配同名资产
                    candidates = asset_map.get(fname, []) or []
                    if not candidates:
                        # 模糊匹配
                        for stem, paths in asset_map.items():
                            if fname in stem or stem in fname:
                                candidates.extend(paths)
                    for af in candidates[:3]:
                        entity_counter += 1
                        aid = f"asset:{gname}/{af.name}"
                        rel_path = processor._get_relative_path(af, gname)
                        ents.append({
                            "id": aid, "name": af.name, "entity_type": "asset",
                            "description": f"资产: {rel_path}",
                            "metadata": {"game_name": gname, "file_path": rel_path,
                                        "file_name": af.name, "asset_type": af.suffix.lower()}
                        })
                        rels.append({
                            "source": nid, "target": aid,
                            "relation_type": "code_uses_asset", "weight": 0.65,
                            "metadata": {}
                        })
    return ents, rels



def show_stats(config: dict):
    """查看知识库统计信息"""
    vs_config = config.get('vector_store', {})

    logger.info("知识库统计:")
    logger.info(f"  集合名: {vs_config.get('collection_name')}")
    logger.info(f"  存储目录: {vs_config.get('persist_directory')}")

    persist_dir = _resolve_path(vs_config.get('persist_directory', ''))
    if persist_dir and Path(persist_dir).exists():
        try:
            client = chromadb.PersistentClient(path=persist_dir)
            collection = client.get_collection(name=vs_config.get('collection_name', 'game_source_code'))
            count = collection.count()
            logger.info(f"  文档数: {count}")
        except Exception as e:
            logger.warning(f"  无法读取集合: {e}")
    else:
        logger.warning("  知识库尚未构建，请先运行 build 命令")


def main():
    parser = argparse.ArgumentParser(
        description='游戏源码 RAG 知识库构建工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python build_game_rag.py                # 构建知识库
  python build_game_rag.py --clear        # 重建
  python build_game_rag.py --stats        # 查看统计
  python build_game_rag.py --batch 50     # 自定义批大小
        """
    )

    parser.add_argument('--config', '-c', help='配置文件路径（默认 config/config_game.yaml）')
    parser.add_argument('--clear', action='store_true', help='清空现有数据后重建（全量）')
    parser.add_argument('--incremental', '-i', action='store_true',
                       help='增量构建：只处理新增游戏，跳过已处理的')
    parser.add_argument('--batch-size', type=int, default=100, help='批处理大小（默认 100）')
    parser.add_argument('--stats', action='store_true', help='仅查看统计信息')
    parser.add_argument('--verbose', '-v', action='store_true', help='详细日志')

    args = parser.parse_args()

    # 加载配置
    config = load_config(args.config)
    setup_logging(config)

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.stats:
        show_stats(config)
        return

    # 增量模式：读取已处理游戏列表
    skip_games = set()
    processed_file = os.path.join(
        config.get('vector_store', {}).get('persist_directory', ''),
        '..', 'processed_games.json'
    )
    processed_file = os.path.normpath(processed_file)

    if args.incremental and not args.clear:
        if os.path.exists(processed_file):
            with open(processed_file, 'r', encoding='utf-8') as f:
                skip_games = set(json.load(f))
            logger.info(f"增量模式: 已跳过 {len(skip_games)} 个已处理游戏")

    # 构建知识库
    result = build_knowledge_base(
        config=config,
        clear_existing=args.clear,
        batch_size=args.batch_size,
        skip_games=skip_games,
    )

    if 'error' in result:
        logger.error(f"构建失败: {result['error']}")
        sys.exit(1)

    if result.get('skipped'):
        print("[OK] 所有游戏均已处理，无需重建。")
        return

    # 更新已处理游戏列表
    if not args.clear:
        try:
            processor = create_processor(
                config.get('source', {}).get('root_directory', ''),
                config.get('source', {})
            )
            all_games = {
                processor.get_game_name(d) for d in processor.scan_game_dirs()
            }
            os.makedirs(os.path.dirname(processed_file), exist_ok=True)
            with open(processed_file, 'w', encoding='utf-8') as f:
                json.dump(sorted(all_games), f, ensure_ascii=False)
        except Exception:
            pass

    print(f"\n[OK] 构建成功! 共 {result['total_chunks']} 个代码块已入库.")


if __name__ == '__main__':
    main()

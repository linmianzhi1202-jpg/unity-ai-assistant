# Game Source Code RAG Workflow

This product server can reuse the local game source code knowledge base at:

`<项目目录>/Server/data/game-rag-knowledge-base`

Use it before changing gameplay, UI, prefab, or systems code. The intended flow is:

1. Search similar game source code with `search_game_code`.
2. Use `search_game_code_graph` when the feature spans classes or call chains.
3. Adapt the best references into one existing project script with `adapt_game_code`.
4. Preview first, then set `apply=true` only when the generated script looks right.
5. Refresh/compile Unity and check console logs.

## Build Or Rebuild

From the workspace root:

```powershell
cd <项目目录>\Server\data\game-rag-knowledge-base
python build_game_rag.py
```

For a clean rebuild:

```powershell
python build_game_rag.py --clear
```

Check product-side status:

```text
game_code_stats()
knowledge_modules()
```

`knowledge_modules` includes a `game_source_code` section with config, vector store, graph, and build status.

## Query Examples

Good prompts are feature-oriented and mention the gameplay role:

```text
search_game_code("tower defense tower attack projectile targeting", top_k=5)
search_game_code("enemy wave spawn checkpoints movement", top_k=5)
search_game_code("money label ui update tower purchase", top_k=5)
search_game_code_graph("tower attack system complete call chain", top_k=5, traverse_depth=2)
```

Use filters when you already know the relevant class or game:

```text
search_game_code("projectile movement", class_name="Tower", code_type="method_detail")
```

## Result Fields

Each search result is normalized for implementation work:

- `file_path`: original source file path
- `class_name` / `method_name`: source symbol to inspect
- `code_type`: `class_overview` or `method_detail`
- `line_start` / `line_end`: source location when indexed
- `score`: semantic match score
- `summary`: short description of the match
- `reuse_hint`: how to adapt it safely
- `text`: source snippet

Treat returned code as a reference. Adapt naming, serialized fields, prefabs, scene object paths, and Unity lifecycle hooks to the current project.

## Adapt References Into A Project Script

`adapt_game_code` turns search results into a complete replacement C# file for one existing script.
It reads the current Unity project, samples nearby scripts, infers local style, and asks local Ollama
to generate adapted code. It does not create missing files and does not perform multi-file edits.

Preview only:

```text
adapt_game_code(
  goal="Add tower target acquisition and attack cooldown logic",
  target_script_path="Assets/Scripts/Tower/Tower.cs",
  reference_results_json="<JSON returned by search_game_code>",
  apply=false
)
```

Apply after reviewing the preview:

```text
adapt_game_code(
  goal="Add enemy wave reward money UI update",
  target_script_path="Assets/Scripts/GameManager.cs",
  reference_results_json="<JSON returned by search_game_code_graph>",
  apply=true
)
```

The tool returns `matched_references`, `project_style_summary`, `generated_code`,
`adaptation_notes`, `planned_edits`, `warnings`, `quality_audit`, `apply_ready`, and `next_action`.
When `apply=true`, it also returns `write_result`, `compile_result`, and `logs_excerpt`.

See **[adapt_game_code_examples.md](./adapt_game_code_examples.md)** for ready-to-copy examples using
`Tower.cs` / `GameManager.cs` from the current project, with realistic goals, search queries,
and the full two-step (search → preview → apply) flow.

Local generation requires Ollama. Configure the model with:

```powershell
$env:UNITY_MCP_CODE_ADAPT_MODEL = "gemma4:26b"
$env:OLLAMA_HOST = "http://localhost:11434"
```

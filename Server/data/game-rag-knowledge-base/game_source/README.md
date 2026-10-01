# 游戏源码目录

把你的 Unity 游戏源码放到这个目录下，用于构建游戏代码知识库。

## 目录结构

每个游戏是一个子目录，需包含 Unity 项目结构（`Assets/Scripts/`）：

```
game_source/
  ├── MyGame1/
  │   └── Assets/Scripts/...
  ├── MyGame2/
  │   └── Assets/Scripts/...
  └── ...
```

## 构建知识库

放入源码后，双击项目根目录下的 `build_game_rag.bat` 完成构建。

构建完成后，在 CodeBuddy 中可用 `search_game_code` / `search_game_code_graph` 检索你的游戏代码。

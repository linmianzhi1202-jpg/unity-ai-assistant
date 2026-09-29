"""Run only the bundled TestRunner fixtures in an explicitly selected isolated Unity project."""
import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Server/src"))
from core.config import config
from fastmcp import FastMCP
from services.tools import register_all_tools
from services.tools.unity_bridge import get_bridge, send_to_unity

async def verify(project, report):
    config.unity_project_path = str(project.resolve())
    await get_bridge().select_project(config.unity_project_path)
    info = await get_bridge().get_unity_info()
    mcp = FastMCP("test-runner-live"); register_all_tools(mcp)
    checks = []
    async def ready():
        async with asyncio.timeout(60):
            while True:
                try:
                    value = await send_to_unity("manage_editor", {"action":"get_editor_state"})
                    state = value.get("result", {})
                    if value.get("status") == "success" and state.get("is_compiling") is False and state.get("is_playing") is False:
                        await asyncio.sleep(1)
                        return
                except ConnectionError: pass
                await asyncio.sleep(.5)
    async def call(**kwargs):
        value = (await mcp.call_tool("run_tests", kwargs)).structured_content
        checks.append(value)
        print(json.dumps({"filter":kwargs.get("test_filter"), "state":value.get("state"), "success":value.get("success"), "error":value.get("error")}), flush=True)
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps({"unity":info, "checks":checks},ensure_ascii=False,indent=2), encoding="utf-8")
        return value
    for mode, name, expected in [("EditMode","McpEditTests.Pass","passed"), ("EditMode","McpEditTests.Fail","failed"),
                                 ("EditMode","McpEditTests.Skip","failed"), ("EditMode","McpMissingTests","no_tests"),
                                 ("PlayMode","McpPlayTests.Pass","passed"), ("PlayMode","McpPlayTests.Fail","failed")]:
        await ready()
        result = await call(test_mode=mode,test_filter=name,timeout=120)
        assert result["state"] == expected, result
        assert result["success"] == (expected == "passed"), result
        if expected != "no_tests":
            assert result["results"]["total"] == 1, result
            assert Path(result["results"]["xml_path"]).is_file(), result
    await ready()
    slow = await call(test_filter="McpEditTests.Slow", timeout=.6)
    assert slow["state"] == "timeout", slow
    busy = await call(test_filter="McpEditTests.Pass", timeout=3)
    assert not busy["success"] and "active" in busy["error"], busy
    resumed = await call(run_id=slow["run_id"], timeout=60)
    assert resumed["success"] and resumed["results"]["total"] == 1, resumed
    report.write_text(json.dumps({"status":"passed","unity":info,"checks":checks},ensure_ascii=False,indent=2),encoding="utf-8")
    get_bridge().close()

if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--project",required=True,type=Path)
    parser.add_argument("--report",type=Path,default=ROOT/"Server/tests/reports/unity_test_runner.json")
    args=parser.parse_args()
    if not (args.project/"Assets/McpTestFixtures").is_dir():
        parser.error("Select an isolated project containing the bundled Assets/McpTestFixtures")
    asyncio.run(verify(args.project,args.report))

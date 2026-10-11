# web/api/console_service.py
"""
BOSS智库 统一控制台服务（合并后台，方案 A）

职责：
- 挂载 import_service 路由：上传导入、任务状态、旧版 /import.html
- 挂载 query_service 路由：检索问答、SSE 流式、历史记录、旧版 /chat.html
- 新增 2 个只读接口：/api/import/tasks（导入任务列表）、/api/import/documents（已入库文档列表）
- 提供统一控制台页面 /console.html（三 Tab：上传导入 / 文档管理 / 检索问答）

运行方式（在项目根目录执行）：
    .venv\\Scripts\\python.exe -m web.api.console_service
"""
import sys
from pathlib import Path

# 将项目根目录加入 sys.path，保证两种启动方式（-m / 直接运行）都能解析 utils、web 包
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import uvicorn
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import FileResponse

from web.api.import_service import router as import_router
from web.api.query_service import router as query_router
from utils.task_utils import get_import_tasks
from tool.logger import logger

# 1. 创建统一应用
app = FastAPI(
    title="BOSS智库-统一控制台",
    description="导入 + 查询合并后台（单进程单端口），控制台地址 /console.html",
)

# 2. 跨域（合并后统一在此配置，业务模块不再各自添加）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许的源
    allow_credentials=True,  # 允许携带cookie
    allow_methods=["*"],  # 允许的请求方法
    allow_headers=["*"],  # 允许的请求头
)

# 3. 挂载原有业务路由（业务逻辑零改动，仅把 FastAPI 实例替换为 APIRouter）
app.include_router(import_router)
app.include_router(query_router)


# 4. 统一控制台页面
@app.get("/console.html", summary="统一控制台页面", description="三 Tab：上传导入 / 文档管理 / 检索问答")
async def console_page():
    current_dir_parent_path = Path(__file__).absolute().parent.parent
    html_path = current_dir_parent_path / "page" / "console.html"
    if not html_path.exists():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"没有查询到页面，地址为：{html_path}")
    return FileResponse(html_path)


# 5. 新增只读接口（供控制台「文档管理」Tab 使用）

@app.get("/api/import/tasks", summary="导入任务列表（只读）", description="返回全部导入任务的状态概览，按创建时间倒序")
async def import_tasks():
    """导入任务列表：来自内存任务追踪（task_utils），与 /status/{task_id} 同一数据源。"""
    return {
        "code": 200,
        "tasks": get_import_tasks(),
    }


@app.get("/api/import/documents", summary="已入库文档列表（只读）", description="返回已成功导入（completed）的文档清单")
async def import_documents():
    """已入库文档列表：从已完成导入任务中提取（状态为 completed 的文件名）。"""
    tasks = get_import_tasks()
    documents = [
        {
            "task_id": t["task_id"],
            "filename": t["filename"],
            "created_at": t["created_at"],
            "status": t["status"],
        }
        for t in tasks if t["status"] == "completed"
    ]
    documents.sort(key=lambda d: d["created_at"], reverse=True)
    return {
        "code": 200,
        "documents": documents,
    }


if __name__ == "__main__":
    logger.info("BOSS智库统一控制台启动中... 端口 8100")
    uvicorn.run(
        app=app,
        host="127.0.0.1",
        port=8100,
    )

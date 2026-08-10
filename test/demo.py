#### 1.3.1 测试1
# test/fastapi/demo.py

import uvicorn
from fastapi import FastAPI
from tool.logger import logger
# 创建一个 FastAPI 应用实例
app = FastAPI()
# 摘要说明
@app.get("/", summary="第一个测试")
async def read_root():
    return {"Hello": "World"}


#### 1.3.2 测试2：参数解析
# test/fastapi/demo.py

# 访问 http://127.0.0.1:8000/items/5?q=somequery
# item_id: 路径参数 (自动转为 int)
# q: 查询参数 (可选，默认 None)
@app.get("/items/{item_id}", summary="获取指定参数")
async def read_item(item_id: int, q: str | None = None):
    return {"item_id": item_id, "q": q}


# 接收? skip=? & limit = ?
@app.get("/items", summary="分页")
async def read_item(skip: int = 0, limit: int = 10):
    return {"skip": skip, "limit": limit}




#### 1.3.3 测试3：类型检查和错误提示
# test/fastapi/demo.py

from pydantic import BaseModel   # 继承 BaseModel 好处：1.会自动校验你给的类型对不对
                                                    # 2.fastapi返回内容的时候自动转成json返给用户

# 定义数据模型
class Item(BaseModel):
    name: str
    price: float
    is_offer: bool = None

# POST 请求接收 JSON 数据
@app.post("/items/", summary="类型检查")
async def create_item(item: Item):
    # item 已经是验证过的 Item 对象
    # 如果客户端传来的 price 是字符串 "abc"，FastAPI 会自动报错
    return {"name": item.name, "price": item.price, "is_offer": item.is_offer}

# 数据验证的幕后英雄
#用户输入错误数据
#    ↓
#FastAPI 接收请求
#    ↓
#交给 Pydantic 验证  ← Pydantic 登场！
#    ↓
#Pydantic 发现类型不匹配
#    ↓
#生成详细的错误信息
#    ↓
#FastAPI 把错误信息返回给用户

# pydantic 的三大功劳：
# 功劳 1：自动类型检查
# 功劳 2：自动生成错误信息
# 功劳 3：自动类型转换（智能功能）




##### 常见的响应形式
# 用户给你发请求你给用户返回json
# test/fastapi/demo.py

# 1、路由处理函数返回一个 Pydantic 模型实例，FastAPI 将自动将其转换为 JSON 格式，并作为响应发送给客户端：
@app.post("/items/return", summary="返回 Pydantic 模型实例")
async def create_item(item: Item):
    return item

#2、使用 HTTPException 抛出异常，返回自定义的状态码和详细信息。
#以下实例在 item_id 为 42 会返回 404 状态码：
from fastapi import HTTPException

@app.delete("/items/{item_id}", summary="抛出异常")
async def read_item(item_id: int):
    if item_id == 42:
        raise HTTPException(status_code=404, detail="Item 找不到")
    return {"item_id": item_id}



##### JSONResponse（最常用）
# test/fastapi/demo.py

from fastapi.responses import JSONResponse

@app.get("/api/user")
async def get_user():
    # 等价于直接 return {"name": "张三", "age": 20}（FastAPI 自动转 JSONResponse）
    return JSONResponse(
        content={"name": "张三", "age": 20},
        status_code=200,  # 可选，默认 200
        headers={"X-Custom-Header": "custom-value"}  # 可选，自定义响应头
    )




##### FileResponse（文件专用）
# test/fastapi/demo.py

from fastapi.responses import FileResponse

@app.get("/download/excel")
async def download_excel():
    excel_path = "D:/output/baby.xls"
    # 返回文件并指定下载文件名
    return FileResponse(
        path=excel_path,
        filename="baby.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )




##### HTMLResponse（HTML直接渲染页面）
# test/fastapi/demo.py

from fastapi.responses import HTMLResponse

@app.get("/hello")
async def hello(name: str = "游客"):
    html_content = f"""
    <html>
        <body>
            <h1>你好，{name}！</h1>
        </body>
    </html>
    """
    return HTMLResponse(content=html_content, status_code=200)




##### PlainTextResponse（纯文本）
# test/fastapi/demo.py

from fastapi.responses import PlainTextResponse

@app.get("/text")
async def get_text():
    return PlainTextResponse(content="这是纯文本响应", status_code=200)


##### RedirectResponse（重定向）
# test/fastapi/demo.py

from fastapi.responses import RedirectResponse

@app.get("/old-path")
async def redirect_old_path():
    # 重定向到 /new-path，状态码 307 表示临时重定向
    return RedirectResponse(url="/new-path", status_code=307)

@app.get("/new-path")
async def new_path():
    return {"message": "这是新接口"}



##### StreamingResponse（流式响应）
# test/fastapi/demo.py

from fastapi.responses import StreamingResponse
import asyncio

async def generate_stream():
    # 模拟流式输出（逐字返回）
    words = ["你", "好", "，", "这", "是", "流", "式", "响", "应"]
    for word in words:
        await asyncio.sleep(0.5)
        yield word.encode("utf-8")  # 流式输出需返回字节流

@app.get("/stream")
async def stream_response():
    return StreamingResponse(generate_stream(), media_type="text/event-stream")



##### Response（基础响应类）
# test/fastapi/demo.py

from fastapi.responses import Response

@app.get("/custom")
async def custom_response():
    # 返回二进制数据，指定自定义 MIME 类型
    return Response(
        content="<h1>纯文本</h1>",
        # media_type="text/text",
        media_type="text/html",
        status_code=200)





# **使用以下方式启动可以进行断点调试：**
# test/fastapi/demo.py

if __name__ == "__main__":
    """服务启动入口：本地开发环境直接运行"""
    logger.info("File Import Service 服务启动中...")
    # 启动uvicorn服务，绑定本地IP和8000端口，关闭自动重载（生产环境建议用workers多进程）
    uvicorn.run(
        app=app,
        host="127.0.0.1",  # 仅本地访问，生产环境改为0.0.0.0（允许所有IP访问）
        port=8000  # 服务端口
    )
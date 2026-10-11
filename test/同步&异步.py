# test/fastapi/同步&异步.py

import time

def download_file(name):
    print(f"开始下载：{name}")
    time.sleep(2)  # 模拟下载耗时 2 秒（整个程序卡住2秒，阻塞）
    print(f"下载完成：{name}")

download_file("文件 1")



# test/fastapi/同步&异步.py
import time

def download_file(name):
    print(f"开始下载：{name}")
    time.sleep(2)  # 模拟下载耗时 2 秒
    print(f"下载完成：{name}")

# 逐个下载
time_begin = time.time()
download_file("文件 1")
download_file("文件 2")
download_file("文件 3")
time_end = time.time()

# 总耗时：6 秒（2+2+2）
print(f"总耗时：{time_end - time_begin} 秒")

# test/fastapi/异步1.py
import asyncio

async def download_file(name):
    print(f"开始下载：{name}")
    await asyncio.sleep(2)  # 模拟下载耗时 2 秒（让出控制权2秒，非阻塞）
    print(f"下载完成：{name}")

asyncio.run(download_file("文件 1"))



# test/fastapi/异步2.py

import asyncio
import time


async def download_file(name):
    print(f"开始下载：{name}")
    await asyncio.sleep(2)  # 模拟下载耗时 2 秒
    print(f"下载完成：{name}")

async def main():
    # 三个任务同时开始！
    await asyncio.gather(
        download_file("文件 1"),
        download_file("文件 2"),
        download_file("文件 3")
    )

time_begin = time.time()
asyncio.run(main())
time_end = time.time()

# 总耗时：约 2 秒（同时进行）
print(f"总耗时：{time_end - time_begin} 秒")



# \test\fastapi\async_sync.py

from fastapi import FastAPI

app = FastAPI()

# ✅ 异步版本
@app.get("/simple-async")
async def simple_async():
    return {"message": "Hello"}

# ✅ 同步版本
@app.get("/simple-sync")
def simple_sync():
    return {"message": "Hello"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)

# uv run uvicorn test.import.fastapi.async_sync:app --reload



# \test\fastapi\async.py

import asyncio

from fastapi import FastAPI

app = FastAPI()

# ✅ 正确：异步函数可以用 await
@app.get("/fetch-data")
async def fetch_data():
    # 模拟耗时操作（如查数据库）
    await asyncio.sleep(1) # 让出CPU
    return {"data": "完成"}

# ❌ 错误：同步函数不能用 await
# @app.get("/fetch-data")
# def fetch_data():  # 少了 async
#     await asyncio.sleep(1)  # SyntaxError!
#     return {"data": "完成"}

# ⚠️ 勉强能用但不好：同步函数做耗时操作会阻塞
@app.get("/fetch-data-bad")
def fetch_data_bad():
    import time
    time.sleep(1)  # 阻塞整个线程
    return {"data": "完成"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)

# uv run uvicorn test.import.fastapi.async:app --reload


from fastapi import FastAPI

app = FastAPI()


# ✅ 推荐：即使现在不需要 await，以后可能需要
@app.get("/users/{user_id}")
async def get_user(user_id: int):
    # 现在很简单
    return {"user_id": user_id}

    # 以后如果要查数据库，直接加 await 就行
    # user = await db.query(user_id)
    # return user

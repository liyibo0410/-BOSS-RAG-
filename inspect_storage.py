"""
检视 BOSS 智库三个后端的当前已存内容（只读，不修改任何数据）。
依赖项目依赖：minio / pymilvus / pymongo / python-dotenv。
运行：.venv/Scripts/python.exe inspect_storage.py
"""
import os
import sys

from dotenv import load_dotenv

# 显式指定 .env 路径，避免 stdin 模式下 load_dotenv() 的 AssertionError
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from config.minio_config import minio_config
from config.milvus_config import milvus_config
from utils.minio_utils import get_minio_client
from utils.milvus_utils import get_milvus_client


def section(title: str):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def inspect_minio():
    section(f"[1] MinIO  桶={minio_config.bucket_name}  endpoint={minio_config.endpoint}")
    try:
        client = get_minio_client()
        if not client.bucket_exists(minio_config.bucket_name):
            print(f"  ⚠️ 桶 {minio_config.bucket_name} 不存在（还未上传过文件）")
            return
        objs = list(client.list_objects(minio_config.bucket_name, recursive=True))
        if not objs:
            print("  （桶为空，还没有文件）")
            return
        total = 0
        for o in objs:
            size = o.size or 0
            total += size
            print(f"  - {o.object_name}   ({size/1024:.1f} KB)")
        print(f"\n  共 {len(objs)} 个对象，合计 {total/1024/1024:.2f} MB")
    except Exception as e:
        print(f"  ❌ MinIO 连接失败：{e}")


def inspect_milvus():
    section(f"[2] Milvus  url={milvus_config.milvus_url}")
    try:
        client = get_milvus_client()
        for coll in [milvus_config.chunks_collection, milvus_config.item_name_collection]:
            print(f"\n  --- 集合 {coll} ---")
            if not client.has_collection(coll):
                print("  （集合不存在，还未导入过知识）")
                continue
            stats = client.get_collection_stats(coll)
            row_count = stats.get("row_count", stats.get("rowCount", "?"))
            print(f"  行数(row_count) = {row_count}")
            # 抽样前 1 条，看看字段长啥样
            try:
                rows = client.query(coll, filter="", output_fields=["*"], limit=1)
                if rows:
                    r = rows[0]
                    # 向量字段太长，截断打印
                    for k, v in r.items():
                        sv = str(v)
                        if len(sv) > 120:
                            sv = sv[:120] + f"...(len={len(str(v))})"
                        print(f"    {k}: {sv}")
            except Exception as qe:
                print(f"  （抽样读取失败：{qe}）")
    except Exception as e:
        print(f"  ❌ Milvus 连接失败：{e}")


def inspect_mongo():
    section(f"[3] MongoDB  url={os.getenv('MONGO_URL')}  db={os.getenv('MONGO_DB_NAME')}")
    try:
        from pymongo import MongoClient
        client = MongoClient(os.getenv("MONGO_URL"), serverSelectionTimeoutMS=5000)
        db = client[os.getenv("MONGO_DB_NAME")]
        cols = db.list_collection_names()
        if not cols:
            print("  （库为空）")
            return
        for c in cols:
            n = db[c].estimated_document_count()
            print(f"  - 集合 {c}: {n} 条")
        # 抽样对话记录
        if "chat_message" in cols:
            print("\n  最近 3 条对话记录示例：")
            for doc in db["chat_message"].find().sort("_id", -1).limit(3):
                sid = doc.get("session_id", "?")
                role = doc.get("role", "?")
                content = str(doc.get("content", ""))[:80]
                print(f"    session={sid} role={role}: {content}")
    except Exception as e:
        print(f"  ❌ MongoDB 连接失败：{e}")


if __name__ == "__main__":
    inspect_minio()
    inspect_milvus()
    inspect_mongo()
    print("\n完成。")

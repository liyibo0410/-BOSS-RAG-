from __future__ import annotations

"""
.env 配置连通性自检脚本。

逐项校验 .env 中的密钥/地址是否可用（真实发起一次最小请求），
并输出 [PASS]/[FAIL]/[SKIP] 汇总表，便于在运行主程序或评估前快速定位环境问题。

用法：
    python check_env.py              # 检查全部
    python check_env.py llm milvus   # 只检查指定项（空格分隔）
    python check_env.py --list       # 列出所有可检查项

可检查项：envfile、llm、embedding、milvus、mongo、minio、reranker
"""

import os
import queue
import sys
import threading
from pathlib import Path
from typing import Callable

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(override=True)

# 单项检查的默认超时（秒），避免某个服务不可用导致脚本长时间卡住
DEFAULT_TIMEOUT = 30

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"


def run_with_timeout(func: Callable[[], str], seconds: int = DEFAULT_TIMEOUT) -> tuple[str, str]:
    """
    在守护线程中执行检查函数，并限制最长等待时间。
    超时的线程无法被强制杀死，但线程为守护线程，主进程退出时会被回收。
    :param func: 无参检查函数，成功时返回说明信息，失败时抛出异常
    :param seconds: 最长等待秒数
    :return: (状态, 说明信息)
    """
    result_queue: queue.Queue = queue.Queue()

    def _target() -> None:
        try:
            result_queue.put((PASS, func()))
        except Exception as exc:  # noqa: BLE001 - 诊断脚本需要捕获所有异常
            # 只保留异常首行，避免超长的 traceback 刷屏
            result_queue.put((FAIL, f"{type(exc).__name__}: {str(exc).splitlines()[0]}"))

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    try:
        return result_queue.get(timeout=seconds)
    except queue.Empty:
        return FAIL, f"超时（超过 {seconds} 秒未响应）"


def _mask(value: str | None) -> str:
    """
    对密钥做脱敏展示，只保留前 3 位和后 4 位。
    :param value: 原始密钥
    :return: 脱敏后的字符串
    """
    if not value:
        return "<未配置>"
    if len(value) <= 8:
        return "***"
    return f"{value[:3]}***{value[-4:]}"


def check_envfile() -> str:
    """
    检查 .env 文件是否存在，并报告关键配置项是否已填写。
    :return: 检查结果说明
    """
    env_file = PROJECT_ROOT / ".env"
    if not env_file.is_file():
        raise FileNotFoundError(
            f"未找到 {env_file}，请复制 .env.example 为 .env 并填写配置"
        )

    required_keys = [
        "OPENAI_API_KEY",
        "OPENAI_API_BASE",
        "LLM_DEFAULT_MODEL",
        "MILVUS_URL",
        "MONGO_URL",
        "BGE_M3_PATH",
        "MINIO_ENDPOINT",
    ]
    missing = [key for key in required_keys if not os.getenv(key)]
    if missing:
        raise ValueError(f".env 已加载，但以下配置项为空: {', '.join(missing)}")
    return f".env 已加载，关键配置项齐全（API_KEY={_mask(os.getenv('OPENAI_API_KEY'))}）"


def check_llm() -> str:
    """
    检查大模型服务连通性：用默认模型与商品识别模型各发一次最小文本请求。
    :return: 检查结果说明
    """
    from utils.llm_utils import get_llm_client

    from config.lm_config import lm_config

    if not lm_config.api_key:
        raise ValueError("未配置 OPENAI_API_KEY")

    reply = get_llm_client().invoke("回复两个字：正常")
    content = (getattr(reply, "content", "") or "").strip()
    detail = f"base_url={lm_config.base_url}, model={lm_config.llm_model}, 回复={content[:20]!r}"

    # 商品识别模型（导入流程使用）一并验证，失败只提示不阻断
    item_model = lm_config.item_model
    if item_model and item_model != lm_config.llm_model:
        try:
            get_llm_client(model=item_model).invoke("回复两个字：正常")
            detail += f"；item_model={item_model} 可用"
        except Exception as exc:  # noqa: BLE001
            detail += f"；item_model={item_model} 不可用（{type(exc).__name__}）"
    return detail


def check_embedding() -> str:
    """
    检查 BGE-M3 嵌入模型可用性：先校验本地模型路径，再对一条短文本做真实向量化。
    :return: 检查结果说明
    """
    from config.embedding_config import embedding_config

    model_path = embedding_config.bge_m3_path
    if not model_path:
        raise ValueError("未配置 BGE_M3_PATH")
    if not Path(model_path).exists():
        raise FileNotFoundError(f"BGE_M3_PATH 指向的路径不存在: {model_path}")

    from utils.embedding_utils import generate_embeddings

    result = generate_embeddings(["连通性测试"])
    if not result or not result.get("dense"):
        raise RuntimeError("BGE-M3 未返回稠密向量")

    dim = len(result["dense"][0])
    return f"模型路径={model_path}, device={embedding_config.bge_device}, 向量维度={dim}"


def check_milvus() -> str:
    """
    检查 Milvus 服务连通性，并确认知识库所需的两个集合是否存在。
    :return: 检查结果说明
    """
    from pymilvus import MilvusClient

    from config.milvus_config import milvus_config

    if not milvus_config.milvus_url:
        raise ValueError("未配置 MILVUS_URL")

    client = MilvusClient(uri=milvus_config.milvus_url, timeout=10)
    collections = set(client.list_collections())

    detail = f"url={milvus_config.milvus_url}, 现有集合={sorted(collections) or '无'}"
    # 集合缺失只提示，首次运行时尚未导入数据属正常
    for name in (milvus_config.chunks_collection, milvus_config.item_name_collection):
        if name and name not in collections:
            detail += f"；集合 {name} 尚未创建（需先导入数据）"
    return detail


def check_mongo() -> str:
    """
    检查 MongoDB 服务连通性：执行 ping 命令验证认证与网络。
    :return: 检查结果说明
    """
    from pymongo import MongoClient

    url = os.getenv("MONGO_URL")
    db_name = os.getenv("MONGO_DB_NAME")
    if not url:
        raise ValueError("未配置 MONGO_URL")

    client = MongoClient(url, serverSelectionTimeoutMS=8000, connectTimeoutMS=8000)
    try:
        client.admin.command("ping")
        return f"url={url}, db={db_name}, ping 成功"
    finally:
        client.close()


def check_minio() -> str:
    """
    检查 MinIO 对象存储连通性：验证密钥可用并确认桶存在。
    :return: 检查结果说明
    """
    from minio import Minio

    endpoint = os.getenv("MINIO_ENDPOINT")
    bucket = os.getenv("MINIO_BUCKET_NAME")
    access_key = os.getenv("MINIO_ACCESS_KEY")
    if not endpoint:
        raise ValueError("未配置 MINIO_ENDPOINT")
    if not access_key:
        raise ValueError("未配置 MINIO_ACCESS_KEY")

    client = Minio(
        endpoint=endpoint,
        access_key=access_key,
        secret_key=os.getenv("MINIO_SECRET_KEY"),
        secure=False,
    )
    exists = client.bucket_exists(bucket) if bucket else False
    return f"endpoint={endpoint}, key={_mask(access_key)}, bucket={bucket} 存在={exists}"


def check_reranker() -> str:
    """
    检查 DashScope 重排序模型连通性：对两条短文本发起一次真实 rerank 请求。
    :return: 检查结果说明
    """
    import dashscope

    from config.reranker_config import reranker_config

    if not reranker_config.text_rerank_api_key:
        raise ValueError("未配置 MCP_API_KEY（DashScope API Key）")
    if not reranker_config.text_rerank_model:
        raise ValueError("未配置 TEXT_RERANK_MODEL")

    dashscope.api_key = reranker_config.text_rerank_api_key
    response = dashscope.TextReRank.call(
        model=reranker_config.text_rerank_model,
        query="连通性测试",
        documents=["测试文档一", "测试文档二"],
        top_n=2,
        return_documents=False,
        instruct=reranker_config.text_rerank_instruct,
    )
    if response.get("status_code") != 200:
        raise RuntimeError(f"status_code={response.get('status_code')}, message={response.get('message')}")
    return f"model={reranker_config.text_rerank_model}, key={_mask(reranker_config.text_rerank_api_key)}"


# 检查项注册表：(名称, 说明, 检查函数, 是否必需)
CHECKS: list[tuple[str, str, Callable[[], str], bool]] = [
    ("envfile", ".env 文件与关键配置项", check_envfile, True),
    ("llm", "大模型 API（DashScope 兼容）", check_llm, True),
    ("embedding", "BGE-M3 本地嵌入模型", check_embedding, True),
    ("milvus", "Milvus 向量数据库", check_milvus, True),
    ("mongo", "MongoDB 历史库", check_mongo, False),
    ("minio", "MinIO 对象存储", check_minio, False),
    ("reranker", "DashScope 重排序模型", check_reranker, False),
]


def main() -> int:
    """
    执行连通性检查并打印汇总结果。
    :return: 进程退出码，存在必需项失败时为 1
    """
    args = sys.argv[1:]
    if "--list" in args:
        for name, desc, _, required in CHECKS:
            print(f"  {name:<10} {desc}{'（必需）' if required else '（可选）'}")
        return 0

    selected = [a for a in args if not a.startswith("-")]
    targets = [c for c in CHECKS if not selected or c[0] in selected]
    if selected:
        unknown = set(selected) - {c[0] for c in CHECKS}
        if unknown:
            print(f"未知检查项: {', '.join(sorted(unknown))}，可用 --list 查看")
            return 1

    print("=" * 68)
    print("开始检查 .env 配置连通性...")
    print("=" * 68)

    results: list[tuple[str, str, str, str, bool]] = []
    for name, desc, func, required in targets:
        print(f"\n[检查] {desc} ({name}) ...")
        status, detail = run_with_timeout(func)
        results.append((name, desc, status, detail, required))
        print(f"  -> [{status}] {detail}")

    print("\n" + "=" * 68)
    print("检查结果汇总")
    print("=" * 68)
    for name, _, status, _, required in results:
        flag = "必需" if required else "可选"
        print(f"  [{status}] {name:<10} {flag}")

    failed_required = [r[0] for r in results if r[2] == FAIL and r[4]]
    failed_optional = [r[0] for r in results if r[2] == FAIL and not r[4]]

    print("-" * 68)
    if failed_required:
        print(f"必需项未通过: {', '.join(failed_required)}")
        print("请先修复以上配置，再运行主程序或评估脚本。")
    else:
        print("所有必需项检查通过。")
    if failed_optional:
        print(f"可选项未通过（视使用场景而定）: {', '.join(failed_optional)}")
        print("  提示：离线批量评估只需 llm / embedding / milvus，Mongo 与 MinIO 可暂不启用。")
    print("=" * 68)

    return 1 if failed_required else 0


if __name__ == "__main__":
    sys.exit(main())

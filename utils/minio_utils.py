# utils/minio_utils.py

import json
import logging

from minio import Minio

from config.minio_config import minio_config
from processor.import_processor.base import setup_logging

setup_logging()# 日志的全局配置 激活

# MinIO 客户端单例（懒加载）
# 原实现在模块导入阶段就建连接并建桶，会带来两个问题：
# 1. 任何 import 本模块的程序都要等 MinIO 超时（实测约 30 秒）才能继续启动；
# 2. 连接失败时 minio_client 从未被赋值，后续 get_minio_client() 抛的是
#    NameError 而非明确的“MinIO 不可用”，排查困难。
# 改为首次调用时初始化，并给出可诊断的报错。
_minio_client: Minio | None = None
_minio_init_error: str | None = None

# 桶的公开读策略：允许匿名读取桶内对象，供前端直接访问图片
_BUCKET_POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {"AWS": "*"},
            "Action": "s3:GetObject",
            "Resource": f"arn:aws:s3:::{minio_config.bucket_name}/*",
        },
    ],
}


def _create_minio_client() -> Minio:
    """
    创建 MinIO 客户端，并确保目标桶存在且具备公开读策略。
    :return: 初始化完成的 MinIO 客户端
    """
    if not minio_config.endpoint:
        raise ValueError("未配置 MINIO_ENDPOINT，请检查 .env")
    if not minio_config.access_key or not minio_config.secret_key:
        raise ValueError("未配置 MINIO_ACCESS_KEY / MINIO_SECRET_KEY，请检查 .env")

    client = Minio(
        endpoint=minio_config.endpoint,# 地址
        access_key=minio_config.access_key,# 两个密钥
        secret_key=minio_config.secret_key,
        #是否强制启用HTTPS的加密链接方式，False：使用http；True：使用https
        secure=False
    )

    # 判断bucket是否存在，不存在则创建
    if not client.bucket_exists(minio_config.bucket_name):
        client.make_bucket(minio_config.bucket_name)

    # 设置当前bucket的访问权限
    client.set_bucket_policy(minio_config.bucket_name, json.dumps(_BUCKET_POLICY))
    return client


def get_minio_client() -> Minio:
    """
    获取 MinIO 客户端单例（懒加载）。
    首次调用时建立连接、建桶并设置访问策略；失败会记录原因并重试下一次调用。
    :return: 初始化完成的 MinIO 客户端
    :raises RuntimeError: MinIO 不可用时抛出，并附带上次失败原因
    """
    global _minio_client, _minio_init_error

    if _minio_client is not None:
        return _minio_client

    try:
        _minio_client = _create_minio_client()
    except Exception as e:
        _minio_init_error = str(e)
        logging.error(f"MinIO连接失败，错误原因：{e}")
        raise RuntimeError(
            f"MinIO 不可用（endpoint={minio_config.endpoint}）：{_minio_init_error}"
        ) from e

    return _minio_client

if __name__ == '__main__':
    get_minio_client()
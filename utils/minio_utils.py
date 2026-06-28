import json
import logging
import traceback

from minio import Minio
from minio.deleteobjects import DeleteObject

from processor.import_processor.config import get_config

logger = logging.getLogger(__name__)

_minio_client = None


def _create_minio_client():
    """创建 MinIO 客户端实例（延迟初始化）"""
    global _minio_client
    if _minio_client is not None:
        return _minio_client

    config = get_config()

    try:
        _minio_client = Minio(
            endpoint=config.minio_endpoint,
            access_key=config.minio_access_key,
            secret_key=config.minio_secret_key,
            secure=config.minio_secure,
        )
        logger.info(f"MinIO客户端实例创建成功，服务地址：{config.minio_endpoint}")

        found = _minio_client.bucket_exists(config.minio_bucket)
        if not found:
            _minio_client.make_bucket(config.minio_bucket)
            logger.info(f"存储桶 {config.minio_bucket} 不存在，已自动创建")
        else:
            logger.info(f"存储桶 {config.minio_bucket} 已存在，无需新建")

        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"AWS": "*"},
                    "Action": "s3:GetObject",
                    "Resource": f"arn:aws:s3:::{config.minio_bucket}/*",
                },
            ],
        }
        _minio_client.set_bucket_policy(config.minio_bucket, json.dumps(policy))
        logger.info("Bucket公开读权限配置完成，MinIO服务连通正常！")

    except Exception as e:
        err_stack = traceback.format_exc()
        logger.error(f"MinIO连接/初始化失败，错误信息：{e}\n完整异常堆栈：\n{err_stack}")
        _minio_client = None

    return _minio_client


def get_minio_client():
    """对外提供 MinIO 客户端（延迟初始化）"""
    return _create_minio_client()


def clean_minio_dir(minio_client: Minio, dir_path: str) -> None:
    """清理 MinIO 指定目录下的所有对象"""
    config = get_config()
    try:
        objects_to_delete = minio_client.list_objects(config.minio_bucket, dir_path, recursive=True)
        delete_list = [DeleteObject(obj.object_name) for obj in objects_to_delete]
        errors = minio_client.remove_objects(config.minio_bucket, delete_list)
        for error in errors:
            logger.error(f"删除对象错误：{error}")
    except Exception as e:
        logger.error(f"清理 MinIO 目录失败，错误原因：{e}")


def upload_to_minio(minio_client: Minio, local_path: str, object_name: str) -> str | None:
    """将本地文件上传至 MinIO，返回访问 URL"""
    config = get_config()
    try:
        ext = local_path.rsplit(".", 1)[-1].lower() if "." in local_path else "bin"
        minio_client.fput_object(
            bucket_name=config.minio_bucket,
            object_name=object_name,
            file_path=local_path,
            content_type=f"image/{ext}",
        )
        return config.get_minio_img_url(object_name)
    except Exception as e:
        logger.error(f"上传文件失败：{local_path}，错误：{e}")
        return None


if __name__ == '__main__':
    from processor.import_processor.base import setup_logging
    setup_logging()
    client = get_minio_client()
    if client:
        logger.info("===== MinIO客户端初始化测试通过 =====")
    else:
        logger.error("===== MinIO客户端初始化失败，请查看上方错误日志 =====")

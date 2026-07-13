import json
from minio import Minio
from app.conf.minio_config import minio_config
from app.core.logger import logger

_minio_client = None

def get_minio_client():
    global _minio_client
    if _minio_client is not None:
        return _minio_client

    try:
        _minio_client = Minio(
            endpoint=minio_config.endpoint,
            access_key=minio_config.access_key,
            secret_key=minio_config.secret_key,
            secure=False
        )

        bucket_name = minio_config.bucket_name
        if not _minio_client.bucket_exists(bucket_name):
            _minio_client.make_bucket(bucket_name)
            bucket_policy = {
                "Version": "2012-10-17",
                "Statement": [{
                    "Effect": "Allow",
                    "Principal": {"AWS": ["*"]},
                    "Action": ["s3:GetObject"],
                    "Resource": [f"arn:aws:s3:::{bucket_name}/*"]
                }]
            }
            _minio_client.set_bucket_policy(bucket_name, json.dumps(bucket_policy))
    except Exception as e:
        logger.warning(f"MinIO 连接失败，图片上传功能不可用: {e}")
        _minio_client = None

    return _minio_client

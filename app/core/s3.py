# app/core/s3.py
"""
S3 Storage Utility — Fulfillment Module

Provides upload, presigned-URL download, and delete operations against the
S3_FULFILLMENT_BUCKET.  Falls back to local filesystem storage when the bucket
env var is not set (development / CI environments).

Usage:
    from app.core.s3 import s3_upload, s3_presigned_url, s3_delete, s3_configured

    # Upload a Werkzeug FileStorage object:
    key = s3_upload(file_obj, stored_name, instance_id, request_id)

    # Get a short-lived download URL:
    url = s3_presigned_url(key)          # redirect user to this URL

    # Delete when a request is hard-deleted:
    s3_delete(key)
"""

import logging
import os

import boto3
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────────────────
_BUCKET = os.environ.get("S3_FULFILLMENT_BUCKET", "").strip()
_REGION = os.environ.get("S3_BUCKET_REGION", "us-east-1").strip()
_PRESIGN_TTL = 180   # seconds — presigned URL lifetime (3 minutes, HIPAA-aligned)


def s3_configured() -> bool:
    """Return True when a bucket name is set (i.e. S3 mode is active)."""
    return bool(_BUCKET)


def _client():
    """Return a boto3 S3 client. Uses the EB instance-profile IAM role."""
    return boto3.client("s3", region_name=_REGION)


def _build_key(instance_id: int, request_id: int, stored_name: str) -> str:
    """
    Build the S3 object key.
    Pattern: fulfillment/<instance_id>/<request_id>/<stored_name>
    """
    return f"fulfillment/{instance_id}/{request_id}/{stored_name}"


def s3_upload(file_obj, stored_name: str, instance_id: int, request_id: int) -> str:
    """
    Upload a file-like object to S3.

    Args:
        file_obj:     Werkzeug FileStorage (or any file-like with .read() / .seek()).
        stored_name:  UUID-based filename with extension (e.g. 'a1b2c3.pdf').
        instance_id:  Owning instance (used in key prefix for namespacing).
        request_id:   Fulfillment request ID (used in key prefix).

    Returns:
        The S3 object key string.

    Raises:
        RuntimeError: if the upload fails.
    """
    if not s3_configured():
        raise RuntimeError("S3_FULFILLMENT_BUCKET is not set.")

    key = _build_key(instance_id, request_id, stored_name)

    # Determine content type from extension
    import mimetypes
    content_type, _ = mimetypes.guess_type(stored_name)
    extra_args = {}
    if content_type:
        extra_args["ContentType"] = content_type

    try:
        file_obj.seek(0)
        _client().upload_fileobj(file_obj, _BUCKET, key, ExtraArgs=extra_args)
        logger.info(f"S3 upload: s3://{_BUCKET}/{key}")
        return key
    except (BotoCoreError, ClientError) as exc:
        logger.error(f"S3 upload failed for key {key}: {exc}")
        raise RuntimeError(f"S3 upload failed: {exc}") from exc


def s3_presigned_url(key: str, ttl: int = _PRESIGN_TTL) -> str:
    """
    Generate a presigned GET URL for an S3 object.

    Args:
        key:  S3 object key (as returned by s3_upload).
        ttl:  URL lifetime in seconds (default 5 minutes).

    Returns:
        HTTPS presigned URL string.

    Raises:
        RuntimeError: if URL generation fails.
    """
    try:
        url = _client().generate_presigned_url(
            "get_object",
            Params={"Bucket": _BUCKET, "Key": key},
            ExpiresIn=ttl,
        )
        return url
    except (BotoCoreError, ClientError) as exc:
        logger.error(f"S3 presign failed for key {key}: {exc}")
        raise RuntimeError(f"S3 presign failed: {exc}") from exc


def s3_delete(key: str) -> None:
    """
    Delete an object from S3.  Silently succeeds if the object does not exist.

    Args:
        key:  S3 object key.
    """
    if not s3_configured():
        return
    try:
        _client().delete_object(Bucket=_BUCKET, Key=key)
        logger.info(f"S3 delete: s3://{_BUCKET}/{key}")
    except (BotoCoreError, ClientError) as exc:
        # Non-fatal — log and continue
        logger.warning(f"S3 delete failed for key {key}: {exc}")

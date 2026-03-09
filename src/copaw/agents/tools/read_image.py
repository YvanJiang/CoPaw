# -*- coding: utf-8 -*-
"""Read image file and return ImageBlock for multimodal models.

Supports:
- Local file paths
- file:// URLs
- http(s):// URLs

Security:
- Only allows files from ~/.copaw/media/ directory
- Maximum file size: 20MB
"""
# flake8: noqa: E501
# pylint: disable=line-too-long,too-many-return-statements
import base64
import os
import mimetypes
from pathlib import Path
from urllib.parse import urlparse
from typing import Optional

import httpx

from agentscope.message import TextBlock, ImageBlock
from agentscope.tool import ToolResponse

from ...constant import WORKING_DIR


# Supported image formats and their MIME types
SUPPORTED_FORMATS = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}

# Image format magic numbers (file signatures) for validation
# Each entry: (offset, signature bytes)
IMAGE_MAGIC_SIGNATURES = {
    ".png": (0, b"\x89PNG\r\n\x1a\n"),
    ".jpg": (0, b"\xff\xd8\xff"),
    ".jpeg": (0, b"\xff\xd8\xff"),
    ".gif": (0, b"GIF87a"),  # Also matches GIF89a (first 6 bytes same)
    ".webp": (8, b"WEBP"),   # RIFF header at 0, WEBP at offset 8
    ".bmp": (0, b"BM"),
}

# Maximum file size: 20MB
MAX_FILE_SIZE = 20 * 1024 * 1024

# Allowed directory for local files
MEDIA_DIR = WORKING_DIR / "media"


def _get_media_type(file_path: str) -> Optional[str]:
    """Get MIME type from file extension.

    Args:
        file_path: Path to the file.

    Returns:
        MIME type string or None if unsupported.
    """
    ext = Path(file_path).suffix.lower()
    return SUPPORTED_FORMATS.get(ext)


def _validate_image_magic(file_path: str) -> tuple[bool, str]:
    """Validate that file content matches expected image format.

    Args:
        file_path: Path to the file.

    Returns:
        Tuple of (is_valid, error_message).
    """
    ext = Path(file_path).suffix.lower()

    if ext not in IMAGE_MAGIC_SIGNATURES:
        return (False, f"不支持的图片格式：{ext}")

    offset, signature = IMAGE_MAGIC_SIGNATURES[ext]

    try:
        with open(file_path, "rb") as f:
            # Read enough bytes to check signature
            header = f.read(offset + len(signature))

        if len(header) < offset + len(signature):
            return (False, "文件过小，无法验证格式")

        # Check signature at expected offset
        if header[offset:offset + len(signature)] != signature:
            # Special handling for GIF which has two variants
            if ext == ".gif" and header[0:6] in (b"GIF87a", b"GIF89a"):
                return (True, "")

            # Special handling for WEBP - check full signature
            if ext == ".webp" and header[0:4] == b"RIFF" and header[8:12] == b"WEBP":
                return (True, "")

            return (
                False,
                f"文件格式不匹配：文件扩展名为 {ext}，但内容不是有效的 {ext} 格式"
            )

        return (True, "")

    except Exception as e:
        return (False, f"读取文件验证失败：{e}")


def _validate_local_path(file_path: str) -> tuple[bool, str]:
    """Validate that a local file path is within allowed directory.

    Args:
        file_path: Absolute path to the file.

    Returns:
        Tuple of (is_valid, error_message).
    """
    try:
        resolved = Path(file_path).resolve()
        media_dir_resolved = MEDIA_DIR.resolve()

        # Check if path is within media directory
        try:
            resolved.relative_to(media_dir_resolved)
        except ValueError:
            return (
                False,
                f"安全限制: 只允许读取 ~/.copaw/media/ 目录下的文件。"
                f"请求的路径: {file_path}",
            )

        return (True, "")

    except Exception as e:
        return (False, f"路径解析错误: {e}")


def _parse_source(source: str) -> tuple[str, Optional[str], str]:
    """Parse image source into type and path/URL.

    Args:
        source: Image source (local path, file:// URL, or http(s):// URL).

    Returns:
        Tuple of (source_type, parsed_path_or_url, error_message).
        source_type is "local", "file_url", "http_url", or "unknown".
    """
    source = source.strip()

    # HTTP(S) URL
    if source.startswith(("http://", "https://")):
        return ("http_url", source, "")

    # file:// URL
    if source.startswith("file://"):
        # Remove file:// prefix and decode URL encoding
        path = source[7:]
        # Handle URL-encoded characters
        from urllib.parse import unquote

        path = unquote(path)
        return ("file_url", path, "")

    # Local path (check if it looks like a path)
    # Could be absolute or relative
    return ("local", source, "")


async def _fetch_http_image(url: str) -> tuple[bytes, str, str]:
    """Fetch image from HTTP URL.

    Args:
        url: HTTP(S) URL to fetch.

    Returns:
        Tuple of (image_data, media_type, error_message).
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, follow_redirects=True)
            response.raise_for_status()

            # Check content type
            content_type = response.headers.get("content-type", "")
            if not content_type.startswith("image/"):
                return (
                    b"",
                    "",
                    f"URL 返回的不是图片类型: {content_type}",
                )

            # Check size
            content_length = len(response.content)
            if content_length > MAX_FILE_SIZE:
                size_mb = content_length / (1024 * 1024)
                return (
                    b"",
                    "",
                    f"文件过大: {size_mb:.2f}MB，最大允许 20MB",
                )

            # Determine media type from content-type header
            media_type = content_type.split(";")[0].strip()

            return (response.content, media_type, "")

    except httpx.TimeoutException:
        return (b"", "", f"请求超时: {url}")
    except httpx.HTTPStatusError as e:
        return (b"", "", f"HTTP 错误: {e.response.status_code}")
    except Exception as e:
        return (b"", "", f"请求失败: {e}")


async def read_image(
    source: str,
) -> ToolResponse:
    """读取图片文件并返回 ImageBlock 给多模态模型。

    支持的格式: PNG, JPG, GIF, WEBP, BMP

    Args:
        source (`str`):
            图片来源，可以是:
            - 本地文件路径 (如 /Users/xxx/image.png)
            - file:// URL (如 file:///Users/xxx/image.png)
            - http(s):// URL (如 https://example.com/image.png)

            注意: 本地文件必须在 ~/.copaw/media/ 目录下，
            且大小不超过 20MB。

    Returns:
        `ToolResponse`: 包含 ImageBlock 或错误信息。
    """

    if not source:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text="错误: 未提供图片来源。",
                ),
            ],
        )

    source_type, parsed_source, error = _parse_source(source)
    if error:
        return ToolResponse(
            content=[
                TextBlock(type="text", text=f"错误: {error}"),
            ],
        )

    # Handle HTTP URLs
    if source_type == "http_url":
        image_data, media_type, error = await _fetch_http_image(parsed_source)
        if error:
            return ToolResponse(
                content=[
                    TextBlock(type="text", text=f"错误: {error}"),
                ],
            )

        # Encode to base64
        base64_data = base64.b64encode(image_data).decode("utf-8")

        return ToolResponse(
            content=[
                ImageBlock(
                    type="image",
                    source={
                        "type": "base64",
                        "media_type": media_type,
                        "data": base64_data,
                    },
                ),
            ],
        )

    # Handle local files and file:// URLs
    file_path = parsed_source

    # Resolve relative paths from MEDIA_DIR
    if not os.path.isabs(file_path):
        file_path = str(MEDIA_DIR / file_path)

    # Validate path security (before resolving symlinks)
    is_valid, error = _validate_local_path(file_path)
    if not is_valid:
        return ToolResponse(
            content=[
                TextBlock(type="text", text=f"错误：{error}"),
            ],
        )

    # Check file exists (use lexists to detect broken symlinks)
    if not os.path.lexists(file_path):
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"错误：文件不存在：{file_path}",
                ),
            ],
        )

    # Check for broken symlinks
    if os.path.islink(file_path) and not os.path.exists(file_path):
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"错误：符号链接指向不存在的位置：{file_path}",
                ),
            ],
        )

    # Resolve symlinks and validate the target path is still within media dir
    real_path = os.path.realpath(file_path)
    if real_path != os.path.abspath(file_path):
        # Path contains symlinks, validate the resolved path
        is_valid, error = _validate_local_path(real_path)
        if not is_valid:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text="安全限制：符号链接指向外部位置，只允许访问 ~/.copaw/media/ 目录内的文件"
                    ),
                ],
            )
        file_path = real_path

    if not os.path.isfile(file_path):
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"错误：路径不是文件：{file_path}",
                ),
            ],
        )

    # Check file format (extension)
    media_type = _get_media_type(file_path)
    if not media_type:
        supported = ", ".join(SUPPORTED_FORMATS.keys())
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"错误：不支持的图片格式。支持的格式：{supported}",
                ),
            ],
        )

    # Validate file content matches expected format (magic number check)
    is_valid, error = _validate_image_magic(file_path)
    if not is_valid:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"错误：{error}",
                ),
            ],
        )

    # Check file size
    file_size = os.path.getsize(file_path)
    if file_size > MAX_FILE_SIZE:
        size_mb = file_size / (1024 * 1024)
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"错误：文件过大 ({size_mb:.2f}MB)，最大允许 20MB。",
                ),
            ],
        )


    # Read and encode file
    try:
        with open(file_path, "rb") as f:
            image_data = f.read()

        base64_data = base64.b64encode(image_data).decode("utf-8")

        return ToolResponse(
            content=[
                ImageBlock(
                    type="image",
                    source={
                        "type": "base64",
                        "media_type": media_type,
                        "data": base64_data,
                    },
                ),
            ],
        )

    except Exception as e:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"错误: 读取文件失败: {e}",
                ),
            ],
        )
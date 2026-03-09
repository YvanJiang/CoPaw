# -*- coding: utf-8 -*-
"""Utilities for handling multimodal data (images, audio) in agent messages.

This module provides functions to convert local file paths and file:// URLs
to base64-encoded data suitable for LLM APIs.
"""
import base64
import logging
import mimetypes
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# MIME type mappings for common media formats
MIME_TYPE_MAP = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".mp3": "audio/mp3",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".opus": "audio/opus",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
}


def _get_media_type(file_path: str) -> str:
    """Get MIME type from file extension.

    Args:
        file_path: Path to the file.

    Returns:
        MIME type string, defaults to application/octet-stream.
    """
    ext = Path(file_path).suffix.lower()
    return MIME_TYPE_MAP.get(
        ext,
        mimetypes.guess_type(file_path)[0] or "application/octet-stream",
    )


def _strip_file_url(url: str) -> str:
    """Strip file:// prefix from URL.

    Args:
        url: URL that may start with file://

    Returns:
        Local file path.
    """
    if url.startswith("file://"):
        path = url[7:]  # Remove file:// prefix
        # Handle Windows paths like file:///C:/path
        if (
            len(path) >= 3
            and path.startswith("/")
            and path[1].isalpha()
            and path[2] == ":"
        ):
            path = path[1:]
        return path
    return url


def is_local_file_path(url: str) -> bool:
    """Check if URL is a local file path (file:// or absolute path).

    Args:
        url: URL or path to check.

    Returns:
        True if it's a local file path, False otherwise.
    """
    if not url or not isinstance(url, str):
        return False

    # Check for file:// URL
    if url.startswith("file://"):
        return True

    # Check for absolute path
    if url.startswith("/") or (len(url) > 1 and url[1] == ":"):
        # Unix absolute path or Windows drive letter path
        return not url.startswith(("http://", "https://", "data:"))

    return False


def file_to_base64(file_path: str) -> Optional[dict]:
    """Convert a local file to base64-encoded source dict.

    Args:
        file_path: Local file path or file:// URL.

    Returns:
        Dict with type, media_type, and data (base64), or None if failed.
    """
    try:
        # Strip file:// prefix if present
        local_path = _strip_file_url(file_path)

        # Check if file exists
        if not os.path.isfile(local_path):
            logger.warning(f"File not found: {local_path}")
            return None

        # Read file and encode to base64
        with open(local_path, "rb") as f:
            file_data = f.read()

        base64_data = base64.b64encode(file_data).decode("utf-8")
        media_type = _get_media_type(local_path)

        return {
            "type": "base64",
            "media_type": media_type,
            "data": base64_data,
        }
    except Exception as e:
        logger.warning(f"Failed to convert file to base64: {e}")
        return None


def convert_image_source_to_base64(source: dict) -> dict:
    """Convert image source dict to base64 if it's a local file.

    Args:
        source: Source dict with type and url/base64 data.

    Returns:
        Source dict, possibly converted to base64.
    """
    if not isinstance(source, dict):
        return source

    source_type = source.get("type")

    # If already base64, return as-is
    if source_type == "base64":
        return source

    # If URL type, check if it's a local file
    if source_type == "url":
        url = source.get("url", "")
        if is_local_file_path(url):
            base64_source = file_to_base64(url)
            if base64_source:
                return base64_source

    return source


def convert_media_blocks_to_base64(content_blocks: list) -> list:
    """Convert all local media blocks in content to base64.

    Args:
        content_blocks: List of content blocks (image, audio, video, file).

    Returns:
        List of blocks with local files converted to base64.
    """
    if not isinstance(content_blocks, list):
        return content_blocks

    result = []
    for block in content_blocks:
        if not isinstance(block, dict):
            result.append(block)
            continue

        block_type = block.get("type")

        # Process media blocks
        if block_type in ("image", "audio", "video", "file"):
            source = block.get("source", {})
            converted_source = convert_image_source_to_base64(source)

            if converted_source != source:
                # Create new block with converted source
                new_block = dict(block)
                new_block["source"] = converted_source
                result.append(new_block)
                continue

        result.append(block)

    return result

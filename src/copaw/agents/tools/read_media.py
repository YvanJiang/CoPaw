# -*- coding: utf-8 -*-
"""Read media file (image, video, audio) and return appropriate Block.

Supports:
- Local file paths (any location accessible by the system)
- file:// URLs
- http(s):// URLs

Media Types:
- Images: PNG, JPG, GIF, WEBP, BMP
- Videos: MP4, AVI, MOV, MKV, WEBM, FLV, WMV
- Audio: MP3, WAV, AAC, OGG, M4A, FLAC, WMA

Features:
- Image compression (using Pillow)
- Video compression with frame extraction (using FFmpeg)
- Automatic media type detection and appropriate Block return

Security:
- Maximum file size: 20MB (before compression)
- File content validation via magic numbers
"""
# flake8: noqa: E501
# pylint: disable=line-too-long,too-many-return-statements
import base64
import os
import tempfile
import asyncio
from pathlib import Path
from typing import Optional

import httpx

from agentscope.message import TextBlock, ImageBlock, AudioBlock, VideoBlock
from agentscope.tool import ToolResponse


# Supported media formats and their MIME types
SUPPORTED_FORMATS = {
    # Images
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    # Videos
    ".mp4": "video/mp4",
    ".avi": "video/x-msvideo",
    ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
    ".flv": "video/x-flv",
    ".wmv": "video/x-ms-wmv",
    # Audio
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".m4a": "audio/mp4",
    ".flac": "audio/flac",
    ".wma": "audio/x-ms-wma",
}

# File extension categories
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".flv", ".wmv"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".aac", ".ogg", ".m4a", ".flac", ".wma"}

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

# Video format magic numbers
VIDEO_MAGIC_SIGNATURES = {
    ".mp4": (4, b"ftyp"),  # ftyp box at offset 4
    ".avi": (0, b"RIFF"),  # RIFF header
    ".mov": (4, b"ftyp"),  # QuickTime uses ftyp
    ".mkv": (0, b"\x1a\x45\xdf\xa3"),  # EBML header
    ".webm": (0, b"\x1a\x45\xdf\xa3"),  # Same as MKV
    ".flv": (0, b"FLV"),
    ".wmv": (0, b"\x30\x26\xb2\x75"),  # ASF header
}

# Audio format magic numbers
AUDIO_MAGIC_SIGNATURES = {
    ".mp3": (0, b"\xff\xfb"),  # MPEG-1 Layer 3
    ".wav": (0, b"RIFF"),     # RIFF/WAVE
    ".aac": (0, b"\xff\xf1"),  # ADTS
    ".ogg": (0, b"OggS"),
    ".m4a": (4, b"ftyp"),      # Same as MP4
    ".flac": (0, b"fLaC"),
    ".wma": (0, b"\x30\x26\xb2\x75"),  # Same as WMV (ASF)
}

# Maximum file size: 20MB
MAX_FILE_SIZE = 20 * 1024 * 1024


def _get_media_type(file_path: str) -> Optional[str]:
    """Get MIME type from file extension.

    Args:
        file_path: Path to the file.

    Returns:
        MIME type string or None if unsupported.
    """
    ext = Path(file_path).suffix.lower()
    return SUPPORTED_FORMATS.get(ext)


def _check_special_format(ext: str, header: bytes) -> bool:
    """Check special format signatures for files with multiple variants.

    Args:
        ext: File extension.
        header: File header bytes.

    Returns:
        True if format is valid, False otherwise.
    """
    if ext == ".gif":
        return header[0:6] in (b"GIF87a", b"GIF89a")
    if ext == ".webp":
        return header[0:4] == b"RIFF" and header[8:12] == b"WEBP"
    if ext in (".mp4", ".mov", ".m4a"):
        return b"ftyp" in header[4:12]
    if ext == ".wav":
        return header[0:4] == b"RIFF" and b"WAVE" in header
    if ext == ".avi":
        return header[0:4] == b"RIFF" and b"AVI " in header
    return False


def _validate_media_magic(file_path: str) -> tuple[bool, str]:
    """Validate that file content matches expected format.

    Args:
        file_path: Path to the file.

    Returns:
        Tuple of (is_valid, error_message).
    """
    ext = Path(file_path).suffix.lower()

    # Get appropriate magic signatures based on extension
    if ext in IMAGE_EXTENSIONS:
        signatures = IMAGE_MAGIC_SIGNATURES
    elif ext in VIDEO_EXTENSIONS:
        signatures = VIDEO_MAGIC_SIGNATURES
    elif ext in AUDIO_EXTENSIONS:
        signatures = AUDIO_MAGIC_SIGNATURES
    else:
        return (False, f"不支持的媒体格式：{ext}")

    if ext not in signatures:
        # No magic signature validation for this format
        return (True, "")

    offset, signature = signatures[ext]

    try:
        with open(file_path, "rb") as f:
            # Read enough bytes to check signature
            header = f.read(offset + len(signature) + 16)

        if len(header) < offset + len(signature):
            return (False, "文件过小，无法验证格式")

        # Check signature at expected offset
        actual_signature = header[offset:offset + len(signature)]

        # Special handling for formats with multiple variants
        if _check_special_format(ext, header):
            return (True, "")

        if actual_signature == signature:
            return (True, "")

        return (
            False,
            f"文件格式不匹配：文件扩展名为 {ext}，但内容不是有效的 {ext} 格式"
        )

    except Exception as e:
        return (False, f"读取文件验证失败：{e}")


def _parse_source(source: str) -> tuple[str, Optional[str], str]:
    """Parse media source into type and path/URL.

    Args:
        source: Media source (local path, file:// URL, or http(s):// URL).

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
    return ("local", source, "")


async def _fetch_http_media(url: str) -> tuple[bytes, str, str]:
    """Fetch media from HTTP URL.

    Args:
        url: HTTP(S) URL to fetch.

    Returns:
        Tuple of (media_data, media_type, error_message).
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, follow_redirects=True)
            response.raise_for_status()

            # Check content type
            content_type = response.headers.get("content-type", "")

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


def _compress_image(
    input_path: str,
    output_path: str,
    target_size_mb: float
) -> bool:
    """Compress image to target size using Pillow.

    Args:
        input_path: Path to input image.
        output_path: Path to save compressed image.
        target_size_mb: Target file size in MB.

    Returns:
        True if compression succeeded and file is within target size.
    """
    try:
        from PIL import Image
    except ImportError:
        return False

    target_bytes = target_size_mb * 1024 * 1024
    quality = 95

    try:
        with Image.open(input_path) as img:
            # Convert to RGB if necessary (handle RGBA, P, LA modes)
            if img.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                if img.mode in ('RGBA', 'LA'):
                    background.paste(
                        img,
                        mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None
                    )
                    img = background
                else:
                    img = img.convert('RGB')
            elif img.mode != 'RGB':
                img = img.convert('RGB')

            # Try reducing quality first
            while quality >= 20:
                img.save(output_path, "JPEG", optimize=True, quality=quality)
                if os.path.getsize(output_path) <= target_bytes:
                    return True
                quality -= 5

            # If quality reduction isn't enough, also resize
            if os.path.getsize(output_path) > target_bytes:
                ratio = 0.8
                while ratio > 0.3:
                    new_size = (int(img.width * ratio), int(img.height * ratio))
                    resized = img.resize(new_size, Image.Resampling.LANCZOS)
                    resized.save(output_path, "JPEG", optimize=True, quality=75)
                    if os.path.getsize(output_path) <= target_bytes:
                        return True
                    ratio -= 0.1

        return os.path.getsize(output_path) <= target_bytes
    except Exception:
        return False


async def _compress_video(
    input_path: str,
    output_path: str,
    target_size_mb: float,
    fps: int = 1
) -> bool:
    """Compress video using FFmpeg with optional frame extraction.

    Args:
        input_path: Path to input video.
        output_path: Path to save compressed video.
        target_size_mb: Target file size in MB.
        fps: Frames per second to extract (1 = 1 frame per second).
             Use 0 to keep original frame rate.

    Returns:
        True if compression succeeded.
    """
    # Calculate CRF based on target size (higher = more compression)
    # 5MB -> CRF 28, 10MB -> CRF 26, etc.
    crf = max(18, min(28, int(28 - (target_size_mb - 5) / 5 * 2)))

    # Build FFmpeg command
    cmd = [
        "ffmpeg",
        "-y",  # Overwrite output
        "-i", input_path,
        "-c:v", "libx264",
        "-crf", str(crf),
        "-preset", "slow",  # Better compression ratio
        "-c:a", "aac",      # Audio codec
        "-b:a", "64k",      # Low audio bitrate
        "-movflags", "+faststart",
    ]

    # Add frame rate filter if specified
    if fps > 0:
        cmd.extend(["-vf", f"fps={fps}"])
        cmd.extend(["-r", str(fps)])  # Output frame rate

    cmd.append(output_path)

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        _, _ = await process.communicate()

        if process.returncode != 0:
            return False

        # Check if output file exists and is smaller
        if not os.path.exists(output_path):
            return False

        return True
    except Exception:
        return False


def _get_file_category(file_path: str) -> str:
    """Get the category of file (image, video, audio).

    Args:
        file_path: Path to the file.

    Returns:
        Category string: "image", "video", "audio", or "unknown".
    """
    ext = Path(file_path).suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        return "image"
    elif ext in VIDEO_EXTENSIONS:
        return "video"
    elif ext in AUDIO_EXTENSIONS:
        return "audio"
    return "unknown"


async def read_media(
    source: str,
    compress: bool = True,
    max_size_mb: float = 5.0,
    video_fps: int = 1,
) -> ToolResponse:
    """读取媒体文件（图片、视频、音频）并返回对应的 Block。

    支持图片、视频和音频格式，自动进行压缩以适应模型输入限制。

    Args:
        source (`str`):
            媒体文件来源，可以是:
            - 本地文件路径 (如 /Users/xxx/video.mp4)
            - file:// URL (如 file:///Users/xxx/audio.mp3)
            - http(s):// URL (如 https://example.com/image.png)

        compress (`bool`):
            是否启用压缩（默认 True）。对于大文件，压缩可以减小大小
            以适应模型输入限制。

        max_size_mb (`float`):
            压缩后的目标文件大小上限（MB），默认 5MB。
            原始文件超过 20MB 时返回错误。

        video_fps (`int`):
            视频抽帧参数，表示每秒保留多少帧（默认 1）。
            - 1 = 每秒1帧（适合分析视频内容）
            - 5 = 每秒5帧（更流畅）
            - 0 = 不抽帧，保留原帧率
            抽帧可以显著减小视频文件大小。

    Returns:
        `ToolResponse`: 包含适当的 Block (ImageBlock, VideoBlock, AudioBlock)
                       或错误信息。

    Examples:
        >>> # 读取本地图片
        >>> await read_media("/path/to/photo.png")

        >>> # 读取视频并抽帧（每秒2帧）
        >>> await read_media("/path/to/video.mp4", video_fps=2)

        >>> # 从URL读取音频
        >>> await read_media("https://example.com/audio.mp3")

        >>> # 禁用压缩
        >>> await read_media("/path/to/small.gif", compress=False)
    """
    if not source:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text="错误: 未提供媒体文件来源。",
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
        media_data, media_type, error = await _fetch_http_media(parsed_source)
        if error:
            return ToolResponse(
                content=[
                    TextBlock(type="text", text=f"错误: {error}"),
                ],
            )

        # Encode to base64
        base64_data = base64.b64encode(media_data).decode("utf-8")

        # Try to determine block type from media_type
        if media_type.startswith("image/"):
            block = ImageBlock(
                type="image",
                source={
                    "type": "base64",
                    "media_type": media_type,
                    "data": base64_data,
                },
            )
        elif media_type.startswith("video/"):
            block = VideoBlock(
                type="video",
                source={
                    "type": "base64",
                    "media_type": media_type,
                    "data": base64_data,
                },
            )
        elif media_type.startswith("audio/"):
            block = AudioBlock(
                type="audio",
                source={
                    "type": "base64",
                    "media_type": media_type,
                    "data": base64_data,
                },
            )
        else:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=f"错误: 不支持的媒体类型: {media_type}"
                    ),
                ],
            )

        return ToolResponse(content=[block])

    # Handle local files and file:// URLs
    file_path = parsed_source
    if file_path is None:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text="错误：无法解析媒体文件来源",
                ),
            ],
        )

    # Resolve to absolute path
    if not os.path.isabs(file_path):
        file_path = os.path.abspath(file_path)

    # Check file exists
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

    # Resolve symlinks
    file_path = os.path.realpath(file_path)

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
                    text=f"错误：不支持的媒体格式。支持的格式：{supported}",
                ),
            ],
        )

    # Validate file content matches expected format
    is_valid, error = _validate_media_magic(file_path)
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

    # Determine file category
    category = _get_file_category(file_path)

    # Handle compression if enabled and file is large
    file_to_read = file_path
    was_compressed = False
    temp_file = None

    if compress and file_size > max_size_mb * 1024 * 1024:
        if category == "image":
            # Create temp file for compressed image
            fd, temp_file = tempfile.mkstemp(suffix=".jpg")
            os.close(fd)

            if _compress_image(file_path, temp_file, max_size_mb):
                file_to_read = temp_file
                was_compressed = True
            else:
                # Compression failed, use original
                os.unlink(temp_file)
                temp_file = None

        elif category == "video":
            # Create temp file for compressed video
            fd, temp_file = tempfile.mkstemp(suffix=".mp4")
            os.close(fd)

            if await _compress_video(file_path, temp_file, max_size_mb, video_fps):
                file_to_read = temp_file
                was_compressed = True
                # Update media type for compressed video
                media_type = "video/mp4"
            else:
                # Compression failed, use original
                os.unlink(temp_file)
                temp_file = None
        # Audio compression not implemented yet

    try:
        # Read and encode file
        with open(file_to_read, "rb") as f:
            media_data = f.read()

        base64_data = base64.b64encode(media_data).decode("utf-8")

        # Build info text
        final_size_mb = len(media_data) / (1024 * 1024)
        info_text = f"已加载媒体文件: {os.path.basename(source)} ({final_size_mb:.2f}MB)"
        if was_compressed:
            info_text += " [已压缩]"
        if category == "video" and video_fps != 1 and video_fps > 0:
            info_text += f" [抽帧: {video_fps}fps]"

        # Create appropriate block based on category
        if category == "image":
            block = ImageBlock(
                type="image",
                source={
                    "type": "base64",
                    "media_type": media_type,
                    "data": base64_data,
                },
            )
        elif category == "video":
            block = VideoBlock(
                type="video",
                source={
                    "type": "base64",
                    "media_type": media_type,
                    "data": base64_data,
                },
            )
        elif category == "audio":
            block = AudioBlock(
                type="audio",
                source={
                    "type": "base64",
                    "media_type": media_type,
                    "data": base64_data,
                },
            )
        else:
            return ToolResponse(
                content=[
                    TextBlock(type="text", text="错误：无法识别的媒体类型"),
                ],
            )

        return ToolResponse(content=[
            TextBlock(type="text", text=info_text),
            block,
        ])

    except Exception as e:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"错误: 读取文件失败: {e}",
                ),
            ],
        )
    finally:
        # Clean up temp file if created
        if temp_file and os.path.exists(temp_file):
            try:
                os.unlink(temp_file)
            except Exception:
                pass

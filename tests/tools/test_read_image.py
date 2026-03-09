# -*- coding: utf-8 -*-
"""Unit tests for read_image tool."""
import base64
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from copaw.agents.tools.read_image import (
    read_image,
    _parse_source,
    _validate_local_path,
    _get_media_type,
    MEDIA_DIR,
    MAX_FILE_SIZE,
    SUPPORTED_FORMATS,
)


# Test fixtures
@pytest.fixture
def media_dir(tmp_path: Path):
    """Create a temporary media directory for testing."""
    media = tmp_path / "media"
    media.mkdir()
    # Patch MEDIA_DIR for tests
    with patch("copaw.agents.tools.read_image.MEDIA_DIR", media):
        yield media


@pytest.fixture
def sample_png(media_dir: Path):
    """Create a sample PNG file for testing."""
    # Minimal valid PNG (1x1 transparent pixel)
    png_data = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    )
    png_path = media_dir / "test.png"
    png_path.write_bytes(png_data)
    return png_path


@pytest.fixture
def sample_jpg(media_dir: Path):
    """Create a sample JPG file for testing."""
    # Minimal valid JPEG (1x1 white pixel) - properly padded base64
    jpg_data = base64.b64decode(
        "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP///////////////////////////////////"
        "////////////////////////////////////////////////////////////////"
        "/////////////////////////////////////////////////////////////wAALCAACAgBARE"
        "A/8QAFQAAAQUBAQEAAAAAAAAAAAAAAAIDAQQFBgcICf/aAAgBAQABBQKb"
        "pqD/2gAIAQAAAQUFpmmo/9oACAEBAAEFAlD/2gAIAQIBAQFwUf/aAAgBAwEB"
        "AXBR/9oADAMBEQCEAaEAAX//2Q=="
    )
    jpg_path = media_dir / "test.jpg"
    jpg_path.write_bytes(jpg_data)
    return jpg_path


class TestGetMediaType:
    """Tests for _get_media_type function."""

    def test_png_extension(self):
        """Test PNG format detection."""
        assert _get_media_type("test.png") == "image/png"
        assert _get_media_type("test.PNG") == "image/png"
        assert _get_media_type("/path/to/image.png") == "image/png"

    def test_jpg_extension(self):
        """Test JPG format detection."""
        assert _get_media_type("test.jpg") == "image/jpeg"
        assert _get_media_type("test.jpeg") == "image/jpeg"
        assert _get_media_type("test.JPG") == "image/jpeg"

    def test_gif_extension(self):
        """Test GIF format detection."""
        assert _get_media_type("test.gif") == "image/gif"

    def test_webp_extension(self):
        """Test WEBP format detection."""
        assert _get_media_type("test.webp") == "image/webp"

    def test_bmp_extension(self):
        """Test BMP format detection."""
        assert _get_media_type("test.bmp") == "image/bmp"

    def test_unsupported_format(self):
        """Test unsupported format returns None."""
        assert _get_media_type("test.txt") is None
        assert _get_media_type("test.pdf") is None
        assert _get_media_type("test.svg") is None

    def test_no_extension(self):
        """Test file without extension returns None."""
        assert _get_media_type("testfile") is None


class TestValidateLocalPath:
    """Tests for _validate_local_path function."""

    def test_valid_path_in_media_dir(self, media_dir: Path):
        """Test path within media directory is valid."""
        file_path = str(media_dir / "image.png")
        is_valid, error = _validate_local_path(file_path)
        assert is_valid is True
        assert error == ""

    def test_path_outside_media_dir(self, media_dir: Path, tmp_path: Path):
        """Test path outside media directory is invalid."""
        outside_path = str(tmp_path / "outside.png")
        is_valid, error = _validate_local_path(outside_path)
        assert is_valid is False
        assert "安全限制" in error

    def test_path_traversal_attempt(self, media_dir: Path):
        """Test path traversal attack is blocked."""
        traversal_path = str(media_dir / ".." / "outside.png")
        is_valid, error = _validate_local_path(traversal_path)
        assert is_valid is False
        assert "安全限制" in error


class TestParseSource:
    """Tests for _parse_source function."""

    def test_http_url(self):
        """Test HTTP URL parsing."""
        source_type, parsed, error = _parse_source("http://example.com/image.png")
        assert source_type == "http_url"
        assert parsed == "http://example.com/image.png"
        assert error == ""

    def test_https_url(self):
        """Test HTTPS URL parsing."""
        source_type, parsed, error = _parse_source("https://example.com/image.png")
        assert source_type == "http_url"
        assert parsed == "https://example.com/image.png"
        assert error == ""

    def test_file_url(self):
        """Test file:// URL parsing."""
        source_type, parsed, error = _parse_source("file:///Users/test/image.png")
        assert source_type == "file_url"
        assert parsed == "/Users/test/image.png"
        assert error == ""

    def test_file_url_encoded(self):
        """Test file:// URL with encoded characters."""
        source_type, parsed, error = _parse_source(
            "file:///Users/test%20folder/image.png"
        )
        assert source_type == "file_url"
        assert parsed == "/Users/test folder/image.png"
        assert error == ""

    def test_local_path(self):
        """Test local path parsing."""
        source_type, parsed, error = _parse_source("/Users/test/image.png")
        assert source_type == "local"
        assert parsed == "/Users/test/image.png"
        assert error == ""

    def test_relative_path(self):
        """Test relative path parsing."""
        source_type, parsed, error = _parse_source("image.png")
        assert source_type == "local"
        assert parsed == "image.png"
        assert error == ""


class TestReadImage:
    """Tests for read_image async function."""

    @pytest.mark.asyncio
    async def test_empty_source(self):
        """Test empty source returns error."""
        response = await read_image("")
        assert len(response.content) == 1
        assert response.content[0]["type"] == "text"
        assert "未提供" in response.content[0]["text"]

    @pytest.mark.asyncio
    async def test_read_png_file(self, sample_png: Path):
        """Test reading a valid PNG file."""
        response = await read_image(str(sample_png))
        assert len(response.content) == 1
        assert response.content[0]["type"] == "image"
        assert response.content[0]["source"]["type"] == "base64"
        assert response.content[0]["source"]["media_type"] == "image/png"
        # Verify it's valid base64
        data = response.content[0]["source"]["data"]
        assert base64.b64decode(data) is not None

    @pytest.mark.asyncio
    async def test_read_jpg_file(self, sample_jpg: Path):
        """Test reading a valid JPG file."""
        response = await read_image(str(sample_jpg))
        assert len(response.content) == 1
        assert response.content[0]["type"] == "image"
        assert response.content[0]["source"]["media_type"] == "image/jpeg"

    @pytest.mark.asyncio
    async def test_file_url(self, sample_png: Path):
        """Test reading image via file:// URL."""
        file_url = f"file://{sample_png}"
        response = await read_image(file_url)
        assert len(response.content) == 1
        assert response.content[0]["type"] == "image"
        assert response.content[0]["source"]["media_type"] == "image/png"

    @pytest.mark.asyncio
    async def test_nonexistent_file(self, media_dir: Path):
        """Test reading nonexistent file returns error."""
        response = await read_image(str(media_dir / "nonexistent.png"))
        assert response.content[0]["type"] == "text"
        assert "不存在" in response.content[0]["text"]

    @pytest.mark.asyncio
    async def test_unsupported_format(self, media_dir: Path):
        """Test reading unsupported format returns error."""
        txt_file = media_dir / "test.txt"
        txt_file.write_text("not an image")
        response = await read_image(str(txt_file))
        assert response.content[0]["type"] == "text"
        assert "不支持" in response.content[0]["text"]

    @pytest.mark.asyncio
    async def test_file_too_large(self, media_dir: Path):
        """Test reading file larger than 20MB returns error."""
        # Create a file slightly larger than 20MB with valid PNG header
        # PNG signature: 89 50 4E 47 0D 0A 1A 0A
        png_header = b"\x89PNG\r\n\x1a\n"
        large_file = media_dir / "large.png"
        large_file.write_bytes(png_header + b"\x00" * (MAX_FILE_SIZE + 1))

        response = await read_image(str(large_file))
        assert response.content[0]["type"] == "text"
        assert "过大" in response.content[0]["text"]

    @pytest.mark.asyncio
    async def test_directory_instead_of_file(self, media_dir: Path):
        """Test reading directory returns error."""
        subdir = media_dir / "subdir"
        subdir.mkdir()
        response = await read_image(str(subdir))
        assert response.content[0]["type"] == "text"
        assert "不是文件" in response.content[0]["text"]

    @pytest.mark.asyncio
    async def test_path_outside_media_dir(self, tmp_path: Path):
        """Test reading file outside media directory returns security error."""
        outside_file = tmp_path / "outside.png"
        outside_file.write_bytes(b"fake png data")
        response = await read_image(str(outside_file))
        assert response.content[0]["type"] == "text"
        assert "安全限制" in response.content[0]["text"]

    @pytest.mark.asyncio
    async def test_relative_path(self, media_dir: Path):
        """Test relative path resolution."""
        # Create a file in media dir
        png_data = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        )
        (media_dir / "relative.png").write_bytes(png_data)

        # Test relative path (should resolve from MEDIA_DIR)
        with patch("copaw.agents.tools.read_image.MEDIA_DIR", media_dir):
            response = await read_image("relative.png")
            assert response.content[0]["type"] == "image"

    @pytest.mark.asyncio
    async def test_http_url_success(self, sample_png: Path):
        """Test fetching image from HTTP URL."""
        png_data = sample_png.read_bytes()
        mock_response = AsyncMock()
        mock_response.content = png_data
        mock_response.headers = {"content-type": "image/png"}
        mock_response.raise_for_status = AsyncMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            response = await read_image("https://example.com/test.png")
            assert response.content[0]["type"] == "image"
            assert response.content[0]["source"]["media_type"] == "image/png"

    @pytest.mark.asyncio
    async def test_http_url_non_image_content(self):
        """Test HTTP URL returning non-image content returns error."""
        mock_response = AsyncMock()
        mock_response.content = b"not an image"
        mock_response.headers = {"content-type": "text/html"}
        mock_response.raise_for_status = AsyncMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            response = await read_image("https://example.com/test.png")
            assert response.content[0]["type"] == "text"
            assert "不是图片类型" in response.content[0]["text"]

    @pytest.mark.asyncio
    async def test_http_url_too_large(self):
        """Test HTTP URL with file too large returns error."""
        mock_response = AsyncMock()
        mock_response.content = b"\x00" * (MAX_FILE_SIZE + 1)
        mock_response.headers = {"content-type": "image/png"}
        mock_response.raise_for_status = AsyncMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            response = await read_image("https://example.com/large.png")
            assert response.content[0]["type"] == "text"
            assert "过大" in response.content[0]["text"]

    @pytest.mark.asyncio
    async def test_symlink_to_outside_file(self, media_dir: Path, tmp_path: Path):
        """Test symlink pointing to file outside media dir is blocked."""
        # Create a file outside media dir
        outside_file = tmp_path / "outside.png"
        outside_file.write_bytes(b"fake data")
        
        # Create symlink in media dir pointing to outside file
        symlink_path = media_dir / "link_to_outside.png"
        if symlink_path.exists() or symlink_path.is_symlink():
            symlink_path.unlink()
        symlink_path.symlink_to(outside_file)
        
        response = await read_image(str(symlink_path))
        assert response.content[0]["type"] == "text"
        assert "安全限制" in response.content[0]["text"]

    @pytest.mark.asyncio
    async def test_broken_symlink(self, media_dir: Path):
        """Test broken symlink returns error."""
        # Create symlink pointing to non-existent file
        symlink_path = media_dir / "broken_link.png"
        if symlink_path.exists() or symlink_path.is_symlink():
            symlink_path.unlink()
        symlink_path.symlink_to(media_dir / "nonexistent.png")
        
        response = await read_image(str(symlink_path))
        assert response.content[0]["type"] == "text"
        assert "符号链接" in response.content[0]["text"] or "不存在" in response.content[0]["text"]

    @pytest.mark.asyncio
    async def test_magic_number_mismatch(self, media_dir: Path):
        """Test file with wrong magic number (extension vs content mismatch) is rejected."""
        # Create a file with .png extension but invalid PNG content
        fake_png = media_dir / "fake.png"
        fake_png.write_bytes(b"This is not a PNG file at all!")
        
        response = await read_image(str(fake_png))
        assert response.content[0]["type"] == "text"
        assert "格式" in response.content[0]["text"] or "文件" in response.content[0]["text"]

    @pytest.mark.asyncio
    async def test_jpg_with_png_extension(self, media_dir: Path):
        """Test JPEG file renamed to .png is rejected."""
        # Create a minimal JPEG file
        jpg_data = base64.b64decode(
            "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////"
        )
        # Save with .png extension
        fake_png = media_dir / "jpg_as_png.png"
        fake_png.write_bytes(jpg_data)
        
        response = await read_image(str(fake_png))
        assert response.content[0]["type"] == "text"
        # Should be rejected because magic number doesn't match PNG
        assert "格式" in response.content[0]["text"] or "文件" in response.content[0]["text"]


class TestConstants:
    """Tests for module constants."""

    def test_max_file_size(self):
        """Test max file size is 20MB."""
        assert MAX_FILE_SIZE == 20 * 1024 * 1024

    def test_supported_formats(self):
        """Test all required formats are supported."""
        required = [".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"]
        for fmt in required:
            assert fmt in SUPPORTED_FORMATS

    def test_media_dir(self):
        """Test media directory path."""
        assert MEDIA_DIR.name == "media"
        assert ".copaw" in str(MEDIA_DIR)
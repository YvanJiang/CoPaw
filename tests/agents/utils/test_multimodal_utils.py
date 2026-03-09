# -*- coding: utf-8 -*-
"""Tests for multimodal utilities."""
import base64
import os
import tempfile
from pathlib import Path

import pytest

from copaw.agents.utils.multimodal_utils import (
    file_to_base64,
    is_local_file_path,
    convert_image_source_to_base64,
    convert_media_blocks_to_base64,
)


class TestFileToBase64:
    """Tests for file_to_base64 function."""

    def test_file_to_base64_with_valid_image(self):
        """Test converting a valid image file to base64."""
        # Create a temporary file with PNG magic bytes
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            # PNG file header
            f.write(b"\x89PNG\r\n\x1a\n")
            f.write(b"fake image data")
            temp_path = f.name

        try:
            result = file_to_base64(temp_path)
            assert result["type"] == "base64"
            assert result["media_type"] == "image/png"
            assert "data" in result
            # Verify base64 data is valid
            decoded = base64.b64decode(result["data"])
            assert decoded.startswith(b"\x89PNG")
        finally:
            os.unlink(temp_path)

    def test_file_to_base64_with_audio_file(self):
        """Test converting an audio file to base64."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"fake mp3 data")
            temp_path = f.name

        try:
            result = file_to_base64(temp_path)
            assert result["type"] == "base64"
            assert result["media_type"] == "audio/mp3"
        finally:
            os.unlink(temp_path)

    def test_file_to_base64_file_not_found(self):
        """Test handling of non-existent file."""
        result = file_to_base64("/nonexistent/path/file.png")
        assert result is None

    def test_file_to_base64_with_file_url(self):
        """Test converting file:// URL to base64."""
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"\xff\xd8\xff")  # JPEG magic bytes
            f.write(b"fake jpeg data")
            temp_path = f.name

        try:
            file_url = f"file://{temp_path}"
            result = file_to_base64(file_url)
            assert result["type"] == "base64"
            assert result["media_type"] == "image/jpeg"
        finally:
            os.unlink(temp_path)


class TestIsLocalFilePath:
    """Tests for is_local_file_path function."""

    def test_detects_file_url(self):
        """Test detection of file:// URLs."""
        assert is_local_file_path("file:///path/to/image.png") is True

    def test_detects_absolute_path(self):
        """Test detection of absolute file paths."""
        assert is_local_file_path("/path/to/image.png") is True
        assert is_local_file_path("C:\\Users\\image.png") is True

    def test_detects_http_url(self):
        """Test that HTTP URLs are not local."""
        assert is_local_file_path("https://example.com/image.png") is False
        assert is_local_file_path("http://example.com/image.png") is False

    def test_detects_data_url(self):
        """Test that data URLs are not local."""
        assert is_local_file_path("data:image/png;base64,ABC123") is False


class TestConvertImageSourceToBase64:
    """Tests for convert_image_source_to_base64 function."""

    def test_converts_local_file_to_base64(self):
        """Test converting local file path to base64 source."""
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNG\r\n\x1a\n")
            f.write(b"fake data")
            temp_path = f.name

        try:
            source = {"type": "url", "url": temp_path}
            result = convert_image_source_to_base64(source)
            assert result["type"] == "base64"
            assert "data" in result
            assert result["media_type"] == "image/png"
        finally:
            os.unlink(temp_path)

    def test_keeps_http_url_unchanged(self):
        """Test that HTTP URLs are kept as-is."""
        source = {"type": "url", "url": "https://example.com/image.png"}
        result = convert_image_source_to_base64(source)
        assert result == source  # Should return unchanged

    def test_keeps_base64_unchanged(self):
        """Test that base64 sources are kept as-is."""
        source = {
            "type": "base64",
            "media_type": "image/png",
            "data": "ABC123",
        }
        result = convert_image_source_to_base64(source)
        assert result == source


class TestConvertMediaBlocksToBase64:
    """Tests for convert_media_blocks_to_base64 function."""

    def test_converts_image_blocks(self):
        """Test converting image blocks to base64."""
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNG\r\n\x1a\nfake png data")
            temp_path = f.name

        try:
            blocks = [
                {"type": "image", "source": {"type": "url", "url": temp_path}},
            ]
            result = convert_media_blocks_to_base64(blocks)
            assert result[0]["source"]["type"] == "base64"
        finally:
            os.unlink(temp_path)

    def test_keeps_text_blocks_unchanged(self):
        """Test that text blocks are not modified."""
        blocks = [{"type": "text", "text": "Hello world"}]
        result = convert_media_blocks_to_base64(blocks)
        assert result == blocks

    def test_handles_mixed_blocks(self):
        """Test handling mixed content blocks."""
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNG\r\n\x1a\n")
            temp_path = f.name

        try:
            blocks = [
                {"type": "text", "text": "Hello"},
                {"type": "image", "source": {"type": "url", "url": temp_path}},
                {"type": "text", "text": "World"},
            ]
            result = convert_media_blocks_to_base64(blocks)
            assert result[0]["type"] == "text"
            assert result[1]["source"]["type"] == "base64"
            assert result[2]["type"] == "text"
        finally:
            os.unlink(temp_path)

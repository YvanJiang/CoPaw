# -*- coding: utf-8 -*-
"""Tests for message_processing utilities."""
import os
import tempfile

import pytest

from copaw.agents.utils.message_processing import (
    _update_block_with_local_path,
)


class TestUpdateBlockWithLocalPath:
    """Tests for _update_block_with_local_path function."""

    def test_image_block_converted_to_base64(self):
        """Test that image blocks can be converted to base64."""
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNG\r\n\x1a\nfake png data")
            temp_path = f.name

        try:
            block = {
                "type": "image",
                "source": {
                    "type": "url",
                    "url": "http://example.com/image.png",
                },
            }

            # With convert_to_base64=True
            result = _update_block_with_local_path(
                block,
                "image",
                temp_path,
                convert_to_base64=True,
            )

            assert result["source"]["type"] == "base64"
            assert "data" in result["source"]
            assert result["source"]["media_type"] == "image/png"
        finally:
            os.unlink(temp_path)

    def test_image_block_keeps_file_url(self):
        """Test that image blocks can keep file:// URL (backward compatible).

        This ensures backward compatibility with file:// URL handling.
        """
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNG\r\n\x1a\nfake png data")
            temp_path = f.name

        try:
            block = {
                "type": "image",
                "source": {
                    "type": "url",
                    "url": "http://example.com/image.png",
                },
            }

            # With convert_to_base64=False (default)
            result = _update_block_with_local_path(
                block,
                "image",
                temp_path,
                convert_to_base64=False,
            )

            assert result["source"]["type"] == "url"
            assert result["source"]["url"].startswith("file://")
        finally:
            os.unlink(temp_path)

    def test_audio_block_converted_to_base64(self):
        """Test that audio blocks can be converted to base64."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"fake mp3 data")
            temp_path = f.name

        try:
            block = {
                "type": "audio",
                "source": {
                    "type": "url",
                    "url": "http://example.com/audio.mp3",
                },
            }

            result = _update_block_with_local_path(
                block,
                "audio",
                temp_path,
                convert_to_base64=True,
            )

            assert result["source"]["type"] == "base64"
            assert result["source"]["media_type"] == "audio/mp3"
        finally:
            os.unlink(temp_path)

    def test_file_block_not_converted(self):
        """Test that file blocks are not converted to base64."""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"fake text data")
            temp_path = f.name

        try:
            # Test without existing filename - should use basename
            block = {
                "type": "file",
                "source": "http://example.com/file.txt",
            }

            result = _update_block_with_local_path(
                block,
                "file",
                temp_path,
                convert_to_base64=True,
            )

            # File blocks should just store the local path
            assert result["source"] == temp_path
            assert result["filename"] == os.path.basename(temp_path)
        finally:
            os.unlink(temp_path)

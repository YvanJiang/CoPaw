"""Tests for model factory and FileBlockSupportFormatter."""
import pytest
from unittest.mock import Mock, patch, AsyncMock
import tempfile
import os

from copaw.agents.model_factory import (
    _create_file_block_support_formatter,
)
from agentscope.formatter import OpenAIChatFormatter


class TestFileBlockSupportFormatterMultimodal:
    """Tests for FileBlockSupportFormatter multimodal handling."""

    @pytest.fixture
    def formatter(self):
        """Create a formatter instance for testing."""
        formatter_class = _create_file_block_support_formatter(
            OpenAIChatFormatter
        )
        return formatter_class()

    @pytest.mark.asyncio
    async def test_converts_local_image_to_base64(self, formatter):
        """Test that local image paths are converted to base64."""
        # Create a temporary image file
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNG\r\n\x1a\n")
            f.write(b"fake image data")
            temp_path = f.name

        try:
            # Create a mock message with local image
            mock_msg = Mock()
            mock_msg.role = "user"
            mock_msg.content = [
                {"type": "image", "source": {"type": "url", "url": temp_path}}
            ]
            mock_msg.get_content_blocks.return_value = mock_msg.content
            mock_msg.name = "test"

            # Mock parent _format to capture what's passed to it
            with patch.object(
                OpenAIChatFormatter, "_format", new_callable=AsyncMock
            ) as mock_parent_format:
                mock_parent_format.return_value = [
                    {"role": "user", "content": []}
                ]

                await formatter._format([mock_msg])

                # Verify parent _format was called
                assert mock_parent_format.called

                # Get the messages passed to parent
                call_args = mock_parent_format.call_args
                msgs = call_args[0][0]

                # Verify the image was converted to base64
                content = msgs[0].content
                assert content[0]["type"] == "image"
                assert content[0]["source"]["type"] == "base64"
                assert "data" in content[0]["source"]
        finally:
            os.unlink(temp_path)

    @pytest.mark.asyncio
    async def test_keeps_http_image_url_unchanged(self, formatter):
        """Test that HTTP image URLs are not converted."""
        mock_msg = Mock()
        mock_msg.role = "user"
        mock_msg.content = [
            {
                "type": "image",
                "source": {
                    "type": "url",
                    "url": "https://example.com/image.png",
                },
            }
        ]
        mock_msg.get_content_blocks.return_value = mock_msg.content
        mock_msg.name = "test"

        with patch.object(
            OpenAIChatFormatter, "_format", new_callable=AsyncMock
        ) as mock_parent_format:
            mock_parent_format.return_value = [
                {"role": "user", "content": []}
            ]

            await formatter._format([mock_msg])

            call_args = mock_parent_format.call_args
            msgs = call_args[0][0]
            content = msgs[0].content

            # HTTP URLs should remain unchanged
            assert content[0]["type"] == "image"
            assert content[0]["source"]["type"] == "url"
            assert (
                content[0]["source"]["url"]
                == "https://example.com/image.png"
            )

    @pytest.mark.asyncio
    async def test_converts_file_url_to_base64(self, formatter):
        """Test that file:// URLs are converted to base64."""
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"\xff\xd8\xff")  # JPEG magic
            f.write(b"fake jpeg data")
            temp_path = f.name

        try:
            file_url = f"file://{temp_path}"

            mock_msg = Mock()
            mock_msg.role = "user"
            mock_msg.content = [
                {"type": "image", "source": {"type": "url", "url": file_url}}
            ]
            mock_msg.get_content_blocks.return_value = mock_msg.content
            mock_msg.name = "test"

            with patch.object(
                OpenAIChatFormatter, "_format", new_callable=AsyncMock
            ) as mock_parent_format:
                mock_parent_format.return_value = [
                    {"role": "user", "content": []}
                ]

                await formatter._format([mock_msg])

                call_args = mock_parent_format.call_args
                msgs = call_args[0][0]
                content = msgs[0].content

                assert content[0]["source"]["type"] == "base64"
                assert "data" in content[0]["source"]
        finally:
            os.unlink(temp_path)

    @pytest.mark.asyncio
    async def test_handles_multiple_media_blocks(self, formatter):
        """Test handling multiple media blocks in one message."""
        with tempfile.NamedTemporaryFile(
            suffix=".png", delete=False
        ) as f1, tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f2:
            f1.write(b"\x89PNG\r\n\x1a\nfake png")
            f2.write(b"\xff\xd8\xfffake jpeg")
            temp_path1 = f1.name
            temp_path2 = f2.name

        try:
            mock_msg = Mock()
            mock_msg.role = "user"
            mock_msg.content = [
                {"type": "text", "text": "Here are two images:"},
                {
                    "type": "image",
                    "source": {"type": "url", "url": temp_path1},
                },
                {
                    "type": "image",
                    "source": {
                        "type": "url",
                        "url": "https://example.com/remote.png",
                    },
                },
                {
                    "type": "image",
                    "source": {"type": "url", "url": temp_path2},
                },
            ]
            mock_msg.get_content_blocks.return_value = mock_msg.content
            mock_msg.name = "test"

            with patch.object(
                OpenAIChatFormatter, "_format", new_callable=AsyncMock
            ) as mock_parent_format:
                mock_parent_format.return_value = [
                    {"role": "user", "content": []}
                ]

                await formatter._format([mock_msg])

                call_args = mock_parent_format.call_args
                msgs = call_args[0][0]
                content = msgs[0].content

                # Text block unchanged
                assert content[0]["type"] == "text"

                # Local file 1 converted to base64
                assert content[1]["source"]["type"] == "base64"

                # Remote URL unchanged
                assert content[2]["source"]["type"] == "url"
                assert (
                    content[2]["source"]["url"]
                    == "https://example.com/remote.png"
                )

                # Local file 2 converted to base64
                assert content[3]["source"]["type"] == "base64"
        finally:
            os.unlink(temp_path1)
            os.unlink(temp_path2)


class TestMonkeyPatchBehavior:
    """Tests for monkey patch behavior with local files."""

    def test_file_url_stripped_by_monkey_patch(self):
        """Test that file:// prefix is stripped by monkey patch."""
        from copaw.agents.model_factory import _file_url_to_path

        # Unix path
        assert (
            _file_url_to_path("file:///path/to/image.png")
            == "/path/to/image.png"
        )

        # Windows path
        assert (
            _file_url_to_path("file:///C:/Users/image.png")
            == "C:/Users/image.png"
        )

        # Already a path
        assert (
            _file_url_to_path("/path/to/image.png") == "/path/to/image.png"
        )

        # HTTP URL unchanged
        assert (
            _file_url_to_path("https://example.com/image.png")
            == "https://example.com/image.png"
        )

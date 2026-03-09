"""Integration tests for multimodal data flow from channel to formatter."""
import base64
import os
import tempfile
from unittest.mock import AsyncMock, Mock, patch

import pytest
from agentscope.formatter import OpenAIChatFormatter

from copaw.agents.utils.multimodal_utils import convert_media_blocks_to_base64
from copaw.agents.model_factory import _create_file_block_support_formatter


class TestMultimodalEndToEnd:
    """End-to-end tests for multimodal data flow."""

    @pytest.mark.asyncio
    async def test_local_image_flow_to_formatter(self):
        """Test complete flow: local image file → base64 → formatter."""
        # Create a temporary image
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNG\r\n\x1a\n")
            f.write(b"fake image content here")
            temp_path = f.name

        try:
            # Step 1: Simulate channel creating content with local path
            content_blocks = [
                {"type": "image", "source": {"type": "url", "url": temp_path}}
            ]

            # Step 2: Convert to base64 (simulating formatter behavior)
            converted_blocks = convert_media_blocks_to_base64(content_blocks)

            # Verify conversion
            assert converted_blocks[0]["source"]["type"] == "base64"
            assert "data" in converted_blocks[0]["source"]
            assert converted_blocks[0]["source"]["media_type"] == "image/png"

            # Step 3: Verify base64 is valid
            decoded = base64.b64decode(converted_blocks[0]["source"]["data"])
            assert decoded.startswith(b"\x89PNG")

            # Step 4: Test formatter integration
            formatter_class = _create_file_block_support_formatter(
                OpenAIChatFormatter
            )
            formatter = formatter_class()

            mock_msg = Mock()
            mock_msg.role = "user"
            mock_msg.content = content_blocks
            mock_msg.get_content_blocks.return_value = content_blocks
            mock_msg.name = "test"

            with patch.object(
                OpenAIChatFormatter, "_format", new_callable=AsyncMock
            ) as mock_parent:
                mock_parent.return_value = [{"role": "user", "content": []}]
                await formatter._format([mock_msg])

                # Verify formatter received base64 content
                call_args = mock_parent.call_args
                msgs = call_args[0][0]
                assert msgs[0].content[0]["source"]["type"] == "base64"

        finally:
            os.unlink(temp_path)

    @pytest.mark.asyncio
    async def test_http_image_unchanged(self):
        """Test that HTTP images are not converted to base64."""
        content_blocks = [
            {
                "type": "image",
                "source": {
                    "type": "url",
                    "url": "https://example.com/image.png",
                },
            }
        ]

        # Conversion should not change HTTP URLs
        converted_blocks = convert_media_blocks_to_base64(content_blocks)

        assert converted_blocks[0]["source"]["type"] == "url"
        assert (
            converted_blocks[0]["source"]["url"]
            == "https://example.com/image.png"
        )

        # Test formatter also keeps it unchanged
        formatter_class = _create_file_block_support_formatter(
            OpenAIChatFormatter
        )
        formatter = formatter_class()

        mock_msg = Mock()
        mock_msg.role = "user"
        mock_msg.content = content_blocks
        mock_msg.get_content_blocks.return_value = content_blocks
        mock_msg.name = "test"

        with patch.object(
            OpenAIChatFormatter, "_format", new_callable=AsyncMock
        ) as mock_parent:
            mock_parent.return_value = [{"role": "user", "content": []}]
            await formatter._format([mock_msg])

            call_args = mock_parent.call_args
            msgs = call_args[0][0]
            assert msgs[0].content[0]["source"]["type"] == "url"
            assert (
                msgs[0].content[0]["source"]["url"]
                == "https://example.com/image.png"
            )

    def test_mixed_content_blocks(self):
        """Test handling mixed content with text, images, and audio."""
        with tempfile.NamedTemporaryFile(
            suffix=".png", delete=False
        ) as f1, tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f2:
            f1.write(b"\x89PNG\r\n\x1a\n")
            f2.write(b"fake mp3 data")
            img_path = f1.name
            audio_path = f2.name

        try:
            content_blocks = [
                {"type": "text", "text": "Here is an image:"},
                {"type": "image", "source": {"type": "url", "url": img_path}},
                {"type": "text", "text": "And audio:"},
                {
                    "type": "audio",
                    "source": {"type": "url", "url": audio_path},
                },
                {
                    "type": "image",
                    "source": {
                        "type": "url",
                        "url": "https://remote.com/img.png",
                    },
                },
            ]

            converted = convert_media_blocks_to_base64(content_blocks)

            # Text unchanged
            assert converted[0]["type"] == "text"

            # Local image converted
            assert converted[1]["source"]["type"] == "base64"

            # Text unchanged
            assert converted[2]["type"] == "text"

            # Local audio converted
            assert converted[3]["source"]["type"] == "base64"

            # Remote image unchanged
            assert converted[4]["source"]["type"] == "url"

        finally:
            os.unlink(img_path)
            os.unlink(audio_path)

    @pytest.mark.asyncio
    async def test_file_url_converted_to_base64(self):
        """Test that file:// URLs are properly converted."""
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"\xff\xd8\xff")  # JPEG magic
            f.write(b"fake jpeg content")
            temp_path = f.name

        try:
            file_url = f"file://{temp_path}"
            content_blocks = [
                {"type": "image", "source": {"type": "url", "url": file_url}}
            ]

            # Convert
            converted = convert_media_blocks_to_base64(content_blocks)

            # Should be base64 now
            assert converted[0]["source"]["type"] == "base64"
            assert "data" in converted[0]["source"]

        finally:
            os.unlink(temp_path)

# -*- coding: utf-8 -*-
"""Feishu (Lark) Simple Notification Router.

Provides a simple HTTP endpoint to send messages to Feishu.
Uses environment variables for target configuration (chat_id or open_id).

Example usage:
    curl -X POST "http://localhost:8000/api/v1/notify/feishu?message=服务器报警"

Environment variables:
    FEISHU_NOTIFY_CHAT_ID: Target chat ID (group chat)
    FEISHU_NOTIFY_OPEN_ID: Target user open ID (private message)
"""

import json
import logging
import os
import time
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_feishu_channel(request: Request):
    """Get FeishuChannel instance from channel manager."""
    cm = getattr(request.app.state, "channel_manager", None)
    if cm is None:
        return None

    if hasattr(cm, "channels"):
        channels = cm.channels
        if isinstance(channels, dict):
            channel_iter = channels.values()
        else:
            channel_iter = channels
        for ch in channel_iter:
            if getattr(ch, "channel", None) == "feishu":
                return ch
    return None


@router.post("/v1/notify/feishu")
async def notify_feishu(
    request: Request,
    message: Optional[str] = None,
    source: Optional[str] = None,
) -> JSONResponse:
    """Send a simple text message to Feishu.

    Args:
        message: The message content to send (from query param or body)
        source: Source identifier for the message (default: "System")

    Environment:
        FEISHU_NOTIFY_CHAT_ID: Target chat ID for group messages
        FEISHU_NOTIFY_OPEN_ID: Target user ID for private messages

    Returns:
        JSONResponse with code and message

    Examples:
        # Query parameter with source
        curl -X POST "http://localhost:8000/api/v1/notify/feishu?message=测试消息&source=Zabbix"

        # JSON body with source
        curl -X POST http://localhost:8000/api/v1/notify/feishu \
          -H "Content-Type: application/json" \
          -d '{"message": "测试消息", "source": "Zabbix"}'

        # Pipe input
        echo "服务器报警" | curl -X POST -d @- \
          http://localhost:8000/api/v1/notify/feishu
    """
    # 1. Get target ID from environment variables
    chat_id = os.environ.get("FEISHU_NOTIFY_CHAT_ID")
    open_id = os.environ.get("FEISHU_NOTIFY_OPEN_ID")

    # 2. Validate configuration
    if not chat_id and not open_id:
        logger.warning("Feishu notify: FEISHU_NOTIFY_CHAT_ID or FEISHU_NOTIFY_OPEN_ID not set")
        return JSONResponse(
            content={
                "code": 400,
                "message": "FEISHU_NOTIFY_CHAT_ID or FEISHU_NOTIFY_OPEN_ID not set",
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    # Determine receive_id_type and receive_id
    if chat_id:
        receive_id_type = "chat_id"
        receive_id = chat_id
    else:
        receive_id_type = "open_id"
        receive_id = open_id

    # 3. Get message and source from query param, body, or raw body (pipe)
    if message is None or source is None:
        # Try to read from body
        try:
            body = await request.body()
            body_str = body.decode("utf-8").strip()

            # Try JSON parsing
            if body_str:
                try:
                    json_data = json.loads(body_str)
                    if isinstance(json_data, dict):
                        if message is None and "message" in json_data:
                            message = json_data["message"]
                        if source is None and "source" in json_data:
                            source = json_data["source"]
                    if message is None:
                        message = body_str
                except json.JSONDecodeError:
                    # Not JSON, use raw body as message
                    if message is None:
                        message = body_str
        except Exception as e:
            logger.warning(f"Failed to read request body: {e}")

    # 4. Validate message
    if not message or not message.strip():
        return JSONResponse(
            content={"code": 400, "message": "Message is required"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    message = message.strip()

    # 5. Format message with source identifier
    source_name = source or "System"
    formatted_message = f"[{source_name}] {message}"

    # 6. Get FeishuChannel instance
    feishu_channel = _get_feishu_channel(request)
    if feishu_channel is None:
        logger.error("Feishu notify: Feishu channel not found")
        return JSONResponse(
            content={"code": 503, "message": "Feishu channel not available"},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    # 7. Send message (dual sending: direct + agent processing)
    try:
        logger.info(
            f"Feishu notify: sending message to {receive_id_type}={receive_id[:20]}... "
            f"message_len={len(formatted_message)}"
        )

        # 7a. First send: Direct message to Feishu
        direct_result = await feishu_channel._send_text(
            receive_id_type=receive_id_type,
            receive_id=receive_id,
            body=formatted_message,
        )

        if not direct_result:
            logger.error("Feishu notify: _send_text returned False")
            return JSONResponse(
                content={"code": 500, "message": "Failed to send direct message"},
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # 7b. Second send: Simulate webhook event for agent processing
        # Determine chat type based on receive_id_type
        chat_type = "group" if receive_id_type == "chat_id" else "p2p"

        # Construct simulated webhook payload
        simulated_event = {
            "event": {
                "message": {
                    "message_id": f"simulated_{uuid.uuid4().hex}_{int(time.time())}",
                    "chat_id": chat_id or open_id,
                    "chat_type": chat_type,
                    "message_type": "text",
                    "content": json.dumps({"text": formatted_message}),
                },
                "sender": {
                    "sender_type": "user",
                    "sender_id": {"open_id": open_id or chat_id},
                    "name": source_name,
                    "nickname": source_name,
                },
            }
        }

        # Call handle_webhook_event for agent processing
        if hasattr(feishu_channel, 'handle_webhook_event'):
            await feishu_channel.handle_webhook_event(simulated_event)
            logger.info("Feishu notify: queued for agent processing via webhook event")
        else:
            logger.warning("Feishu notify: handle_webhook_event not available, skipping agent processing")

        return JSONResponse(
            content={
                "code": 0,
                "message": "Direct message sent and queued for agent processing",
            },
            status_code=status.HTTP_200_OK,
        )

    except Exception as e:
        logger.exception(f"Feishu notify: failed to send message: {e}")
        return JSONResponse(
            content={"code": 500, "message": f"Internal error: {str(e)}"},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

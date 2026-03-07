# -*- coding: utf-8 -*-
"""Feishu (Lark) Webhook Router.

Handles Feishu event subscriptions via HTTP webhook.
Supports challenge verification, signature verification, and event dispatching.
Reference: https://open.feishu.cn/document/ukTMukTMukTM/uYDNxYjL2QTM24iN0EjN/event-subscription-guide
"""

import base64
import hashlib
import hmac
import json
import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter()


def verify_signature(
    encrypt_key: str,
    timestamp: str,
    nonce: str,
    body: str,
    expected_signature: str,
) -> bool:
    """Verify Feishu webhook request signature.

    Args:
        encrypt_key: The encryption key configured in Feishu app
        timestamp: Request timestamp from header
        nonce: Request nonce from header
        body: Raw request body
        expected_signature: Expected signature from header

    Returns:
        True if signature is valid, False otherwise
    """
    if not encrypt_key:
        logger.warning("No encrypt_key configured, skipping signature verification")
        return True

    key = encrypt_key.encode("utf-8")
    msg = f"{timestamp}{nonce}{body}".encode("utf-8")

    computed = base64.b64encode(
        hmac.new(key, msg, hashlib.sha256).digest(),
    ).decode("utf-8")

    return hmac.compare_digest(computed, expected_signature)


def decrypt_body(encrypt_key: str, encrypted_body: str) -> str:
    """Decrypt Feishu webhook payload (if encryption is enabled).

    Args:
        encrypt_key: The encryption key
        encrypted_body: Base64-encoded encrypted payload

    Returns:
        Decrypted JSON string
    """
    if not encrypted_body:
        return ""

    # Feishu uses AES-256-CBC encryption
    # This is a placeholder - full implementation requires AES decryption
    # Reference: https://open.feishu.cn/document/ukTMukTMukTM/uYDNxYjL2QTM24iN0EjN/event-subscription-guide
    import warnings

    warnings.warn("AES decryption not fully implemented")
    return base64.b64decode(encrypted_body).decode("utf-8")


@router.post("/webhook/feishu")
async def handle_feishu_webhook(request: Request) -> JSONResponse:
    """Handle Feishu webhook events.

    Handles:
    1. URL verification (challenge response)
    2. Event callbacks with signature verification
    3. Message dispatching to FeishuChannel
    """
    # Get request headers for verification
    timestamp = request.headers.get("X-Lark-Request-Timestamp", "")
    nonce = request.headers.get("X-Lark-Request-Nonce", "")
    signature = request.headers.get("X-Lark-Signature", "")

    # Read raw body
    body = await request.body()
    body_str = body.decode("utf-8")

    try:
        payload: Dict[str, Any] = json.loads(body_str)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse webhook payload: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload",
        ) from e

    # Handle challenge verification (URL verification)
    if payload.get("type") == "url_verification":
        challenge = payload.get("challenge")
        logger.info(f"Feishu webhook URL verification, challenge: {challenge}")
        return JSONResponse(
            content={"challenge": challenge},
            status_code=status.HTTP_200_OK,
        )

    # Get config for verification
    from ...config.utils import load_config

    config = load_config()
    feishu_config = config.channels.feishu

    if not feishu_config.webhook_enabled:
        logger.warning("Feishu webhook is disabled in config")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook not enabled",
        )

    # Verify signature if verification token is configured
    verification_token = (
        feishu_config.webhook_verification_token
        or feishu_config.verification_token
    )
    if verification_token and not verify_signature(
        verification_token,
        timestamp,
        nonce,
        body_str,
        signature,
    ):
        logger.error("Webhook signature verification failed")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid signature",
        )

    # Decrypt body if encrypted
    encrypt_key = feishu_config.webhook_encrypt_key or feishu_config.encrypt_key
    if encrypt_key and "encrypt" in payload:
        try:
            decrypted = decrypt_body(encrypt_key, payload["encrypt"])
            payload = json.loads(decrypted)
        except Exception as e:
            logger.error(f"Failed to decrypt webhook payload: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Decryption failed",
            ) from e

    # Get the event data from the new 2.0 schema
    event_data = payload.get("event", payload)
    header = payload.get("header", {})
    event_id = header.get("event_id", "")

    logger.debug(f"Received Feishu webhook event: {event_id}")

    # Dispatch to channel - get channel_manager from app.state
    cm = getattr(request.app.state, "channel_manager", None)
    if cm is None:
        logger.error("Channel manager not initialized")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Channel manager not ready",
        )

    # Find FeishuChannel instance
    feishu_channel = None
    if hasattr(cm, "channels"):
        for ch in cm.channels.values():
            if ch.channel == "feishu":
                feishu_channel = ch
                break

    if feishu_channel is None:
        logger.error("Feishu channel not found")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Feishu channel not available",
        )

    # Handle the event asynchronously
    try:
        await feishu_channel.handle_webhook_event(payload)
    except Exception as e:
        logger.exception(f"Error handling webhook event: {e}")
        # Return 200 to prevent Feishu from retrying
        # (we've logged the error)

    return JSONResponse(
        content={"code": 0, "msg": "success"},
        status_code=status.HTTP_200_OK,
    )


@router.get("/webhook/feishu/health")
async def feishu_webhook_health(request: Request) -> JSONResponse:
    """Health check endpoint for Feishu webhook."""
    cm = getattr(request.app.state, "channel_manager", None)
    return JSONResponse(
        content={
            "status": "ok",
            "webhook_enabled": cm is not None,
        },
        status_code=status.HTTP_200_OK,
    )

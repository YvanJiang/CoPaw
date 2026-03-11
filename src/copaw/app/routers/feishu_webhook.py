# -*- coding: utf-8 -*-
"""Feishu (Lark) Webhook Router.

Handles Feishu event subscriptions via HTTP webhook.
Supports challenge verification, signature verification, and event dispatching.
Reference:
https://open.feishu.cn/document/ukTMukTMukTM/uYDNxYjL2QTM24iN0EjN/event-subscription-guide
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

    Reference:
    https://open.larksuite.com/document/server-docs/event-subscription/event-subscription-configure-/encrypt-key-encryption-configuration-case
    Algorithm: SHA256(timestamp + nonce + encrypt_key + body), output as hex
    """
    if not encrypt_key:
        logger.warning(
            "No encrypt_key configured, skipping signature verification",
        )
        return True

    # Lark signature algorithm:
    # SHA256(timestamp + nonce + encrypt_key + body)
    # Note: This is NOT HMAC, just a simple SHA256 hash of the
    # concatenated string
    content = f"{timestamp}{nonce}{encrypt_key}{body}"
    computed = hashlib.sha256(content.encode("utf-8")).hexdigest()

    # Debug logging - use info level for troubleshooting
    is_valid = hmac.compare_digest(computed, expected_signature)
    if is_valid:
        logger.info(
            f"Signature verification PASSED for timestamp={timestamp}",
        )
    else:
        logger.warning(
            f"Signature verification FAILED: timestamp={timestamp}, "
            f"nonce={nonce}, key_prefix={encrypt_key[:8]}..., "
            f"body_len={len(body)}, computed={computed[:20]}..., "
            f"expected={expected_signature[:20]}...",
        )

    return is_valid


def decrypt_body(encrypt_key: str, encrypted_body: str) -> str:
    """Decrypt Feishu/Lark webhook payload using AES-256-CBC.

    Args:
        encrypt_key: The encryption key from Lark developer console
        encrypted_body: Base64-encoded encrypted payload

    Returns:
        Decrypted JSON string

    Reference: https://open.larksuite.com/document/uAjLw4CM/ukTMukTMukTM/
               event-subscription-guide/event-subscriptions/encrypt-keys
    """
    if not encrypted_body:
        return ""

    try:
        # Try to import cryptography for AES decryption
        from cryptography.hazmat.primitives.ciphers import (
            Cipher,
            algorithms,
            modes,
        )
        from cryptography.hazmat.backends import default_backend
    except ImportError:
        logger.error(
            "cryptography package is required for webhook decryption. "
            "Install with: pip install cryptography",
        )
        raise RuntimeError(
            "cryptography package required for Lark webhook decryption",
        ) from None

    # Decode the base64 encrypted body
    encrypted_bytes = base64.b64decode(encrypted_body)

    # Derive AES key from encrypt_key using SHA-256
    # Lark uses the first 32 bytes of SHA256(encrypt_key) as the AES key
    key = hashlib.sha256(encrypt_key.encode("utf-8")).digest()

    # Extract IV (first 16 bytes) and ciphertext
    # Lark format: IV (16 bytes) + ciphertext + padding
    iv = encrypted_bytes[:16]
    ciphertext = encrypted_bytes[16:]

    # Create AES-256-CBC cipher
    cipher = Cipher(
        algorithms.AES(key),
        modes.CBC(iv),
        backend=default_backend(),
    )
    decryptor = cipher.decryptor()

    # Decrypt
    padded_plaintext = decryptor.update(ciphertext) + decryptor.finalize()

    # Remove PKCS7 padding
    padding_len = padded_plaintext[-1]
    plaintext = padded_plaintext[:-padding_len]

    return plaintext.decode("utf-8")


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

    # Debug logging for troubleshooting
    logger.info(
        f"Feishu webhook request: timestamp={timestamp}, nonce={nonce}, "
        f"signature={signature[:30] if signature else 'None'}..., "
        f"body_len={len(body_str)}",
    )
    # Log full body for signature verification debugging
    # (temporarily using info level)
    logger.info(f"Feishu webhook full body for debug: {body_str}")

    try:
        payload: Dict[str, Any] = json.loads(body_str)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse webhook payload: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload",
        ) from e

    # Handle challenge verification (URL verification)
    # Note: URL verification may be encrypted, handle both cases
    is_url_verification = payload.get("type") == "url_verification"

    # Check if payload is encrypted (url_verification with encrypt field)
    if "encrypt" in payload:
        # Get config for decryption
        from ...config.utils import load_config

        config = load_config()
        feishu_config = config.channels.feishu
        encrypt_key = (
            getattr(feishu_config, "webhook_encrypt_key", None)
            or getattr(feishu_config, "encrypt_key", None)
            or getattr(feishu_config, "verification_token", None)
        )

        if encrypt_key:
            try:
                decrypted = decrypt_body(encrypt_key, payload["encrypt"])
                payload = json.loads(decrypted)
                logger.info("Successfully decrypted webhook payload")
                # Re-check type after decryption
                is_url_verification = payload.get("type") == "url_verification"
            except Exception as e:
                logger.error(f"Failed to decrypt webhook payload: {e}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Decryption failed",
                ) from e

    if is_url_verification:
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

    # Verify signature using encrypt_key
    # (Lark uses encrypt_key for signature, not verification_token)
    # Reference:
    # https://open.larksuite.com/document/uAjLw4CM/ukTMukTMukTM/event-subscription-guide/event-subscription-configure
    signature_key = (
        feishu_config.webhook_encrypt_key
        or feishu_config.encrypt_key
        or feishu_config.webhook_verification_token
        or feishu_config.verification_token
    )

    # Allow skipping signature verification
    # (e.g., for reverse proxy setups that modify request body)
    if getattr(feishu_config, "webhook_skip_signature_verify", False):
        logger.warning(
            "Skipping signature verification "
            "(webhook_skip_signature_verify is enabled)",
        )
    elif signature_key and signature:
        is_valid = verify_signature(
            signature_key,
            timestamp,
            nonce,
            body_str,
            signature,
        )
        if not is_valid:
            # 尝试使用 verification_token 验证（某些 Lark 配置使用此方式）
            verification_key = (
                feishu_config.webhook_verification_token
                or feishu_config.verification_token
            )
            if verification_key and verification_key != signature_key:
                is_valid = verify_signature(
                    verification_key,
                    timestamp,
                    nonce,
                    body_str,
                    signature,
                )
                if is_valid:
                    logger.info("Signature verified using verification_token")
                else:
                    logger.error(
                        f"Webhook signature verification failed. "
                        f"Timestamp: {timestamp}, Nonce: {nonce}, "
                        f"Signature key prefix: {signature_key[:8]}..., "
                        f"Body length: {len(body_str)}",
                    )
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Invalid signature",
                    )
            else:
                logger.error(
                    f"Webhook signature verification failed. "
                    f"Timestamp: {timestamp}, Nonce: {nonce}, "
                    f"Signature key prefix: {signature_key[:8]}..., "
                    f"Body length: {len(body_str)}",
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Invalid signature",
                )

    # Decrypt body if encrypted
    encrypt_key = (
        feishu_config.webhook_encrypt_key or feishu_config.encrypt_key
    )
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
        channels = cm.channels
        if isinstance(channels, dict):
            channel_iter = channels.values()
        else:
            channel_iter = channels
        for ch in channel_iter:
            if getattr(ch, "channel", None) == "feishu":
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

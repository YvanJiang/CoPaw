# -*- coding: utf-8 -*-
"""Notification service for sending messages via Feishu API."""

import os
import subprocess
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class NotificationService:
    """Service for sending notifications via Feishu API."""

    def __init__(self, base_url: Optional[str] = None):
        """Initialize notification service.

        Args:
            base_url: Base URL for notification API.
                Defaults to env var or localhost.
        """
        self.base_url = base_url or os.environ.get(
            "COPAW_NOTIFY_URL",
            "http://127.0.0.1:8088/api/v1",
        )
        self.api_user = os.environ.get("API_USER")
        self.api_pass = os.environ.get("API_PASS")

    def is_configured(self) -> bool:
        """Check if notification service is properly configured.

        Returns:
            True if API_USER and API_PASS are set, False otherwise.
        """
        return bool(self.api_user and self.api_pass)

    def build_feishu_command(self, message: str, source: str = "CoPaw") -> str:
        """Build curl command for sending Feishu notification.

        Args:
            message: Message content to send.
            source: Source identifier for the notification.

        Returns:
            Curl command string ready for execution.

        Raises:
            RuntimeError: If notification service is not configured.
        """
        if not self.is_configured():
            raise RuntimeError(
                "Notification service not configured. "
                "Please set API_USER and "
                "API_PASS environment variables.",
            )

        # Escape quotes in message to prevent shell injection
        escaped_message = message.replace('"', '\\"')
        escaped_source = source.replace('"', '\\"')

        url = f"{self.base_url}/notify/feishu"

        cmd = (
            f'curl -u "{self.api_user}:{self.api_pass}" '
            f'-X POST "{url}" '
            f'-H "Content-Type: application/json" '
            '-d "{\\"message\\":\\"{escaped_message}\\",'
            '\\"source\\":\\"{escaped_source}\\"}"'.format(
                escaped_message=escaped_message,
                escaped_source=escaped_source,
            )
        )

        return cmd

    def send_feishu_sync(self, message: str, source: str = "CoPaw") -> bool:
        """Send Feishu notification synchronously.

        Args:
            message: Message content to send.
            source: Source identifier for the notification.

        Returns:
            True if notification was sent successfully, False otherwise.
        """
        if not self.is_configured():
            logger.warning(
                "Cannot send notification: "
                "API_USER and API_PASS not configured",
            )
            return False

        try:
            cmd = self.build_feishu_command(message, source)
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )

            if result.returncode == 0:
                logger.info("Notification sent successfully: %s", message)
                return True
            else:
                logger.error(
                    "Failed to send notification: %s",
                    result.stderr,
                )
                return False

        except subprocess.TimeoutExpired:
            logger.error("Notification request timed out")
            return False
        except Exception as e:
            logger.error("Error sending notification: %s", e)
            return False


# Singleton instance
_notification_service: Optional[NotificationService] = None


def get_notification_service() -> NotificationService:
    """Get singleton instance of NotificationService."""
    global _notification_service
    if _notification_service is None:
        _notification_service = NotificationService()
    return _notification_service

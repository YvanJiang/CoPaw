"""Tests for notification service."""

import os
import pytest
from unittest.mock import patch, MagicMock

from copaw.utils.notification import NotificationService, get_notification_service


class TestNotificationService:
    """Test NotificationService class."""

    def test_init_with_defaults(self):
        """Test initialization with default values."""
        with patch.dict(os.environ, {}, clear=True):
            service = NotificationService()
            assert service.base_url == "http://127.0.0.1:8088/api/v1"
            assert service.api_user is None
            assert service.api_pass is None

    def test_init_with_env_vars(self):
        """Test initialization with environment variables."""
        env = {
            "COPAW_NOTIFY_URL": "http://example.com/api",
            "API_USER": "test_user",
            "API_PASS": "test_pass",
        }
        with patch.dict(os.environ, env, clear=True):
            service = NotificationService()
            assert service.base_url == "http://example.com/api"
            assert service.api_user == "test_user"
            assert service.api_pass == "test_pass"

    def test_init_with_custom_base_url(self):
        """Test initialization with custom base URL."""
        with patch.dict(os.environ, {}, clear=True):
            service = NotificationService(base_url="http://custom.com/api")
            assert service.base_url == "http://custom.com/api"

    def test_is_configured_true(self):
        """Test is_configured returns True when credentials are set."""
        env = {"API_USER": "user", "API_PASS": "pass"}
        with patch.dict(os.environ, env, clear=True):
            service = NotificationService()
            assert service.is_configured() is True

    def test_is_configured_false_no_user(self):
        """Test is_configured returns False when API_USER is missing."""
        env = {"API_PASS": "pass"}
        with patch.dict(os.environ, env, clear=True):
            service = NotificationService()
            assert service.is_configured() is False

    def test_is_configured_false_no_pass(self):
        """Test is_configured returns False when API_PASS is missing."""
        env = {"API_USER": "user"}
        with patch.dict(os.environ, env, clear=True):
            service = NotificationService()
            assert service.is_configured() is False

    def test_build_feishu_command_success(self):
        """Test building curl command for Feishu notification."""
        env = {"API_USER": "user", "API_PASS": "pass"}
        with patch.dict(os.environ, env, clear=True):
            service = NotificationService()
            cmd = service.build_feishu_command("Hello World", "Test")

            assert 'curl -u "user:pass"' in cmd
            assert "-X POST" in cmd
            assert "/notify/feishu" in cmd
            assert "Hello World" in cmd
            assert "Test" in cmd

    def test_build_feishu_command_not_configured(self):
        """Test build_feishu_command raises error when not configured."""
        with patch.dict(os.environ, {}, clear=True):
            service = NotificationService()
            with pytest.raises(RuntimeError, match="Notification service not configured"):
                service.build_feishu_command("Hello", "Test")

    def test_build_feishu_command_escapes_quotes(self):
        """Test that quotes in message are properly escaped."""
        env = {"API_USER": "user", "API_PASS": "pass"}
        with patch.dict(os.environ, env, clear=True):
            service = NotificationService()
            cmd = service.build_feishu_command('Hello "World"', "Test")

            assert '\\"World\\"' in cmd

    @patch("subprocess.run")
    def test_send_feishu_sync_success(self, mock_run):
        """Test successful notification sending."""
        mock_run.return_value = MagicMock(returncode=0, stdout="OK", stderr="")

        env = {"API_USER": "user", "API_PASS": "pass"}
        with patch.dict(os.environ, env, clear=True):
            service = NotificationService()
            result = service.send_feishu_sync("Hello", "Test")

            assert result is True
            mock_run.assert_called_once()

    @patch("subprocess.run")
    def test_send_feishu_sync_failure(self, mock_run):
        """Test failed notification sending."""
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Error")

        env = {"API_USER": "user", "API_PASS": "pass"}
        with patch.dict(os.environ, env, clear=True):
            service = NotificationService()
            result = service.send_feishu_sync("Hello", "Test")

            assert result is False

    def test_send_feishu_sync_not_configured(self):
        """Test send_feishu_sync returns False when not configured."""
        with patch.dict(os.environ, {}, clear=True):
            service = NotificationService()
            result = service.send_feishu_sync("Hello", "Test")

            assert result is False

    @patch("subprocess.run")
    def test_send_feishu_sync_timeout(self, mock_run):
        """Test notification sending with timeout."""
        from subprocess import TimeoutExpired
        mock_run.side_effect = TimeoutExpired("curl", 30)

        env = {"API_USER": "user", "API_PASS": "pass"}
        with patch.dict(os.environ, env, clear=True):
            service = NotificationService()
            result = service.send_feishu_sync("Hello", "Test")

            assert result is False


class TestGetNotificationService:
    """Test get_notification_service function."""

    def test_singleton(self):
        """Test that get_notification_service returns singleton."""
        # Reset singleton for test
        import copaw.utils.notification as notification_module
        notification_module._notification_service = None

        with patch.dict(os.environ, {}, clear=True):
            service1 = get_notification_service()
            service2 = get_notification_service()
            assert service1 is service2

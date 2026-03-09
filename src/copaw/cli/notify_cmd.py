# -*- coding: utf-8 -*-
"""Notification management commands for CoPaw CLI."""

import click
from copaw.utils.notification import get_notification_service


@click.group(name="notify")
def notify_cmd():
    """Manage notification settings and send test notifications."""
    pass


@notify_cmd.command(name="send")
@click.option(
    "--message", "-m",
    required=True,
    help="Message content to send"
)
@click.option(
    "--source", "-s",
    default="CoPaw CLI",
    help="Source identifier for the notification"
)
def send_notification(message: str, source: str):
    """Send a test notification."""
    service = get_notification_service()

    if not service.is_configured():
        raise click.ClickException(
            "❌ Notification service not configured. "
            "Please set API_USER and API_PASS environment variables."
        )

    click.echo(f"Sending notification...")
    click.echo(f"  Message: {message}")
    click.echo(f"  Source: {source}")

    success = service.send_feishu_sync(message, source)

    if success:
        click.echo("✅ Notification sent successfully!")
    else:
        raise click.ClickException("❌ Failed to send notification.")


@notify_cmd.command(name="status")
def notification_status():
    """Check notification configuration status."""
    service = get_notification_service()

    click.echo("Notification Configuration")
    click.echo("=" * 40)

    if service.is_configured():
        click.echo("✅ Configured")
        click.echo(f"  API User: {service.api_user}")
        click.echo(f"  Base URL: {service.base_url}")
        # Mask password for security
        masked_pass = "*" * len(service.api_pass) if service.api_pass else ""
        click.echo(f"  API Pass: {masked_pass}")
    else:
        click.echo("❌ Not configured")
        click.echo("")
        click.echo("Required environment variables:")
        click.echo("  - API_USER: API authentication username")
        click.echo("  - API_PASS: API authentication password")
        click.echo("")
        click.echo("Optional environment variables:")
        click.echo(
            "  - COPAW_NOTIFY_URL: Notification service URL "
            "(default: http://127.0.0.1:8088/api/v1)"
        )

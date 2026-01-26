"""
Sistema de alertas para errores críticos en tareas de Celery.
Soporta múltiples canales: Email, Slack, Telegram, Webhook.
"""
import logging
import traceback
from typing import Dict, Any, Optional, List
from datetime import datetime
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib

from app.core.config import settings

logger = logging.getLogger(__name__)


class AlertLevel:
    """Niveles de alerta"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AlertManager:
    """Gestor centralizado de alertas"""
    
    def __init__(self):
        self.enabled = getattr(settings, 'alerts_enabled', True)
        self.channels = self._load_channels()
    
    def _load_channels(self) -> Dict[str, bool]:
        """Cargar canales de alerta habilitados desde configuración"""
        return {
            'email': getattr(settings, 'alert_email_enabled', False),
            'slack': getattr(settings, 'alert_slack_enabled', False),
            'telegram': getattr(settings, 'alert_telegram_enabled', False),
            'webhook': getattr(settings, 'alert_webhook_enabled', False),
        }
    
    def send_alert(
        self,
        title: str,
        message: str,
        level: str = AlertLevel.ERROR,
        context: Optional[Dict[str, Any]] = None,
        channels: Optional[List[str]] = None
    ):
        """
        Enviar alerta a los canales configurados
        
        Args:
            title: Título de la alerta
            message: Mensaje de la alerta
            level: Nivel de severidad (info, warning, error, critical)
            context: Contexto adicional (task_id, instance_id, etc.)
            channels: Lista de canales específicos (None = todos los habilitados)
        """
        if not self.enabled:
            logger.debug("Alertas deshabilitadas globalmente")
            return
        
        # Si no se especifican canales, usar todos los habilitados
        if channels is None:
            channels = [ch for ch, enabled in self.channels.items() if enabled]
        
        alert_data = {
            'title': title,
            'message': message,
            'level': level,
            'context': context or {},
            'timestamp': datetime.utcnow().isoformat()
        }
        
        for channel in channels:
            try:
                if channel == 'email' and self.channels.get('email'):
                    self._send_email(alert_data)
                elif channel == 'slack' and self.channels.get('slack'):
                    self._send_slack(alert_data)
                elif channel == 'telegram' and self.channels.get('telegram'):
                    self._send_telegram(alert_data)
                elif channel == 'webhook' and self.channels.get('webhook'):
                    self._send_webhook(alert_data)
            except Exception as e:
                logger.error(
                    f"Error sending alert to {channel}: {e}",
                    exc_info=True
                )
    
    def _send_email(self, alert_data: Dict[str, Any]):
        """Enviar alerta por email"""
        smtp_host = getattr(settings, 'alert_email_smtp_host', 'localhost')
        smtp_port = getattr(settings, 'alert_email_smtp_port', 587)
        smtp_user = getattr(settings, 'alert_email_smtp_user', '')
        smtp_password = getattr(settings, 'alert_email_smtp_password', '')
        from_email = getattr(settings, 'alert_email_from', 'alerts@woocommerce-odoo.local')
        to_emails = getattr(settings, 'alert_email_to', [])
        
        if not to_emails:
            logger.warning("No email recipients configured for alerts")
            return
        
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"[{alert_data['level'].upper()}] {alert_data['title']}"
        msg['From'] = from_email
        msg['To'] = ', '.join(to_emails)
        
        # HTML body
        html_body = f"""
        <html>
          <body>
            <h2 style="color: {'red' if alert_data['level'] == AlertLevel.CRITICAL else 'orange'};">
              {alert_data['title']}
            </h2>
            <p><strong>Level:</strong> {alert_data['level'].upper()}</p>
            <p><strong>Time:</strong> {alert_data['timestamp']}</p>
            <p><strong>Message:</strong></p>
            <pre>{alert_data['message']}</pre>
            
            {f"<p><strong>Context:</strong></p><pre>{alert_data['context']}</pre>" if alert_data['context'] else ""}
          </body>
        </html>
        """
        
        msg.attach(MIMEText(html_body, 'html'))
        
        try:
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                if smtp_user and smtp_password:
                    server.starttls()
                    server.login(smtp_user, smtp_password)
                server.send_message(msg)
                logger.info(f"Email alert sent to {to_emails}")
        except Exception as e:
            logger.error(f"Failed to send email alert: {e}")
    
    def _send_slack(self, alert_data: Dict[str, Any]):
        """Enviar alerta a Slack"""
        webhook_url = getattr(settings, 'alert_slack_webhook_url', '')
        
        if not webhook_url:
            logger.warning("Slack webhook URL not configured")
            return
        
        # Color based on level
        color_map = {
            AlertLevel.INFO: '#36a64f',
            AlertLevel.WARNING: '#ff9800',
            AlertLevel.ERROR: '#f44336',
            AlertLevel.CRITICAL: '#d32f2f'
        }
        
        payload = {
            "attachments": [{
                "color": color_map.get(alert_data['level'], '#f44336'),
                "title": alert_data['title'],
                "text": alert_data['message'],
                "fields": [
                    {
                        "title": "Level",
                        "value": alert_data['level'].upper(),
                        "short": True
                    },
                    {
                        "title": "Time",
                        "value": alert_data['timestamp'],
                        "short": True
                    }
                ],
                "footer": "WooCommerce-Odoo Sync",
                "ts": int(datetime.utcnow().timestamp())
            }]
        }
        
        # Add context fields if present
        if alert_data['context']:
            for key, value in alert_data['context'].items():
                payload["attachments"][0]["fields"].append({
                    "title": key.replace('_', ' ').title(),
                    "value": str(value),
                    "short": True
                })
        
        response = requests.post(webhook_url, json=payload, timeout=10)
        response.raise_for_status()
        logger.info("Slack alert sent successfully")
    
    def _send_telegram(self, alert_data: Dict[str, Any]):
        """Enviar alerta a Telegram"""
        bot_token = getattr(settings, 'alert_telegram_bot_token', '')
        chat_id = getattr(settings, 'alert_telegram_chat_id', '')
        
        if not bot_token or not chat_id:
            logger.warning("Telegram bot token or chat ID not configured")
            return
        
        # Format message
        emoji_map = {
            AlertLevel.INFO: 'ℹ️',
            AlertLevel.WARNING: '⚠️',
            AlertLevel.ERROR: '❌',
            AlertLevel.CRITICAL: '🔥'
        }
        
        text = f"""
{emoji_map.get(alert_data['level'], '❌')} <b>{alert_data['title']}</b>

<b>Level:</b> {alert_data['level'].upper()}
<b>Time:</b> {alert_data['timestamp']}

<b>Message:</b>
<pre>{alert_data['message']}</pre>
"""
        
        if alert_data['context']:
            text += "\n<b>Context:</b>\n"
            for key, value in alert_data['context'].items():
                text += f"• {key}: {value}\n"
        
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            'chat_id': chat_id,
            'text': text,
            'parse_mode': 'HTML'
        }
        
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        logger.info("Telegram alert sent successfully")
    
    def _send_webhook(self, alert_data: Dict[str, Any]):
        """Enviar alerta a webhook personalizado"""
        webhook_url = getattr(settings, 'alert_webhook_url', '')
        
        if not webhook_url:
            logger.warning("Webhook URL not configured")
            return
        
        response = requests.post(webhook_url, json=alert_data, timeout=10)
        response.raise_for_status()
        logger.info("Webhook alert sent successfully")


# Singleton instance
alert_manager = AlertManager()


def send_task_error_alert(
    task_name: str,
    error: Exception,
    task_id: Optional[str] = None,
    instance_id: Optional[int] = None,
    retries: int = 0,
    max_retries: int = 3
):
    """
    Helper para enviar alerta de error en tarea de Celery
    
    Args:
        task_name: Nombre de la tarea
        error: Excepción que causó el error
        task_id: ID de la tarea de Celery
        instance_id: ID de la instancia afectada
        retries: Intentos actuales
        max_retries: Máximo de intentos
    """
    level = AlertLevel.CRITICAL if retries >= max_retries else AlertLevel.ERROR
    
    title = f"Task Failed: {task_name}"
    message = f"""
Error: {type(error).__name__}: {str(error)}

Traceback:
{traceback.format_exc()}
"""
    
    context = {
        'task_name': task_name,
        'task_id': task_id,
        'instance_id': instance_id,
        'retries': f"{retries}/{max_retries}",
        'error_type': type(error).__name__
    }
    
    alert_manager.send_alert(
        title=title,
        message=message,
        level=level,
        context=context
    )


def send_sync_completion_alert(
    instance_id: int,
    instance_name: str,
    total_processed: int,
    created: int,
    updated: int,
    errors: int,
    duration_seconds: float
):
    """
    Alerta de resumen de sincronización completada
    
    Args:
        instance_id: ID de la instancia
        instance_name: Nombre de la instancia
        total_processed: Total de ítems procesados
        created: Ítems creados
        updated: Ítems actualizados
        errors: Errores encontrados
        duration_seconds: Duración en segundos
    """
    level = AlertLevel.WARNING if errors > 0 else AlertLevel.INFO
    
    title = f"Sync Completed: {instance_name}"
    message = f"""
Synchronization completed for instance {instance_name} (ID: {instance_id})

Summary:
• Total Processed: {total_processed}
• Created: {created}
• Updated: {updated}
• Errors: {errors}
• Duration: {duration_seconds:.2f}s
• Success Rate: {((total_processed - errors) / total_processed * 100) if total_processed > 0 else 0:.1f}%
"""
    
    context = {
        'instance_id': instance_id,
        'instance_name': instance_name,
        'total_processed': total_processed,
        'created': created,
        'updated': updated,
        'errors': errors,
        'duration_seconds': round(duration_seconds, 2)
    }
    
    # Solo enviar por email/webhook para no saturar Slack/Telegram
    alert_manager.send_alert(
        title=title,
        message=message,
        level=level,
        context=context,
        channels=['email', 'webhook'] if level == AlertLevel.INFO else None
    )

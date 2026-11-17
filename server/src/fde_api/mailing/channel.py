"""发信通道解析（provider 无关的唯一权威）。

注册制试用开闸 R1（2026-11-17）：SES 生产权限已被 AWS 拒绝（路线冻结），
注册面的邮箱验证邮件改走 SMTP（Zoho 形态）。既有代码把「发信是否启用」写死成
``settings.ses_enabled``（mailing/service.py 与 registration/service.py 各一处），
通道无关化后这两个点位统一读本模块——**通道切换只改配置，不改闸门语义**。

纯逻辑层：只读 Settings，不构造客户端、不 import 网络栈（可测性与
ses_client/smtp_client 解耦）。
"""
from __future__ import annotations

from fde_api.config import Settings

CHANNEL_SES = "ses"
CHANNEL_SMTP = "smtp"


class MailChannelConflictError(RuntimeError):
    """两发信通道同开＝配置歧义 ⇒ fail-closed（不静默择一）。"""


def resolve_channel(settings: Settings) -> str | None:
    """生效通道标识（'ses' / 'smtp' / None＝未启用）。

    两开关同开即抛错：SES 与 SMTP 都是「已启用」却只可能有一条生效，
    静默择一＝配置错误被吞掉（宁可启动失败）。
    """
    if settings.ses_enabled and settings.smtp_enabled:
        raise MailChannelConflictError("smtp_and_ses_enabled_conflict")
    if settings.smtp_enabled:
        return CHANNEL_SMTP
    if settings.ses_enabled:
        return CHANNEL_SES
    return None


def channel_enabled(settings: Settings) -> bool:
    """任一发信通道已启用（注册面开闸三条件之一，通道无关）。

    冲突配置（SES 与 SMTP 同开）在本函数按 **未启用** 处理＝fail-closed：
    注册面整体关闭（404），不因配置歧义炸 500，也不静默放行。
    """
    return bool(settings.ses_enabled or settings.smtp_enabled)

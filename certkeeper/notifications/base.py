"""通知 Provider 抽象。"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field

from certkeeper.providers import Provider, ProviderRegistry


@dataclass(slots=True)
class ExpiryReminder:
    """单个证书的到期提醒信息。"""

    domain: str
    days_until_expiry: int | None
    expires_at: str | None


@dataclass(slots=True)
class ReminderSummary:
    """到期提醒汇总。"""

    reminders: list[ExpiryReminder] = field(default_factory=list)
    renewal_days: int = 30


class Notifier(Provider):
    """通知渠道的基类。"""

    @abstractmethod
    def notify(self, summary) -> None:
        """发送 apply 汇总通知。"""

    def notify_reminder(self, reminder_summary: ReminderSummary) -> None:
        """发送证书到期提醒通知。默认空实现，子类可覆盖。"""


__all__ = ["ExpiryReminder", "Notifier", "ProviderRegistry", "ReminderSummary"]

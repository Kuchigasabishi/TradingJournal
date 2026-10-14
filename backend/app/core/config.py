"""Runtime configuration (docs/BLUEPRINT.md, section 3.4). Environment variables win over the repo-root .env."""
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]

# The public weekly export (docs/BLUEPRINT.md, D3). The same export is also published as XML; the parser accepts both.
DEFAULT_FF_FEED_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

FeedsMode = Literal["off", "fixture", "live"]


def _default_database_url() -> str:
    return f"sqlite:///{(REPO_ROOT / 'data' / 'dev.db').as_posix()}"


def url_host(url: str) -> str:
    """The host of a URL, lower-case, with no credentials, path or query: the only part that is ever logged."""
    return (urlsplit(url).hostname or "").lower()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["dev", "test", "prod"] = "prod"
    database_url: str = Field(default_factory=_default_database_url)
    app_timezone: str = "UTC"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    static_dir: Path | None = None
    auto_migrate: bool = True
    # The largest request body the API accepts. The journal's own requests are a few hundred bytes; a note is at most 10,000 characters.
    max_request_bytes: int = Field(1_048_576, ge=1_024)

    # External feeds (Phase 3). `off` runs nothing, `live` talks to the real hosts, and `fixture` talks only to
    # loopback addresses (the verification stub), so a test run can never reach the internet by accident.
    feeds_mode: FeedsMode = "off"
    # Hosts, besides loopback, that fixture mode may talk to: the name of the stub's container when verification runs in
    # Docker Compose. Comma separated, plain host names only. Ignored outside fixture mode.
    feeds_fixture_hosts: str = ""
    ff_feed_url: str = DEFAULT_FF_FEED_URL
    ff_poll_minutes: int = Field(60, ge=30)
    # The calendar's secret iCal address is a bearer credential. It lives in .env, is masked in every log line,
    # and is never returned by the API or shown in the UI.
    gcal_ical_url: SecretStr | None = None
    gcal_poll_minutes: int = Field(30, ge=5)
    sync_cooldown_seconds: int = Field(300, ge=0)  # least time between two manual syncs of one source
    feed_tick_seconds: float = Field(5.0, gt=0)  # how often a feed worker looks at its schedule
    feed_timeout_seconds: float = Field(15.0, gt=0)
    feed_max_bytes: int = Field(10_000_000, ge=1_000)
    # Where the feeds' clock starts, for tests. Time then keeps running. Honored only when APP_ENV=test.
    app_now_override: datetime | None = None

    @field_validator("log_level", mode="before")
    @classmethod
    def _uppercase_level(cls, value):
        return value.upper() if isinstance(value, str) else value

    @field_validator("static_dir", "gcal_ical_url", "app_now_override", mode="before")
    @classmethod
    def _blank_is_unset(cls, value):
        return None if value is None or (isinstance(value, str) and not value.strip()) else value

    @field_validator("app_timezone")
    @classmethod
    def _known_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"unknown IANA time zone: {value!r}") from None
        return value

    @field_validator("app_now_override")
    @classmethod
    def _override_is_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("APP_NOW_OVERRIDE needs an explicit UTC offset, for example 2044-05-11T12:00:00Z")
        return value.astimezone(timezone.utc) if value else None

    @model_validator(mode="after")
    def _feed_rules(self) -> "Settings":
        if self.app_now_override is not None and self.app_env != "test":
            raise ValueError("APP_NOW_OVERRIDE is honored only when APP_ENV=test")
        if self.feeds_mode == "fixture":
            urls = {"FF_FEED_URL": self.ff_feed_url}
            if self.gcal_ical_url is not None:
                urls["GCAL_ICAL_URL"] = self.gcal_ical_url.get_secret_value()
            allowed = LOOPBACK_HOSTS | self.fixture_hosts
            outside = [name for name, url in urls.items() if url_host(url) not in allowed]
            if outside:
                raise ValueError(f"FEEDS_MODE=fixture only allows loopback addresses and FEEDS_FIXTURE_HOSTS, but {', '.join(outside)} points elsewhere")
        return self

    @field_validator("feeds_fixture_hosts")
    @classmethod
    def _plain_host_names(cls, value: str) -> str:
        for name in (part.strip() for part in value.split(",")):
            if name and not re.fullmatch(r"[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?", name):
                raise ValueError("FEEDS_FIXTURE_HOSTS lists plain host names (letters, digits and hyphens, no dots), such as the name of a container")
        return value

    @property
    def fixture_hosts(self) -> frozenset[str]:
        """The extra hosts fixture mode allows. A name with no dot cannot be a public site, which is the point of the rule."""
        return frozenset(part.strip().lower() for part in self.feeds_fixture_hosts.split(",") if part.strip())

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.app_timezone)

    @property
    def gcal_url(self) -> str | None:
        return self.gcal_ical_url.get_secret_value() if self.gcal_ical_url else None

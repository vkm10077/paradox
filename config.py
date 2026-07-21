import os
from dataclasses import dataclass
from typing import Dict


def get_required_env(name: str) -> str:
    """
    Required environment variable पढ़ता है।
    Value missing होने पर application साफ error देगा।
    """
    value = os.getenv(name, "").strip()

    if not value:
        raise RuntimeError(
            f"Required environment variable '{name}' is missing."
        )

    return value


def get_optional_env(
    name: str,
    default: str = ""
) -> str:
    """
    Optional environment variable सुरक्षित तरीके से पढ़ता है।
    """
    return os.getenv(name, default).strip()


@dataclass(frozen=True)
class FyersConfig:
    client_id: str
    secret_key: str
    redirect_uri: str
    response_type: str = "code"
    grant_type: str = "authorization_code"


@dataclass(frozen=True)
class AppConfig:
    secret_key: str
    environment: str
    session_cookie_secure: bool
    cache_seconds: int
    scan_batch_size: int
    scan_delay_seconds: float
    max_workers: int
    timezone: str


def load_fyers_config() -> FyersConfig:
    """
    FYERS API credentials Render environment variables से load करता है।
    """

    return FyersConfig(
        client_id=get_required_env("FYERS_CLIENT_ID"),
        secret_key=get_required_env("FYERS_SECRET_KEY"),
        redirect_uri=get_required_env("FYERS_REDIRECT_URI")
    )


def load_app_config() -> AppConfig:
    """
    Application configuration environment variables से load करता है।
    """

    environment = get_optional_env(
        "APP_ENV",
        "production"
    ).lower()

    session_cookie_secure = (
        get_optional_env(
            "SESSION_COOKIE_SECURE",
            "true"
        ).lower()
        in {"true", "1", "yes", "on"}
    )

    try:
        cache_seconds = int(
            get_optional_env(
                "SCANNER_CACHE_SECONDS",
                "300"
            )
        )
    except ValueError as exc:
        raise RuntimeError(
            "SCANNER_CACHE_SECONDS must be an integer."
        ) from exc

    try:
        scan_batch_size = int(
            get_optional_env(
                "SCAN_BATCH_SIZE",
                "20"
            )
        )
    except ValueError as exc:
        raise RuntimeError(
            "SCAN_BATCH_SIZE must be an integer."
        ) from exc

    try:
        scan_delay_seconds = float(
            get_optional_env(
                "SCAN_DELAY_SECONDS",
                "0.35"
            )
        )
    except ValueError as exc:
        raise RuntimeError(
            "SCAN_DELAY_SECONDS must be a number."
        ) from exc

    try:
        max_workers = int(
            get_optional_env(
                "MAX_SCAN_WORKERS",
                "4"
            )
        )
    except ValueError as exc:
        raise RuntimeError(
            "MAX_SCAN_WORKERS must be an integer."
        ) from exc

    if cache_seconds < 60:
        raise RuntimeError(
            "SCANNER_CACHE_SECONDS cannot be below 60."
        )

    if scan_batch_size < 1:
        raise RuntimeError(
            "SCAN_BATCH_SIZE must be at least 1."
        )

    if scan_delay_seconds < 0:
        raise RuntimeError(
            "SCAN_DELAY_SECONDS cannot be negative."
        )

    if max_workers < 1:
        raise RuntimeError(
            "MAX_SCAN_WORKERS must be at least 1."
        )

    return AppConfig(
        secret_key=get_required_env("SECRET_KEY"),
        environment=environment,
        session_cookie_secure=session_cookie_secure,
        cache_seconds=cache_seconds,
        scan_batch_size=scan_batch_size,
        scan_delay_seconds=scan_delay_seconds,
        max_workers=max_workers,
        timezone=get_optional_env(
            "APP_TIMEZONE",
            "Asia/Kolkata"
        )
    )


def get_timeframe_config() -> Dict[str, Dict[str, str]]:
    """
    Scanner में उपलब्ध सभी holding-period options।
    """

    return {
        "swing": {
            "label": "Swing",
            "holding_period": "5–30 Days",
            "history_resolution": "D",
            "history_days": "420"
        },
        "quarterly": {
            "label": "Quarterly",
            "holding_period": "1–3 Months",
            "history_resolution": "D",
            "history_days": "730"
        },
        "half_yearly": {
            "label": "Half-Yearly",
            "holding_period": "3–6 Months",
            "history_resolution": "D",
            "history_days": "1095"
        },
        "yearly": {
            "label": "Yearly",
            "holding_period": "6–12 Months",
            "history_resolution": "D",
            "history_days": "1825"
        },
        "five_year": {
            "label": "5 Year",
            "holding_period": "3–5 Years",
            "history_resolution": "D",
            "history_days": "3650"
        },
        "ten_year": {
            "label": "10 Year",
            "holding_period": "5–10 Years",
            "history_resolution": "D",
            "history_days": "3650"
        }

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

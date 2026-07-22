# ============================================
# app.py - Part 1 Start
# ============================================

from __future__ import annotations

import inspect
import logging
import os
import secrets
import time
from datetime import datetime, timedelta
from functools import wraps
from typing import Any, Callable, Optional

from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.middleware.proxy_fix import ProxyFix


# ============================================
# OPTIONAL PROJECT IMPORTS
# ============================================

try:
    import config as project_config
except ImportError:
    project_config = None

try:
    from fyers_service import FyersService
except ImportError:
    FyersService = None

try:
    from scanner_engine import ScannerEngine
except ImportError:
    ScannerEngine = None

try:
    from fundamental_service import FundamentalService
except ImportError:
    FundamentalService = None

try:
    from technical_scanner import TechnicalScanner
except ImportError:
    TechnicalScanner = None

try:
    from nifty500 import NIFTY500
except ImportError:
    NIFTY500 = []


# ============================================
# BASIC CONFIGURATION HELPERS
# ============================================

def get_config_value(
    name: str,
    default: Any = None,
    required: bool = False,
) -> Any:
    """
    Configuration priority:

    1. Environment variable
    2. config.py module attribute
    3. Supplied default
    """

    environment_value = os.getenv(name)

    if environment_value not in (None, ""):
        value = environment_value

    elif project_config is not None and hasattr(project_config, name):
        value = getattr(project_config, name)

    else:
        value = default

    if required and value in (None, ""):
        raise RuntimeError(
            f"Required configuration '{name}' is missing. "
            f"Add it in Render Environment Variables."
        )

    return value


def get_boolean_config(name: str, default: bool = False) -> bool:
    value = get_config_value(name, default)

    if isinstance(value, bool):
        return value

    return str(value).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
        "enabled",
    }


def get_integer_config(
    name: str,
    default: int,
    minimum: Optional[int] = None,
    maximum: Optional[int] = None,
) -> int:
    raw_value = get_config_value(name, default)

    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        value = default

    if minimum is not None:
        value = max(value, minimum)

    if maximum is not None:
        value = min(value, maximum)

    return value


# ============================================
# APPLICATION SETTINGS
# ============================================

APP_NAME = str(
    get_config_value(
        "APP_NAME",
        "Paradox Nifty 500 Smart Scanner",
    )
)

APP_VERSION = str(
    get_config_value(
        "APP_VERSION",
        "1.0.0",
    )
)

APP_ENV = str(
    get_config_value(
        "APP_ENV",
        os.getenv("FLASK_ENV", "production"),
    )
).lower()

IS_PRODUCTION = APP_ENV == "production"

SECRET_KEY = str(
    get_config_value(
        "SECRET_KEY",
        secrets.token_hex(32) if not IS_PRODUCTION else "",
    )
)

if not SECRET_KEY:
    raise RuntimeError(
        "SECRET_KEY is missing. Add a strong SECRET_KEY "
        "in Render Environment Variables."
    )

SESSION_LIFETIME_HOURS = get_integer_config(
    "SESSION_LIFETIME_HOURS",
    default=12,
    minimum=1,
    maximum=168,
)

SCANNER_CACHE_SECONDS = get_integer_config(
    "SCANNER_CACHE_SECONDS",
    default=60,
    minimum=15,
    maximum=3600,
)

MAX_SCAN_SYMBOLS = get_integer_config(
    "MAX_SCAN_SYMBOLS",
    default=500,
    minimum=1,
    maximum=500,
)

DEFAULT_TIMEFRAME = str(
    get_config_value(
        "DEFAULT_TIMEFRAME",
        "swing",
    )
).strip().lower()

SUPPORTED_TIMEFRAMES = {
    "swing",
    "quarterly",
    "half_yearly",
    "yearly",
    "five_year",
    "ten_year",
}

FYERS_CLIENT_ID = str(
    get_config_value(
        "FYERS_CLIENT_ID",
        get_config_value("FYERS_APP_ID", ""),
    )
).strip()

FYERS_SECRET_KEY = str(
    get_config_value(
        "FYERS_SECRET_KEY",
        get_config_value("FYERS_SECRET_ID", ""),
    )
).strip()

FYERS_REDIRECT_URI = str(
    get_config_value(
        "FYERS_REDIRECT_URI",
        "",
    )
).strip()

FMP_API_KEY = str(
    get_config_value(
        "FMP_API_KEY",
        "",
    )
).strip()


# ============================================
# FLASK APPLICATION
# ============================================

app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static",
)

app.secret_key = SECRET_KEY

app.config.update(
    APP_NAME=APP_NAME,
    APP_VERSION=APP_VERSION,
    ENV=APP_ENV,
    DEBUG=False,
    TESTING=False,
    SESSION_COOKIE_NAME="paradox_session",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=IS_PRODUCTION,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(
        hours=SESSION_LIFETIME_HOURS
    ),
    MAX_CONTENT_LENGTH=2 * 1024 * 1024,
    JSON_SORT_KEYS=False,
)

# Render reverse proxy support
app.wsgi_app = ProxyFix(
    app.wsgi_app,
    x_for=1,
    x_proto=1,
    x_host=1,
    x_port=1,
    x_prefix=1,
)


# ============================================
# LOGGING
# ============================================

logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s | %(levelname)s | "
        "%(name)s | %(message)s"
    ),
)

logger = logging.getLogger(APP_NAME)


# ============================================
# IN-MEMORY SCANNER CACHE
# ============================================

scanner_cache: dict[str, Any] = {
    "results": [],
    "updated_at": None,
    "timestamp": 0.0,
    "timeframe": None,
    "access_token_hash": None,
    "error": None,
    "running": False,
}


def clear_scanner_cache() -> None:
    scanner_cache.update(
        {
            "results": [],
            "updated_at": None,
            "timestamp": 0.0,
            "timeframe": None,
            "access_token_hash": None,
            "error": None,
            "running": False,
        }
    )


def get_token_hash(access_token: Optional[str]) -> Optional[int]:
    if not access_token:
        return None

    return hash(access_token[-25:])


def scanner_cache_is_valid(
    access_token: str,
    timeframe: str,
) -> bool:
    cached_timestamp = float(
        scanner_cache.get("timestamp") or 0
    )

    cache_age = time.time() - cached_timestamp

    return (
        bool(scanner_cache.get("results"))
        and cache_age < SCANNER_CACHE_SECONDS
        and scanner_cache.get("timeframe") == timeframe
        and scanner_cache.get("access_token_hash")
        == get_token_hash(access_token)
    )


# ============================================
# GENERAL HELPERS
# ============================================

def utc_now_iso() -> str:
    return datetime.utcnow().replace(
        microsecond=0
    ).isoformat() + "Z"


def normalize_timeframe(raw_timeframe: Optional[str]) -> str:
    timeframe = str(
        raw_timeframe or DEFAULT_TIMEFRAME
    ).strip().lower()

    aliases = {
        "15-20-days": "swing",
        "15_20_days": "swing",
        "swing_trading": "swing",
        "3_month": "quarterly",
        "3_months": "quarterly",
        "quarter": "quarterly",
        "6_month": "half_yearly",
        "6_months": "half_yearly",
        "half-yearly": "half_yearly",
        "1_year": "yearly",
        "1year": "yearly",
        "5_year": "five_year",
        "5year": "five_year",
        "10_year": "ten_year",
        "10year": "ten_year",
    }

    timeframe = aliases.get(timeframe, timeframe)

    if timeframe not in SUPPORTED_TIMEFRAMES:
        return DEFAULT_TIMEFRAME

    return timeframe


def normalize_symbol(symbol: Any) -> str:
    value = str(symbol or "").strip().upper()

    value = value.replace("NSE:", "")
    value = value.replace("-EQ", "")
    value = value.replace(".NS", "")

    return value


def serialize_value(value: Any) -> Any:
    """
    Convert non-JSON-compatible objects into safe values.
    """

    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, datetime):
        return value.isoformat()

    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass

    if hasattr(value, "to_dict"):
        try:
            return serialize_value(value.to_dict())
        except Exception:
            pass

    if isinstance(value, dict):
        return {
            str(key): serialize_value(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple, set)):
        return [
            serialize_value(item)
            for item in value
        ]

    return str(value)


def extract_results(payload: Any) -> list[dict[str, Any]]:
    """
    Accept scanner output in list, tuple, DataFrame,
    dictionary or object form.
    """

    if payload is None:
        return []

    if hasattr(payload, "to_dict"):
        try:
            records = payload.to_dict(orient="records")

            if isinstance(records, list):
                return [
                    serialize_value(record)
                    for record in records
                    if isinstance(record, dict)
                ]

        except TypeError:
            try:
                converted = payload.to_dict()

                if isinstance(converted, dict):
                    payload = converted

            except Exception:
                pass

        except Exception:
            pass

    if isinstance(payload, tuple):
        if payload and isinstance(payload[0], list):
            payload = payload[0]
        else:
            payload = list(payload)

    if isinstance(payload, dict):
        for key in (
            "results",
            "data",
            "stocks",
            "scanner_results",
            "items",
        ):
            nested_value = payload.get(key)

            if isinstance(nested_value, list):
                payload = nested_value
                break
        else:
            payload = [payload]

    if not isinstance(payload, list):
        return []

    clean_results: list[dict[str, Any]] = []

    for item in payload:
        if isinstance(item, dict):
            clean_results.append(
                serialize_value(item)
            )

        elif hasattr(item, "__dict__"):
            clean_results.append(
                serialize_value(vars(item))
            )

    return clean_results


def stock_signal(stock: dict[str, Any]) -> str:
    for key in (
        "signal",
        "final_signal",
        "recommendation",
        "trade_signal",
        "action",
    ):
        value = stock.get(key)

        if value:
            return str(value).strip().upper()

    return ""


def filter_buy_results(
    results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Dashboard पर केवल confirmed BUY signals दिखेंगे.
    No dummy signal is generated here.
    """

    allowed_signals = {
        "BUY",
        "STRONG BUY",
        "STRONG_BUY",
        "CONFIRMED BUY",
        "CONFIRMED_BUY",
    }

    filtered_results = [
        stock
        for stock in results
        if stock_signal(stock) in allowed_signals
    ]

    def sorting_key(stock: dict[str, Any]) -> tuple:
        signal = stock_signal(stock)

        signal_rank = (
            0
            if signal in {"STRONG BUY", "STRONG_BUY"}
            else 1
        )

        probability = stock.get(
            "move_probability",
            stock.get(
                "probability",
                stock.get(
                    "confidence",
                    stock.get("score", 0),
                ),
            ),
        )

        try:
            probability_number = float(probability)
        except (TypeError, ValueError):
            probability_number = 0.0

        return signal_rank, -probability_number

    filtered_results.sort(key=sorting_key)

    return filtered_results


def find_stock_in_results(
    results: list[dict[str, Any]],
    requested_symbol: str,
) -> Optional[dict[str, Any]]:
    clean_requested_symbol = normalize_symbol(
        requested_symbol
    )

    for stock in results:
        candidate_symbol = normalize_symbol(
            stock.get(
                "symbol",
                stock.get(
                    "stock",
                    stock.get("ticker", ""),
                ),
            )
        )

        if candidate_symbol == clean_requested_symbol:
            return stock

    return None


# ============================================
# FLEXIBLE METHOD CALLER
# ============================================

def call_compatible_method(
    target: Any,
    method_names: tuple[str, ...],
    supplied_arguments: dict[str, Any],
) -> Any:
    """
    Calls the first available compatible method.

    This protects app.py from small method-name differences
    between service files.
    """

    last_error: Optional[Exception] = None

    for method_name in method_names:
        method = getattr(target, method_name, None)

        if not callable(method):
            continue

        try:
            signature = inspect.signature(method)

            accepted_arguments: dict[str, Any] = {}
            accepts_kwargs = False

            for parameter in signature.parameters.values():
                if (
                    parameter.kind
                    == inspect.Parameter.VAR_KEYWORD
                ):
                    accepts_kwargs = True

            if accepts_kwargs:
                accepted_arguments = supplied_arguments.copy()

            else:
                for argument_name, argument_value in (
                    supplied_arguments.items()
                ):
                    if argument_name in signature.parameters:
                        accepted_arguments[argument_name] = (
                            argument_value
                        )

            return method(**accepted_arguments)

        except TypeError as exc:
            last_error = exc

            try:
                if "access_token" in supplied_arguments:
                    return method(
                        supplied_arguments["access_token"]
                    )

                return method()

            except Exception as secondary_error:
                last_error = secondary_error

        except Exception as exc:
            last_error = exc

    if last_error is not None:
        raise last_error

    raise AttributeError(
        "Compatible method was not found. "
        f"Tried: {', '.join(method_names)}"
    )


# ============================================
# SERVICE FACTORIES
# ============================================

def create_fyers_service(
    access_token: Optional[str] = None,
) -> Any:
    if FyersService is None:
        raise RuntimeError(
            "FyersService could not be imported from "
            "fyers_service.py."
        )

    candidate_arguments = [
        {
            "client_id": FYERS_CLIENT_ID,
            "secret_key": FYERS_SECRET_KEY,
            "redirect_uri": FYERS_REDIRECT_URI,
            "access_token": access_token,
        },
        {
            "client_id": FYERS_CLIENT_ID,
            "secret_key": FYERS_SECRET_KEY,
            "redirect_uri": FYERS_REDIRECT_URI,
        },
        {
            "access_token": access_token,
        },
        {},
    ]

    last_error: Optional[Exception] = None

    for arguments in candidate_arguments:
        clean_arguments = {
            key: value
            for key, value in arguments.items()
            if value not in (None, "")
        }

        try:
            service = FyersService(**clean_arguments)

            if access_token:
                for attribute_name in (
                    "access_token",
                    "token",
                ):
                    if hasattr(service, attribute_name):
                        try:
                            setattr(
                                service,
                                attribute_name,
                                access_token,
                            )
                        except Exception:
                            pass

            return service

        except TypeError as exc:
            last_error = exc

    raise RuntimeError(
        "FyersService initialization failed. "
        f"Reason: {last_error}"
    )


def create_fundamental_service() -> Any:
    if FundamentalService is None:
        return None

    candidate_arguments = [
        {"api_key": FMP_API_KEY},
        {"fmp_api_key": FMP_API_KEY},
        {},
    ]

    last_error: Optional[Exception] = None

    for arguments in candidate_arguments:
        clean_arguments = {
            key: value
            for key, value in arguments.items()
            if value not in (None, "")
        }

        try:
            return FundamentalService(
                **clean_arguments
            )

        except TypeError as exc:
            last_error = exc

    logger.warning(
        "FundamentalService initialization failed: %s",
        last_error,
    )

    return None


def create_technical_scanner(
    fyers_service: Any,
) -> Any:
    if TechnicalScanner is None:
        return None

    candidate_arguments = [
        {"fyers_service": fyers_service},
        {"fyers": fyers_service},
        {"data_service": fyers_service},
        {},
    ]

    last_error: Optional[Exception] = None

    for arguments in candidate_arguments:
        try:
            return TechnicalScanner(**arguments)

        except TypeError as exc:
            last_error = exc

    logger.warning(
        "TechnicalScanner initialization failed: %s",
        last_error,
    )

    return None


def create_scanner_engine(
    access_token: str,
) -> Any:
    if ScannerEngine is None:
        raise RuntimeError(
            "ScannerEngine could not be imported from "
            "scanner_engine.py."
        )

    fyers_service = create_fyers_service(
        access_token=access_token
    )

    fundamental_service = create_fundamental_service()

    technical_scanner = create_technical_scanner(
        fyers_service=fyers_service
    )

    candidate_arguments = [
        {
            "fyers_service": fyers_service,
            "technical_scanner": technical_scanner,
            "fundamental_service": fundamental_service,
            "symbols": NIFTY500,
        },
        {
            "fyers": fyers_service,
            "technical_scanner": technical_scanner,
            "fundamental_service": fundamental_service,
            "symbols": NIFTY500,
        },
        {
            "fyers_service": fyers_service,
            "fundamental_service": fundamental_service,
        },
        {
            "fyers": fyers_service,
            "fundamental_service": fundamental_service,
        },
        {
            "fyers_service": fyers_service,
        },
        {
            "fyers": fyers_service,
        },
        {
            "access_token": access_token,
        },
        {},
    ]

    last_error: Optional[Exception] = None

    for arguments in candidate_arguments:
        clean_arguments = {
            key: value
            for key, value in arguments.items()
            if value is not None
        }

        try:
            engine = ScannerEngine(**clean_arguments)

            # Inject available services when supported.
            attribute_values = {
                "fyers_service": fyers_service,
                "fyers": fyers_service,
                "technical_scanner": technical_scanner,
                "fundamental_service": fundamental_service,
                "symbols": NIFTY500,
            }

            for attribute_name, value in (
                attribute_values.items()
            ):
                if (
                    value is not None
                    and hasattr(engine, attribute_name)
                ):
                    try:
                        setattr(
                            engine,
                            attribute_name,
                            value,
                        )
                    except Exception:
                        pass

            return engine

        except TypeError as exc:
            last_error = exc

    raise RuntimeError(
        "ScannerEngine initialization failed. "
        f"Reason: {last_error}"
    )


# ============================================
# AUTHENTICATION HELPERS
# ============================================

def get_access_token() -> Optional[str]:
    token = session.get("access_token")

    if not token:
        return None

    return str(token).strip() or None


def user_is_logged_in() -> bool:
    return bool(get_access_token())


def login_required(
    view_function: Callable[..., Any],
) -> Callable[..., Any]:

    @wraps(view_function)
    def wrapped_view(
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if not user_is_logged_in():
            if request.path.startswith("/api/"):
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "authentication_required",
                            "message": (
                                "FYERS login is required."
                            ),
                        }
                    ),
                    401,
                )

            session["next_url"] = request.url
            return redirect(url_for("login"))

        return view_function(*args, **kwargs)

    return wrapped_view


def store_access_token(
    access_token: str,
) -> None:
    clean_token = str(access_token or "").strip()

    if not clean_token:
        raise ValueError(
            "FYERS access token is empty."
        )

    session.clear()
    session.permanent = True
    session["access_token"] = clean_token
    session["logged_in_at"] = utc_now_iso()

    clear_scanner_cache()


def remove_access_token() -> None:
    session.clear()
    clear_scanner_cache()


# ============================================
# ERROR RESPONSE HELPER
# ============================================

def api_error(
    message: str,
    status_code: int = 500,
    error_code: str = "server_error",
    details: Optional[Any] = None,
):
    payload: dict[str, Any] = {
        "success": False,
        "error": error_code,
        "message": message,
        "timestamp": utc_now_iso(),
    }

    if details is not None and not IS_PRODUCTION:
        payload["details"] = serialize_value(details)

    return jsonify(payload), status_code


# ============================================
# TEMPLATE GLOBAL VALUES
# ============================================

@app.context_processor
def inject_global_template_values() -> dict[str, Any]:
    return {
        "app_name": APP_NAME,
        "app_version": APP_VERSION,
        "is_logged_in": user_is_logged_in(),
        "default_timeframe": DEFAULT_TIMEFRAME,
        "supported_timeframes": sorted(
            SUPPORTED_TIMEFRAMES
        ),
        "current_year": datetime.utcnow().year,
    }


# ============================================
# RESPONSE SECURITY HEADERS
# ============================================

@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = (
        "strict-origin-when-cross-origin"
    )

    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=()"
    )

    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = (
            "no-store, no-cache, must-revalidate, "
            "max-age=0"
        )

    return response


# ============================================
# app.py - Part 1 End
# ============================================
# ============================================
# app.py - Part 2 Start
# Part 1 के बिल्कुल नीचे paste करें
# ============================================


# ============================================
# FYERS AUTHENTICATION FUNCTIONS
# ============================================

def generate_fyers_login_url() -> str:
    """
    FYERS authorization URL generate करता है.
    """

    if not FYERS_CLIENT_ID:
        raise RuntimeError(
            "FYERS_CLIENT_ID missing है। "
            "Render Environment Variables में add करें।"
        )

    if not FYERS_SECRET_KEY:
        raise RuntimeError(
            "FYERS_SECRET_KEY missing है। "
            "Render Environment Variables में add करें।"
        )

    if not FYERS_REDIRECT_URI:
        raise RuntimeError(
            "FYERS_REDIRECT_URI missing है। "
            "Render Environment Variables में callback URL add करें।"
        )

    fyers_service = create_fyers_service()

    login_payload = call_compatible_method(
        target=fyers_service,
        method_names=(
            "generate_auth_url",
            "generate_login_url",
            "get_auth_url",
            "get_login_url",
            "create_auth_url",
            "create_login_url",
        ),
        supplied_arguments={
            "client_id": FYERS_CLIENT_ID,
            "secret_key": FYERS_SECRET_KEY,
            "redirect_uri": FYERS_REDIRECT_URI,
        },
    )

    if isinstance(login_payload, str):
        login_url = login_payload

    elif isinstance(login_payload, dict):
        login_url = (
            login_payload.get("auth_url")
            or login_payload.get("login_url")
            or login_payload.get("url")
            or login_payload.get("data")
        )

    else:
        login_url = None

    if not login_url:
        raise RuntimeError(
            "FYERS login URL generate नहीं हुआ। "
            "fyers_service.py का authorization method check करें।"
        )

    return str(login_url)


def exchange_auth_code_for_token(
    auth_code: str,
) -> str:
    """
    FYERS callback से मिले auth_code को access token में बदलता है.
    """

    clean_auth_code = str(auth_code or "").strip()

    if not clean_auth_code:
        raise ValueError(
            "FYERS callback में auth_code नहीं मिला।"
        )

    fyers_service = create_fyers_service()

    token_payload = call_compatible_method(
        target=fyers_service,
        method_names=(
            "generate_access_token",
            "exchange_auth_code",
            "exchange_code_for_token",
            "get_access_token",
            "create_access_token",
        ),
        supplied_arguments={
            "auth_code": clean_auth_code,
            "code": clean_auth_code,
            "authorization_code": clean_auth_code,
            "client_id": FYERS_CLIENT_ID,
            "secret_key": FYERS_SECRET_KEY,
            "redirect_uri": FYERS_REDIRECT_URI,
        },
    )

    if isinstance(token_payload, str):
        access_token = token_payload

    elif isinstance(token_payload, dict):
        access_token = (
            token_payload.get("access_token")
            or token_payload.get("token")
        )

        if not access_token:
            nested_data = token_payload.get("data")

            if isinstance(nested_data, dict):
                access_token = (
                    nested_data.get("access_token")
                    or nested_data.get("token")
                )

    else:
        access_token = None

    if not access_token:
        error_message = None

        if isinstance(token_payload, dict):
            error_message = (
                token_payload.get("message")
                or token_payload.get("error")
                or token_payload.get("s")
            )

        raise RuntimeError(
            error_message
            or "FYERS access token generate नहीं हुआ।"
        )

    return str(access_token).strip()


# ============================================
# FYERS SESSION VALIDATION
# ============================================

def validate_fyers_session(
    access_token: str,
) -> dict[str, Any]:
    """
    FYERS profile endpoint के माध्यम से token validate करता है.
    """

    fyers_service = create_fyers_service(
        access_token=access_token
    )

    profile_payload = call_compatible_method(
        target=fyers_service,
        method_names=(
            "get_profile",
            "profile",
            "fetch_profile",
            "user_profile",
        ),
        supplied_arguments={
            "access_token": access_token,
        },
    )

    if not isinstance(profile_payload, dict):
        return {
            "valid": True,
            "profile": serialize_value(profile_payload),
        }

    status_value = str(
        profile_payload.get("s")
        or profile_payload.get("status")
        or ""
    ).strip().lower()

    message_value = str(
        profile_payload.get("message")
        or profile_payload.get("error")
        or ""
    ).strip()

    invalid_statuses = {
        "error",
        "failed",
        "failure",
        "false",
    }

    if status_value in invalid_statuses:
        raise RuntimeError(
            message_value
            or "FYERS session invalid है।"
        )

    profile_data = profile_payload.get("data")

    if not isinstance(profile_data, dict):
        profile_data = profile_payload

    return {
        "valid": True,
        "profile": serialize_value(profile_data),
    }


# ============================================
# SCANNER EXECUTION
# ============================================

def execute_live_scanner(
    access_token: str,
    timeframe: str,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """
    Scanner engine run करता है।

    केवल live scanner result इस्तेमाल होंगे।
    यह function कोई dummy stock या fake BUY signal नहीं बनाता।
    """

    normalized_timeframe = normalize_timeframe(
        timeframe
    )

    if (
        not force_refresh
        and scanner_cache_is_valid(
            access_token=access_token,
            timeframe=normalized_timeframe,
        )
    ):
        cached_results = scanner_cache.get(
            "results",
            [],
        )

        return {
            "results": cached_results,
            "updated_at": scanner_cache.get(
                "updated_at"
            ),
            "from_cache": True,
            "timeframe": normalized_timeframe,
            "error": scanner_cache.get("error"),
        }

    if scanner_cache.get("running"):
        existing_results = scanner_cache.get(
            "results",
            [],
        )

        return {
            "results": existing_results,
            "updated_at": scanner_cache.get(
                "updated_at"
            ),
            "from_cache": bool(existing_results),
            "timeframe": normalized_timeframe,
            "error": "Scanner अभी पहले से run हो रहा है।",
        }

    scanner_cache["running"] = True
    scanner_cache["error"] = None

    try:
        scanner_engine = create_scanner_engine(
            access_token=access_token
        )

        symbols = list(NIFTY500)[:MAX_SCAN_SYMBOLS]

        scanner_payload = call_compatible_method(
            target=scanner_engine,
            method_names=(
                "scan_nifty500",
                "run_scan",
                "scan",
                "scan_market",
                "execute_scan",
                "scan_all",
                "get_scanner_results",
            ),
            supplied_arguments={
                "access_token": access_token,
                "symbols": symbols,
                "stock_symbols": symbols,
                "timeframe": normalized_timeframe,
                "investment_timeframe": normalized_timeframe,
                "limit": MAX_SCAN_SYMBOLS,
                "max_symbols": MAX_SCAN_SYMBOLS,
            },
        )

        all_results = extract_results(
            scanner_payload
        )

        buy_results = filter_buy_results(
            all_results
        )

        update_time = utc_now_iso()

        scanner_cache.update(
            {
                "results": buy_results,
                "updated_at": update_time,
                "timestamp": time.time(),
                "timeframe": normalized_timeframe,
                "access_token_hash": get_token_hash(
                    access_token
                ),
                "error": None,
                "running": False,
            }
        )

        logger.info(
            "Scanner completed | timeframe=%s | "
            "total=%s | buy_results=%s",
            normalized_timeframe,
            len(all_results),
            len(buy_results),
        )

        return {
            "results": buy_results,
            "updated_at": update_time,
            "from_cache": False,
            "timeframe": normalized_timeframe,
            "total_scanned_results": len(all_results),
            "buy_count": len(buy_results),
            "error": None,
        }

    except Exception as exc:
        logger.exception(
            "Scanner execution failed"
        )

        scanner_cache.update(
            {
                "error": str(exc),
                "running": False,
            }
        )

        raise


def scan_single_stock(
    access_token: str,
    symbol: str,
    timeframe: str,
) -> Optional[dict[str, Any]]:
    """
    Search/detail के लिए एक specific stock scan करता है.
    """

    clean_symbol = normalize_symbol(symbol)

    if not clean_symbol:
        return None

    scanner_engine = create_scanner_engine(
        access_token=access_token
    )

    fyers_symbol = f"NSE:{clean_symbol}-EQ"

    scanner_payload = call_compatible_method(
        target=scanner_engine,
        method_names=(
            "scan_single_stock",
            "scan_stock",
            "analyze_stock",
            "get_stock_analysis",
            "scan_symbol",
        ),
        supplied_arguments={
            "access_token": access_token,
            "symbol": fyers_symbol,
            "stock_symbol": fyers_symbol,
            "ticker": clean_symbol,
            "timeframe": normalize_timeframe(
                timeframe
            ),
            "investment_timeframe": normalize_timeframe(
                timeframe
            ),
        },
    )

    results = extract_results(scanner_payload)

    if results:
        matched_stock = find_stock_in_results(
            results=results,
            requested_symbol=clean_symbol,
        )

        return matched_stock or results[0]

    if isinstance(scanner_payload, dict):
        return serialize_value(scanner_payload)

    return None


# ============================================
# HOME ROUTE
# ============================================

@app.route("/", methods=["GET"])
def home():
    if user_is_logged_in():
        return redirect(
            url_for("dashboard")
        )

    return render_template(
        "index.html",
        page_title=APP_NAME,
        fyers_configured=bool(
            FYERS_CLIENT_ID
            and FYERS_SECRET_KEY
            and FYERS_REDIRECT_URI
        ),
    )


# ============================================
# LOGIN ROUTE
# ============================================

@app.route("/login", methods=["GET"])
def login():
    if user_is_logged_in():
        return redirect(
            url_for("dashboard")
        )

    try:
        login_url = generate_fyers_login_url()

        return redirect(login_url)

    except Exception as exc:
        logger.exception(
            "FYERS login URL generation failed"
        )

        return render_template(
            "error.html",
            page_title="Login Error",
            error_title="FYERS Login शुरू नहीं हो पाया",
            error_message=str(exc),
            back_url=url_for("home"),
        ), 500


# ============================================
# FYERS CALLBACK ROUTES
# ============================================

@app.route("/callback", methods=["GET"])
@app.route("/fyers/callback", methods=["GET"])
def fyers_callback():
    callback_error = (
        request.args.get("error")
        or request.args.get("message")
        or request.args.get("error_description")
    )

    if callback_error:
        logger.warning(
            "FYERS callback error: %s",
            callback_error,
        )

        return render_template(
            "error.html",
            page_title="FYERS Login Error",
            error_title="FYERS Login असफल रहा",
            error_message=str(callback_error),
            back_url=url_for("login"),
        ), 400

    auth_code = (
        request.args.get("auth_code")
        or request.args.get("code")
    )

    if not auth_code:
        return render_template(
            "error.html",
            page_title="Callback Error",
            error_title="Authorization code नहीं मिला",
            error_message=(
                "FYERS callback URL में auth_code "
                "या code parameter मौजूद नहीं है।"
            ),
            back_url=url_for("login"),
        ), 400

    try:
        access_token = exchange_auth_code_for_token(
            auth_code=auth_code
        )

        store_access_token(
            access_token=access_token
        )

        next_url = session.pop(
            "next_url",
            None,
        )

        if next_url:
            return redirect(next_url)

        return redirect(
            url_for("dashboard")
        )

    except Exception as exc:
        logger.exception(
            "FYERS token exchange failed"
        )

        remove_access_token()

        return render_template(
            "error.html",
            page_title="Token Error",
            error_title="FYERS access token नहीं मिला",
            error_message=str(exc),
            back_url=url_for("login"),
        ), 500


# ============================================
# LOGOUT ROUTE
# ============================================

@app.route("/logout", methods=["GET", "POST"])
def logout():
    remove_access_token()

    return redirect(
        url_for("home")
    )


# ============================================
# DASHBOARD ROUTE
# ============================================

@app.route("/dashboard", methods=["GET"])
@login_required
def dashboard():
    access_token = get_access_token()

    if not access_token:
        return redirect(
            url_for("login")
        )

    timeframe = normalize_timeframe(
        request.args.get("timeframe")
    )

    force_refresh = (
        str(
            request.args.get("refresh", "")
        ).strip().lower()
        in {"1", "true", "yes"}
    )

    scanner_results: list[dict[str, Any]] = []
    scanner_error: Optional[str] = None
    updated_at: Optional[str] = None
    from_cache = False

    try:
        scan_response = execute_live_scanner(
            access_token=access_token,
            timeframe=timeframe,
            force_refresh=force_refresh,
        )

        scanner_results = scan_response.get(
            "results",
            [],
        )

        updated_at = scan_response.get(
            "updated_at"
        )

        from_cache = bool(
            scan_response.get("from_cache")
        )

        scanner_error = scan_response.get(
            "error"
        )

    except Exception as exc:
        scanner_error = str(exc)

        logger.exception(
            "Dashboard scanner failed"
        )

        if (
            "token" in scanner_error.lower()
            or "unauthor" in scanner_error.lower()
            or "invalid session" in scanner_error.lower()
        ):
            remove_access_token()

            return redirect(
                url_for("login")
            )

    return render_template(
        "dashboard.html",
        page_title="Nifty 500 Smart Scanner",
        stocks=scanner_results,
        scanner_results=scanner_results,
        buy_count=len(scanner_results),
        scanner_error=scanner_error,
        updated_at=updated_at,
        from_cache=from_cache,
        selected_timeframe=timeframe,
        cache_seconds=SCANNER_CACHE_SECONDS,
    )


# ============================================
# STOCK DETAIL ROUTE
# ============================================

@app.route(
    "/stock/<string:symbol>",
    methods=["GET"],
)
@login_required
def stock_detail(symbol: str):
    access_token = get_access_token()

    if not access_token:
        return redirect(
            url_for("login")
        )

    timeframe = normalize_timeframe(
        request.args.get("timeframe")
    )

    clean_symbol = normalize_symbol(symbol)

    stock = find_stock_in_results(
        results=scanner_cache.get(
            "results",
            [],
        ),
        requested_symbol=clean_symbol,
    )

    detail_error = None

    if stock is None:
        try:
            stock = scan_single_stock(
                access_token=access_token,
                symbol=clean_symbol,
                timeframe=timeframe,
            )

        except Exception as exc:
            detail_error = str(exc)

            logger.exception(
                "Single stock analysis failed | symbol=%s",
                clean_symbol,
            )

    if stock is None:
        return render_template(
            "detail.html",
            page_title=f"{clean_symbol} Analysis",
            symbol=clean_symbol,
            stock=None,
            detail_error=(
                detail_error
                or "इस stock का live analysis उपलब्ध नहीं है।"
            ),
            selected_timeframe=timeframe,
        ), 404

    return render_template(
        "detail.html",
        page_title=f"{clean_symbol} Analysis",
        symbol=clean_symbol,
        stock=stock,
        detail_error=detail_error,
        selected_timeframe=timeframe,
    )


# ============================================
# STOCK SEARCH ROUTE
# ============================================

@app.route("/search", methods=["GET"])
@login_required
def search_stock():
    access_token = get_access_token()

    if not access_token:
        return redirect(
            url_for("login")
        )

    query = normalize_symbol(
        request.args.get("q")
    )

    timeframe = normalize_timeframe(
        request.args.get("timeframe")
    )

    if not query:
        return redirect(
            url_for(
                "dashboard",
                timeframe=timeframe,
            )
        )

    return redirect(
        url_for(
            "stock_detail",
            symbol=query,
            timeframe=timeframe,
        )
    )


# ============================================
# PROFILE ROUTE
# ============================================

@app.route("/profile", methods=["GET"])
@login_required
def profile():
    access_token = get_access_token()

    if not access_token:
        return redirect(
            url_for("login")
        )

    profile_data = None
    profile_error = None

    try:
        validation_response = validate_fyers_session(
            access_token=access_token
        )

        profile_data = validation_response.get(
            "profile"
        )

    except Exception as exc:
        profile_error = str(exc)

        logger.exception(
            "FYERS profile fetch failed"
        )

    return render_template(
        "profile.html",
        page_title="FYERS Profile",
        profile=profile_data,
        profile_error=profile_error,
    )


# ============================================
# HEALTH CHECK ROUTES
# ============================================

@app.route("/health", methods=["GET"])
def health():
    return jsonify(
        {
            "success": True,
            "status": "healthy",
            "app": APP_NAME,
            "version": APP_VERSION,
            "environment": APP_ENV,
            "timestamp": utc_now_iso(),
        }
    )


@app.route("/api/health", methods=["GET"])
def api_health():
    return jsonify(
        {
            "success": True,
            "status": "healthy",
            "logged_in": user_is_logged_in(),
            "scanner_running": bool(
                scanner_cache.get("running")
            ),
            "last_scan": scanner_cache.get(
                "updated_at"
            ),
            "timestamp": utc_now_iso(),
        }
    )


# ============================================
# SCANNER API ROUTE
# ============================================

@app.route("/api/scanner", methods=["GET"])
@login_required
def api_scanner():
    access_token = get_access_token()

    if not access_token:
        return api_error(
            message="FYERS login required है।",
            status_code=401,
            error_code="authentication_required",
        )

    timeframe = normalize_timeframe(
        request.args.get("timeframe")
    )

    force_refresh = (
        str(
            request.args.get("refresh", "")
        ).strip().lower()
        in {"1", "true", "yes"}
    )

    try:
        scan_response = execute_live_scanner(
            access_token=access_token,
            timeframe=timeframe,
            force_refresh=force_refresh,
        )

        results = scan_response.get(
            "results",
            [],
        )

        return jsonify(
            {
                "success": True,
                "timeframe": timeframe,
                "count": len(results),
                "results": results,
                "updated_at": scan_response.get(
                    "updated_at"
                ),
                "from_cache": scan_response.get(
                    "from_cache",
                    False,
                ),
                "timestamp": utc_now_iso(),
            }
        )

    except Exception as exc:
        logger.exception(
            "Scanner API failed"
        )

        return api_error(
            message=str(exc),
            status_code=500,
            error_code="scanner_failed",
            details=exc,
        )


# ============================================
# SINGLE STOCK API ROUTE
# ============================================

@app.route(
    "/api/stock/<string:symbol>",
    methods=["GET"],
)
@login_required
def api_stock_detail(symbol: str):
    access_token = get_access_token()

    if not access_token:
        return api_error(
            message="FYERS login required है।",
            status_code=401,
            error_code="authentication_required",
        )

    timeframe = normalize_timeframe(
        request.args.get("timeframe")
    )

    clean_symbol = normalize_symbol(symbol)

    try:
        stock = find_stock_in_results(
            results=scanner_cache.get(
                "results",
                [],
            ),
            requested_symbol=clean_symbol,
        )

        if stock is None:
            stock = scan_single_stock(
                access_token=access_token,
                symbol=clean_symbol,
                timeframe=timeframe,
            )

        if stock is None:
            return api_error(
                message=(
                    f"{clean_symbol} का analysis "
                    "नहीं मिला।"
                ),
                status_code=404,
                error_code="stock_not_found",
            )

        return jsonify(
            {
                "success": True,
                "symbol": clean_symbol,
                "timeframe": timeframe,
                "stock": serialize_value(stock),
                "timestamp": utc_now_iso(),
            }
        )

    except Exception as exc:
        logger.exception(
            "Stock API failed | symbol=%s",
            clean_symbol,
        )

        return api_error(
            message=str(exc),
            status_code=500,
            error_code="stock_analysis_failed",
            details=exc,
        )


# ============================================
# PROFILE API ROUTE
# ============================================

@app.route("/api/profile", methods=["GET"])
@login_required
def api_profile():
    access_token = get_access_token()

    if not access_token:
        return api_error(
            message="FYERS login required है।",
            status_code=401,
            error_code="authentication_required",
        )

    try:
        validation_response = validate_fyers_session(
            access_token=access_token
        )

        return jsonify(
            {
                "success": True,
                "profile": validation_response.get(
                    "profile"
                ),
                "timestamp": utc_now_iso(),
            }
        )

    except Exception as exc:
        logger.exception(
            "Profile API failed"
        )

        return api_error(
            message=str(exc),
            status_code=401,
            error_code="invalid_fyers_session",
            details=exc,
        )


# ============================================
# CACHE CLEAR API
# ============================================

@app.route(
    "/api/scanner/clear-cache",
    methods=["POST"],
)
@login_required
def clear_scanner_cache_api():
    clear_scanner_cache()

    return jsonify(
        {
            "success": True,
            "message": "Scanner cache clear हो गया।",
            "timestamp": utc_now_iso(),
        }
    )


# ============================================
# app.py - Part 2 End
# ============================================
# ============================================
# app.py - Part 3A Start
# Part 2 के बिल्कुल नीचे paste करें
# ============================================


# ============================================
# APPLICATION STATUS API
# ============================================

@app.route("/api/status", methods=["GET"])
def api_status():
    """
    Project configuration और scanner status दिखाता है।
    Secret keys या access token expose नहीं करता।
    """

    return jsonify(
        {
            "success": True,
            "application": {
                "name": APP_NAME,
                "version": APP_VERSION,
                "environment": APP_ENV,
            },
            "configuration": {
                "fyers_client_id_configured": bool(
                    FYERS_CLIENT_ID
                ),
                "fyers_secret_configured": bool(
                    FYERS_SECRET_KEY
                ),
                "fyers_redirect_uri_configured": bool(
                    FYERS_REDIRECT_URI
                ),
                "fmp_api_key_configured": bool(
                    FMP_API_KEY
                ),
                "nifty500_symbols_loaded": len(
                    NIFTY500
                ),
                "max_scan_symbols": MAX_SCAN_SYMBOLS,
                "cache_seconds": SCANNER_CACHE_SECONDS,
            },
            "session": {
                "logged_in": user_is_logged_in(),
                "logged_in_at": session.get(
                    "logged_in_at"
                ),
            },
            "scanner": {
                "running": bool(
                    scanner_cache.get("running")
                ),
                "last_updated_at": scanner_cache.get(
                    "updated_at"
                ),
                "cached_result_count": len(
                    scanner_cache.get(
                        "results",
                        [],
                    )
                ),
                "cached_timeframe": scanner_cache.get(
                    "timeframe"
                ),
                "last_error": scanner_cache.get(
                    "error"
                ),
            },
            "timestamp": utc_now_iso(),
        }
    )


# ============================================
# MANUAL SCANNER REFRESH
# ============================================

@app.route(
    "/api/scanner/refresh",
    methods=["POST"],
)
@login_required
def api_scanner_refresh():
    """
    Scanner को force refresh करता है।
    Request JSON में timeframe भेज सकते हैं।
    """

    access_token = get_access_token()

    if not access_token:
        return api_error(
            message="FYERS login required है।",
            status_code=401,
            error_code="authentication_required",
        )

    request_payload = request.get_json(
        silent=True
    ) or {}

    timeframe = normalize_timeframe(
        request_payload.get("timeframe")
        or request.form.get("timeframe")
        or request.args.get("timeframe")
    )

    if scanner_cache.get("running"):
        return api_error(
            message=(
                "Scanner पहले से run हो रहा है। "
                "कुछ समय बाद दोबारा refresh करें।"
            ),
            status_code=409,
            error_code="scanner_already_running",
        )

    try:
        scan_response = execute_live_scanner(
            access_token=access_token,
            timeframe=timeframe,
            force_refresh=True,
        )

        results = scan_response.get(
            "results",
            [],
        )

        return jsonify(
            {
                "success": True,
                "message": (
                    "Live scanner refresh पूरा हुआ।"
                ),
                "timeframe": timeframe,
                "buy_count": len(results),
                "results": results,
                "updated_at": scan_response.get(
                    "updated_at"
                ),
                "timestamp": utc_now_iso(),
            }
        )

    except Exception as exc:
        logger.exception(
            "Manual scanner refresh failed"
        )

        return api_error(
            message=str(exc),
            status_code=500,
            error_code="scanner_refresh_failed",
            details=exc,
        )


# ============================================
# SEARCH STOCK API
# ============================================

@app.route("/api/search", methods=["GET"])
@login_required
def api_search_stock():
    """
    किसी भी stock को search करके उसका live analysis देता है।
    BUY signal न होने पर भी scanner engine का पूरा result लौटाता है।
    """

    access_token = get_access_token()

    if not access_token:
        return api_error(
            message="FYERS login required है।",
            status_code=401,
            error_code="authentication_required",
        )

    query = normalize_symbol(
        request.args.get("q")
        or request.args.get("symbol")
    )

    timeframe = normalize_timeframe(
        request.args.get("timeframe")
    )

    if not query:
        return api_error(
            message="Stock symbol enter करें।",
            status_code=400,
            error_code="symbol_required",
        )

    try:
        cached_stock = find_stock_in_results(
            results=scanner_cache.get(
                "results",
                [],
            ),
            requested_symbol=query,
        )

        if cached_stock is not None:
            return jsonify(
                {
                    "success": True,
                    "symbol": query,
                    "timeframe": timeframe,
                    "source": "scanner_cache",
                    "stock": cached_stock,
                    "timestamp": utc_now_iso(),
                }
            )

        stock = scan_single_stock(
            access_token=access_token,
            symbol=query,
            timeframe=timeframe,
        )

        if stock is None:
            return api_error(
                message=(
                    f"{query} का live analysis "
                    "नहीं मिला। Symbol check करें।"
                ),
                status_code=404,
                error_code="stock_not_found",
            )

        return jsonify(
            {
                "success": True,
                "symbol": query,
                "timeframe": timeframe,
                "source": "live_scan",
                "stock": serialize_value(stock),
                "timestamp": utc_now_iso(),
            }
        )

    except Exception as exc:
        logger.exception(
            "Search API failed | symbol=%s",
            query,
        )

        return api_error(
            message=str(exc),
            status_code=500,
            error_code="stock_search_failed",
            details=exc,
        )


# ============================================
# TIMEFRAMES API
# ============================================

@app.route("/api/timeframes", methods=["GET"])
def api_timeframes():
    timeframe_labels = {
        "swing": "Swing — 15 से 20 दिन",
        "quarterly": "Quarterly — 3 महीने",
        "half_yearly": "Half-Yearly — 6 महीने",
        "yearly": "Yearly — 1 वर्ष",
        "five_year": "Long Term — 5 वर्ष",
        "ten_year": "Long Term — 10 वर्ष",
    }

    timeframes = [
        {
            "value": timeframe,
            "label": timeframe_labels.get(
                timeframe,
                timeframe.replace(
                    "_",
                    " ",
                ).title(),
            ),
            "default": (
                timeframe == DEFAULT_TIMEFRAME
            ),
        }
        for timeframe in sorted(
            SUPPORTED_TIMEFRAMES
        )
    ]

    return jsonify(
        {
            "success": True,
            "timeframes": timeframes,
            "default": DEFAULT_TIMEFRAME,
            "timestamp": utc_now_iso(),
        }
    )


# ============================================
# SCANNER CACHE INFORMATION
# ============================================

@app.route(
    "/api/scanner/cache",
    methods=["GET"],
)
@login_required
def api_scanner_cache():
    cached_timestamp = float(
        scanner_cache.get("timestamp") or 0
    )

    cache_age_seconds = (
        max(
            0,
            int(time.time() - cached_timestamp),
        )
        if cached_timestamp
        else None
    )

    expires_in_seconds = (
        max(
            0,
            SCANNER_CACHE_SECONDS
            - cache_age_seconds,
        )
        if cache_age_seconds is not None
        else 0
    )

    return jsonify(
        {
            "success": True,
            "cache": {
                "result_count": len(
                    scanner_cache.get(
                        "results",
                        [],
                    )
                ),
                "updated_at": scanner_cache.get(
                    "updated_at"
                ),
                "timeframe": scanner_cache.get(
                    "timeframe"
                ),
                "running": bool(
                    scanner_cache.get("running")
                ),
                "error": scanner_cache.get(
                    "error"
                ),
                "age_seconds": cache_age_seconds,
                "expires_in_seconds": (
                    expires_in_seconds
                ),
                "cache_duration_seconds": (
                    SCANNER_CACHE_SECONDS
                ),
            },
            "timestamp": utc_now_iso(),
        }
    )


# ============================================
# LOGIN STATUS API
# ============================================

@app.route(
    "/api/auth/status",
    methods=["GET"],
)
def api_auth_status():
    return jsonify(
        {
            "success": True,
            "logged_in": user_is_logged_in(),
            "logged_in_at": session.get(
                "logged_in_at"
            ),
            "timestamp": utc_now_iso(),
        }
    )


# ============================================
# SESSION VALIDATION API
# ============================================

@app.route(
    "/api/auth/validate",
    methods=["GET"],
)
@login_required
def api_validate_session():
    access_token = get_access_token()

    if not access_token:
        return api_error(
            message="FYERS login required है।",
            status_code=401,
            error_code="authentication_required",
        )

    try:
        validation_result = validate_fyers_session(
            access_token=access_token
        )

        return jsonify(
            {
                "success": True,
                "valid": True,
                "profile": validation_result.get(
                    "profile"
                ),
                "timestamp": utc_now_iso(),
            }
        )

    except Exception as exc:
        logger.warning(
            "FYERS session validation failed: %s",
            exc,
        )

        remove_access_token()

        return api_error(
            message=(
                "FYERS session expire या invalid है। "
                "दोबारा login करें।"
            ),
            status_code=401,
            error_code="invalid_fyers_session",
            details=exc,
        )


# ============================================
# ROBOTS.TXT
# ============================================

@app.route("/robots.txt", methods=["GET"])
def robots_txt():
    return (
        "User-agent: *\n"
        "Disallow: /dashboard\n"
        "Disallow: /stock/\n"
        "Disallow: /profile\n"
        "Disallow: /api/\n",
        200,
        {
            "Content-Type": (
                "text/plain; charset=utf-8"
            )
        },
    )


# ============================================
# FAVICON FALLBACK
# ============================================

@app.route("/favicon.ico", methods=["GET"])
def favicon():
    return "", 204


# ============================================
# app.py - Part 3A End
# ============================================


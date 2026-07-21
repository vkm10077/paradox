from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence

import pandas as pd
import pytz
from fyers_apiv3 import fyersModel

from config import FyersConfig, load_fyers_config


logger = logging.getLogger(__name__)


class FyersServiceError(RuntimeError):
    """
    FYERS authentication, quotes या historical-data errors के लिए
    application-level exception।
    """


@dataclass(frozen=True)
class HistoricalRequest:
    symbol: str
    resolution: str
    range_from: str
    range_to: str
    date_format: str = "1"
    continuous: str = "1"
    open_interest: str = "0"


class FyersService:
    """
    FYERS API v3 के लिए complete live-data service।

    यह service:
    - FYERS login URL बनाती है
    - Auth code से access token बनाती है
    - Access token verify करती है
    - User profile पढ़ती है
    - Live quotes पढ़ती है
    - Historical OHLCV candles पढ़ती है
    - Nifty 500 scanner के लिए symbols को batches में fetch करती है
    """

    MAX_QUOTE_SYMBOLS_PER_REQUEST = 50

    def __init__(
        self,
        access_token: Optional[str] = None,
        config: Optional[FyersConfig] = None,
    ) -> None:
        self.config = config or load_fyers_config()
        self.access_token = self._clean_text(access_token)

        self._client: Optional[fyersModel.FyersModel] = None

        if self.access_token:
            self._client = self._build_client(self.access_token)

    # =========================================================
    # BASIC HELPERS
    # =========================================================

    @staticmethod
    def _clean_text(value: Any) -> str:
        if value is None:
            return ""

        return str(value).strip()

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        """
        Stock symbol को FYERS-compatible NSE equity format में बदलता है।

        Examples:
        RELIANCE          -> NSE:RELIANCE-EQ
        NSE:RELIANCE-EQ   -> NSE:RELIANCE-EQ
        RELIANCE-EQ       -> NSE:RELIANCE-EQ
        """

        cleaned = str(symbol or "").strip().upper()

        if not cleaned:
            raise FyersServiceError("Stock symbol is required.")

        if ":" in cleaned:
            exchange, instrument = cleaned.split(":", 1)

            exchange = exchange.strip()
            instrument = instrument.strip()

            if not exchange or not instrument:
                raise FyersServiceError(
                    f"Invalid FYERS symbol format: {symbol}"
                )

            if exchange == "NSE" and "-" not in instrument:
                instrument = f"{instrument}-EQ"

            return f"{exchange}:{instrument}"

        cleaned = cleaned.replace("NSE:", "")

        if not cleaned.endswith("-EQ"):
            cleaned = f"{cleaned}-EQ"

        return f"NSE:{cleaned}"

    @staticmethod
    def clean_display_symbol(symbol: str) -> str:
        """
        NSE:RELIANCE-EQ को RELIANCE में बदलता है।
        """

        cleaned = str(symbol or "").strip().upper()
        cleaned = cleaned.replace("NSE:", "")

        if cleaned.endswith("-EQ"):
            cleaned = cleaned[:-3]

        return cleaned

    @staticmethod
    def _chunks(
        values: Sequence[str],
        size: int,
    ) -> Iterable[Sequence[str]]:
        for start in range(0, len(values), size):
            yield values[start:start + size]

    @staticmethod
    def _require_success(
        response: Any,
        operation: str,
    ) -> Dict[str, Any]:
        """
        FYERS response validate करता है।
        """

        if not isinstance(response, dict):
            raise FyersServiceError(
                f"{operation} failed: invalid response received from FYERS."
            )

        status = str(response.get("s", "")).strip().lower()
        code = response.get("code")
        message = (
            response.get("message")
            or response.get("msg")
            or "Unknown FYERS API error."
        )

        if status not in {"ok", "success"}:
            raise FyersServiceError(
                f"{operation} failed"
                f"{f' (code {code})' if code is not None else ''}: "
                f"{message}"
            )

        return response

    # =========================================================
    # AUTHENTICATION
    # =========================================================

    def create_login_url(self) -> str:
        """
        FYERS OAuth login URL बनाता है।
        """

        try:
            session = fyersModel.SessionModel(
                client_id=self.config.client_id,
                secret_key=self.config.secret_key,
                redirect_uri=self.config.redirect_uri,
                response_type=self.config.response_type,
                grant_type=self.config.grant_type,
            )

            login_url = session.generate_authcode()

            if not login_url:
                raise FyersServiceError(
                    "FYERS login URL could not be generated."
                )

            return str(login_url)

        except FyersServiceError:
            raise

        except Exception as exc:
            logger.exception("FYERS login URL generation failed.")

            raise FyersServiceError(
                f"FYERS login URL generation failed: {exc}"
            ) from exc

    def exchange_auth_code(self, auth_code: str) -> str:
        """
        Redirect callback से मिले auth_code को access token में बदलता है।
        """

        cleaned_auth_code = self._clean_text(auth_code)

        if not cleaned_auth_code:
            raise FyersServiceError(
                "FYERS auth code is missing."
            )

        try:
            session = fyersModel.SessionModel(
                client_id=self.config.client_id,
                secret_key=self.config.secret_key,
                redirect_uri=self.config.redirect_uri,
                response_type=self.config.response_type,
                grant_type=self.config.grant_type,
            )

            session.set_token(cleaned_auth_code)
            response = session.generate_token()

            validated = self._require_success(
                response,
                "FYERS access-token generation",
            )

            access_token = self._clean_text(
                validated.get("access_token")
            )

            if not access_token:
                raise FyersServiceError(
                    "FYERS returned success but access_token is missing."
                )

            self.set_access_token(access_token)

            return access_token

        except FyersServiceError:
            raise

        except Exception as exc:
            logger.exception(
                "FYERS auth-code exchange failed."
            )

            raise FyersServiceError(
                f"FYERS auth-code exchange failed: {exc}"
            ) from exc

    def set_access_token(self, access_token: str) -> None:
        """
        Current service में access token set करता है।
        """

        cleaned_token = self._clean_text(access_token)

        if not cleaned_token:
            raise FyersServiceError(
                "FYERS access token is required."
            )

        self.access_token = cleaned_token
        self._client = self._build_client(cleaned_token)

    def _build_client(
        self,
        access_token: str,
    ) -> fyersModel.FyersModel:
        """
        Authenticated FYERS client बनाता है।
        """

        try:
            return fyersModel.FyersModel(
                client_id=self.config.client_id,
                token=access_token,
                is_async=False,
                log_path="",
            )

        except Exception as exc:
            logger.exception(
                "Authenticated FYERS client creation failed."
            )

            raise FyersServiceError(
                f"FYERS client creation failed: {exc}"
            ) from exc

    def get_client(self) -> fyersModel.FyersModel:
        """
        Authenticated client return करता है।
        """

        if self._client is None:
            if not self.access_token:
                raise FyersServiceError(
                    "FYERS access token is not available. "
                    "Please log in to FYERS."
                )

            self._client = self._build_client(
                self.access_token
            )

        return self._client

    def verify_access_token(self) -> bool:
        """
        Profile endpoint call करके token validity verify करता है।
        """

        try:
            self.get_profile()
            return True

        except FyersServiceError:
            return False

    # =========================================================
    # PROFILE
    # =========================================================

    def get_profile(self) -> Dict[str, Any]:
        """
        Logged-in FYERS user profile return करता है।
        """

        client = self.get_client()

        try:
            response = client.get_profile()

            validated = self._require_success(
                response,
                "FYERS profile request",
            )

            profile = validated.get("data")

            if not isinstance(profile, dict):
                profile = {}

            return profile

        except FyersServiceError:
            raise

        except Exception as exc:
            logger.exception(
                "FYERS profile request failed."
            )

            raise FyersServiceError(
                f"FYERS profile request failed: {exc}"
            ) from exc

    # =========================================================
    # LIVE QUOTES
    # =========================================================

    def get_quote(
        self,
        symbol: str,
    ) -> Dict[str, Any]:
        """
        एक stock का live quote return करता है।
        """

        results = self.get_quotes([symbol])

        if not results:
            raise FyersServiceError(
                f"No live quote was returned for {symbol}."
            )

        return results[0]

    def get_quotes(
        self,
        symbols: Sequence[str],
        request_delay_seconds: float = 0.20,
    ) -> List[Dict[str, Any]]:
        """
        Multiple symbols के live quotes batches में fetch करता है।

        कोई missing या failed quote के लिए fake price नहीं बनती।
        """

        if not symbols:
            return []

        normalized_symbols: List[str] = []
        seen = set()

        for symbol in symbols:
            normalized = self.normalize_symbol(symbol)

            if normalized not in seen:
                normalized_symbols.append(normalized)
                seen.add(normalized)

        client = self.get_client()
        all_quotes: List[Dict[str, Any]] = []

        batches = list(
            self._chunks(
                normalized_symbols,
                self.MAX_QUOTE_SYMBOLS_PER_REQUEST,
            )
        )

        for batch_index, batch in enumerate(batches):
            payload = {
                "symbols": ",".join(batch)
            }

            try:
                response = client.quotes(
                    data=payload
                )

                validated = self._require_success(
                    response,
                    "FYERS quotes request",
                )

                quote_rows = validated.get("d", [])

                if not isinstance(quote_rows, list):
                    quote_rows = []

                for quote_row in quote_rows:
                    parsed = self._parse_quote_row(
                        quote_row
                    )

                    if parsed:
                        all_quotes.append(parsed)

            except FyersServiceError:
                raise

            except Exception as exc:
                logger.exception(
                    "FYERS quote batch failed."
                )

                raise FyersServiceError(
                    f"FYERS quote request failed: {exc}"
                ) from exc

            if (
                request_delay_seconds > 0
                and batch_index < len(batches) - 1
            ):
                time.sleep(request_delay_seconds)

        return all_quotes

    def _parse_quote_row(
        self,
        quote_row: Any,
    ) -> Optional[Dict[str, Any]]:
        """
        FYERS quote response को scanner-friendly structure में बदलता है।
        """

        if not isinstance(quote_row, dict):
            return None

        values = quote_row.get("v")

        if not isinstance(values, dict):
            return None

        fyers_symbol = (
            quote_row.get("n")
            or values.get("symbol")
            or ""
        )

        fyers_symbol = self._clean_text(fyers_symbol)

        if not fyers_symbol:
            return None

        def number(
            key: str,
            default: Optional[float] = None,
        ) -> Optional[float]:
            value = values.get(key)

            if value in {None, ""}:
                return default

            try:
                return float(value)

            except (TypeError, ValueError):
                return default

        return {
            "symbol": fyers_symbol,
            "display_symbol": self.clean_display_symbol(
                fyers_symbol
            ),
            "current_price": number("lp"),
            "open": number("open_price"),
            "high": number("high_price"),
            "low": number("low_price"),
            "previous_close": number("prev_close_price"),
            "change": number("ch"),
            "change_percent": number("chp"),
            "volume": number("volume"),
            "bid": number("bid"),
            "ask": number("ask"),
            "spread": number("spread"),
            "description": values.get("description"),
            "exchange": values.get("exchange"),
            "short_name": values.get("short_name"),
            "original_name": values.get("original_name"),
            "timestamp": values.get("tt"),
        }

    # =========================================================
    # HISTORICAL CANDLES
    # =========================================================

    def get_historical_data(
        self,
        symbol: str,
        resolution: str,
        range_from: str,
        range_to: str,
        date_format: str = "1",
        continuous: str = "1",
        open_interest: str = "0",
    ) -> pd.DataFrame:
        """
        FYERS historical OHLCV candles DataFrame में return करता है।

        DataFrame columns:
        datetime, timestamp, open, high, low, close, volume
        """

        request_data = HistoricalRequest(
            symbol=self.normalize_symbol(symbol),
            resolution=self._clean_text(resolution),
            range_from=self._clean_text(range_from),
            range_to=self._clean_text(range_to),
            date_format=self._clean_text(date_format),
            continuous=self._clean_text(continuous),
            open_interest=self._clean_text(open_interest),
        )

        if not request_data.resolution:
            raise FyersServiceError(
                "Historical-data resolution is required."
            )

        if not request_data.range_from:
            raise FyersServiceError(
                "Historical-data start date is required."
            )

        if not request_data.range_to:
            raise FyersServiceError(
                "Historical-data end date is required."
            )

        payload = {
            "symbol": request_data.symbol,
            "resolution": request_data.resolution,
            "date_format": request_data.date_format,
            "range_from": request_data.range_from,
            "range_to": request_data.range_to,
            "cont_flag": request_data.continuous,
            "oi_flag": request_data.open_interest,
        }

        client = self.get_client()

        try:
            response = client.history(
                data=payload
            )

            validated = self._require_success(
                response,
                f"FYERS historical-data request for "
                f"{request_data.symbol}",
            )

            candles = validated.get("candles")

            if not isinstance(candles, list):
                raise FyersServiceError(
                    f"No historical candles were returned for "
                    f"{request_data.symbol}."
                )

            dataframe = self._candles_to_dataframe(
                candles
            )

            if dataframe.empty:
                raise FyersServiceError(
                    f"Historical data is empty for "
                    f"{request_data.symbol}."
                )

            return dataframe

        except FyersServiceError:
            raise

        except Exception as exc:
            logger.exception(
                "FYERS historical-data request failed."
            )

            raise FyersServiceError(
                f"FYERS historical-data request failed for "
                f"{request_data.symbol}: {exc}"
            ) from exc

    def get_daily_history(
        self,
        symbol: str,
        days: int = 420,
        end_date: Optional[date] = None,
    ) -> pd.DataFrame:
        """
        Daily historical candles का convenient helper।
        """

        if days < 1:
            raise FyersServiceError(
                "Historical days must be at least 1."
            )

        final_end_date = end_date or date.today()
        start_date = final_end_date - timedelta(
            days=days
        )

        return self.get_historical_data(
            symbol=symbol,
            resolution="D",
            range_from=start_date.strftime("%Y-%m-%d"),
            range_to=final_end_date.strftime("%Y-%m-%d"),
            date_format="1",
            continuous="1",
            open_interest="0",
        )

    @staticmethod
    def _candles_to_dataframe(
        candles: List[Any],
    ) -> pd.DataFrame:
        """
        FYERS candle array को clean pandas DataFrame में बदलता है।
        """

        valid_rows: List[List[Any]] = []

        for candle in candles:
            if not isinstance(candle, (list, tuple)):
                continue

            if len(candle) < 6:
                continue

            valid_rows.append(
                list(candle[:6])
            )

        if not valid_rows:
            return pd.DataFrame(
                columns=[
                    "datetime",
                    "timestamp",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                ]
            )

        dataframe = pd.DataFrame(
            valid_rows,
            columns=[
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
            ],
        )

        numeric_columns = [
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
        ]

        for column in numeric_columns:
            dataframe[column] = pd.to_numeric(
                dataframe[column],
                errors="coerce",
            )

        dataframe.dropna(
            subset=[
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
            ],
            inplace=True,
        )

        dataframe["timestamp"] = (
            dataframe["timestamp"].astype("int64")
        )

        dataframe["datetime"] = pd.to_datetime(
            dataframe["timestamp"],
            unit="s",
            utc=True,
        ).dt.tz_convert("Asia/Kolkata")

        dataframe.sort_values(
            "timestamp",
            inplace=True,
        )

        dataframe.drop_duplicates(
            subset=["timestamp"],
            keep="last",
            inplace=True,
        )

        dataframe.reset_index(
            drop=True,
            inplace=True,
        )

        dataframe = dataframe[
            [
                "datetime",
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
            ]
        ]

        return dataframe

    # =========================================================
    # MARKET TIME
    # =========================================================

    @staticmethod
    def india_now() -> datetime:
        """
        Current Indian time return करता है।
        """

        india_timezone = pytz.timezone(
            "Asia/Kolkata"
        )

        return datetime.now(
            india_timezone
        )

    @classmethod
    def is_regular_market_open(cls) -> bool:
        """
        Basic NSE regular-market time check।

        यह केवल weekday और सामान्य 09:15–15:30 window check है।
        Exchange holiday calendar बाद में अलग service में जोड़ा जाएगा।
        """

        now = cls.india_now()

        if now.weekday() >= 5:
            return False

        market_open = now.replace(
            hour=9,
            minute=15,
            second=0,
            microsecond=0,
        )

        market_close = now.replace(
            hour=15,
            minute=30,
            second=0,
            microsecond=0,
        )

        return market_open <= now <= market_close

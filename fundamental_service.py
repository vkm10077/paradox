from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

import requests


logger = logging.getLogger(__name__)


class FundamentalServiceError(RuntimeError):
    """
    FMP authentication, symbol resolution, API response या
    fundamental-data processing errors के लिए application exception.
    """


@dataclass(frozen=True)
class FundamentalSettings:
    """
    Fundamental scoring thresholds.

    Maximum fundamental score: 30
    """

    minimum_roe_percent: float = 15.0
    strong_roe_percent: float = 20.0

    minimum_roic_percent: float = 12.0
    strong_roic_percent: float = 18.0

    maximum_debt_to_equity: float = 1.0
    strong_debt_to_equity: float = 0.5

    minimum_revenue_growth_percent: float = 10.0
    strong_revenue_growth_percent: float = 15.0

    minimum_eps_growth_percent: float = 10.0
    strong_eps_growth_percent: float = 15.0

    minimum_net_income_growth_percent: float = 10.0
    strong_net_income_growth_percent: float = 15.0

    minimum_operating_cash_flow: float = 0.0
    minimum_free_cash_flow: float = 0.0

    minimum_current_ratio: float = 1.0
    preferred_current_ratio: float = 1.5

    maximum_pe_ratio: float = 60.0
    maximum_price_to_book: float = 12.0

    cache_seconds: int = 21600
    request_timeout_seconds: int = 25
    maximum_retries: int = 3
    retry_base_delay_seconds: float = 1.5


@dataclass
class CacheEntry:
    expires_at: datetime
    value: Any


class FundamentalService:
    """
    Financial Modeling Prep API से real fundamental data service.

    यह service:

    - FMP API key environment variable से पढ़ती है
    - Indian/NSE symbol resolve करती है
    - Company profile validate करती है
    - TTM financial ratios पढ़ती है
    - TTM key metrics पढ़ती है
    - Income-statement growth पढ़ती है
    - Missing data को स्पष्ट रूप से unavailable रखती है
    - Available metrics पर maximum 30 marks का score बनाती है
    - API rate limit और temporary server errors handle करती है
    - Fundamental data cache करती है

    Environment variables:

    FMP_API_KEY
    FMP_BASE_URL
    FMP_CACHE_SECONDS
    FMP_REQUEST_TIMEOUT_SECONDS
    FMP_MAX_RETRIES
    FMP_SYMBOL_OVERRIDES

    FMP_SYMBOL_OVERRIDES optional JSON example:

    {
        "RELIANCE": "RELIANCE.NS",
        "M&M": "M&M.NS"
    }
    """

    DEFAULT_BASE_URL = "https://financialmodelingprep.com/stable"

    PROFILE_ENDPOINT = "profile"
    RATIOS_TTM_ENDPOINT = "ratios-ttm"
    KEY_METRICS_TTM_ENDPOINT = "key-metrics-ttm"
    INCOME_GROWTH_ENDPOINT = "income-statement-growth"
    INCOME_STATEMENT_ENDPOINT = "income-statement"
    BALANCE_SHEET_ENDPOINT = "balance-sheet-statement"
    CASH_FLOW_ENDPOINT = "cash-flow-statement"

    MAXIMUM_SCORE = 30

    def __init__(
        self,
        api_key: Optional[str] = None,
        settings: Optional[FundamentalSettings] = None,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.api_key = (
            api_key
            or os.getenv("FMP_API_KEY", "")
        ).strip()

        if not self.api_key:
            raise FundamentalServiceError(
                "Required environment variable "
                "'FMP_API_KEY' is missing."
            )

        self.base_url = (
            os.getenv(
                "FMP_BASE_URL",
                self.DEFAULT_BASE_URL,
            )
            .strip()
            .rstrip("/")
        )

        if not self.base_url.startswith("https://"):
            raise FundamentalServiceError(
                "FMP_BASE_URL must use HTTPS."
            )

        self.settings = settings or self._load_settings()
        self.session = session or self._build_session()

        self.symbol_overrides = (
            self._load_symbol_overrides()
        )

        self._cache: Dict[str, CacheEntry] = {}
        self._cache_lock = threading.RLock()

    # =========================================================
    # CONFIGURATION
    # =========================================================

    def _load_settings(self) -> FundamentalSettings:
        return FundamentalSettings(
            cache_seconds=self._read_integer_env(
                "FMP_CACHE_SECONDS",
                21600,
                minimum=300,
            ),
            request_timeout_seconds=self._read_integer_env(
                "FMP_REQUEST_TIMEOUT_SECONDS",
                25,
                minimum=5,
            ),
            maximum_retries=self._read_integer_env(
                "FMP_MAX_RETRIES",
                3,
                minimum=1,
            ),
            retry_base_delay_seconds=self._read_float_env(
                "FMP_RETRY_BASE_DELAY_SECONDS",
                1.5,
                minimum=0.25,
            ),
        )

    @staticmethod
    def _read_integer_env(
        name: str,
        default: int,
        minimum: int,
    ) -> int:
        raw_value = os.getenv(
            name,
            str(default),
        ).strip()

        try:
            value = int(raw_value)
        except ValueError as exc:
            raise FundamentalServiceError(
                f"{name} must be an integer."
            ) from exc

        if value < minimum:
            raise FundamentalServiceError(
                f"{name} must be at least {minimum}."
            )

        return value

    @staticmethod
    def _read_float_env(
        name: str,
        default: float,
        minimum: float,
    ) -> float:
        raw_value = os.getenv(
            name,
            str(default),
        ).strip()

        try:
            value = float(raw_value)
        except ValueError as exc:
            raise FundamentalServiceError(
                f"{name} must be a number."
            ) from exc

        if value < minimum:
            raise FundamentalServiceError(
                f"{name} must be at least {minimum}."
            )

        return value

    @staticmethod
    def _build_session() -> requests.Session:
        session = requests.Session()

        session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": (
                    "Paradox-Nifty500-Scanner/1.0"
                ),
                "Connection": "keep-alive",
            }
        )

        return session

    def _load_symbol_overrides(self) -> Dict[str, str]:
        raw_value = os.getenv(
            "FMP_SYMBOL_OVERRIDES",
            "",
        ).strip()

        if not raw_value:
            return {}

        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError as exc:
            raise FundamentalServiceError(
                "FMP_SYMBOL_OVERRIDES must be valid JSON."
            ) from exc

        if not isinstance(parsed, dict):
            raise FundamentalServiceError(
                "FMP_SYMBOL_OVERRIDES must be a JSON object."
            )

        cleaned: Dict[str, str] = {}

        for source_symbol, fmp_symbol in parsed.items():
            source = self.clean_nse_symbol(
                str(source_symbol)
            )

            target = str(fmp_symbol or "").strip().upper()

            if source and target:
                cleaned[source] = target

        return cleaned

    # =========================================================
    # PUBLIC METHODS
    # =========================================================

    def analyze(
        self,
        symbol: str,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """
        एक NSE stock का complete fundamental analysis return करता है.
        """

        nse_symbol = self.clean_nse_symbol(symbol)

        if not nse_symbol:
            raise FundamentalServiceError(
                "Stock symbol is required."
            )

        cache_key = f"fundamental:{nse_symbol}"

        if not force_refresh:
            cached = self._get_cache(cache_key)

            if cached is not None:
                return cached

        resolved_symbol, profile = self.resolve_symbol(
            nse_symbol=nse_symbol,
            force_refresh=force_refresh,
        )

        ratios = self.get_ratios_ttm(
            resolved_symbol,
            force_refresh=force_refresh,
        )

        key_metrics = self.get_key_metrics_ttm(
            resolved_symbol,
            force_refresh=force_refresh,
        )

        growth = self.get_income_statement_growth(
            resolved_symbol,
            force_refresh=force_refresh,
        )

        income_statement = self.get_income_statement(
            resolved_symbol,
            force_refresh=force_refresh,
        )

        balance_sheet = self.get_balance_sheet(
            resolved_symbol,
            force_refresh=force_refresh,
        )

        cash_flow = self.get_cash_flow_statement(
            resolved_symbol,
            force_refresh=force_refresh,
        )

        metrics = self.extract_metrics(
            ratios=ratios,
            key_metrics=key_metrics,
            growth=growth,
            income_statement=income_statement,
            balance_sheet=balance_sheet,
            cash_flow=cash_flow,
        )

        score_result = self.calculate_fundamental_score(
            metrics
        )

        result = {
            "symbol": nse_symbol,
            "fmp_symbol": resolved_symbol,
            "company_name": self._first_text(
                profile,
                [
                    "companyName",
                    "name",
                ],
            ),
            "sector": self._first_text(
                profile,
                ["sector"],
            ),
            "industry": self._first_text(
                profile,
                ["industry"],
            ),
            "exchange": self._first_text(
                profile,
                [
                    "exchange",
                    "exchangeShortName",
                ],
            ),
            "country": self._first_text(
                profile,
                [
                    "country",
                    "countryCode",
                ],
            ),
            "currency": self._first_text(
                profile,
                ["currency"],
            ),
            "website": self._first_text(
                profile,
                ["website"],
            ),
            "metrics": metrics,
            "fundamental_score": score_result[
                "fundamental_score"
            ],
            "available_score": score_result[
                "available_score"
            ],
            "maximum_score": self.MAXIMUM_SCORE,
            "coverage_percent": score_result[
                "coverage_percent"
            ],
            "normalized_score_percent": score_result[
                "normalized_score_percent"
            ],
            "fundamental_signal": score_result[
                "fundamental_signal"
            ],
            "positive_conditions": score_result[
                "positive_conditions"
            ],
            "negative_conditions": score_result[
                "negative_conditions"
            ],
            "missing_conditions": score_result[
                "missing_conditions"
            ],
            "data_sources": {
                "profile": bool(profile),
                "ratios_ttm": bool(ratios),
                "key_metrics_ttm": bool(
                    key_metrics
                ),
                "income_statement_growth": bool(
                    growth
                ),
                "income_statement": bool(
                    income_statement
                ),
                "balance_sheet": bool(
                    balance_sheet
                ),
                "cash_flow_statement": bool(
                    cash_flow
                ),
            },
            "last_updated": datetime.now(
                timezone.utc
            ).isoformat(),
        }

        self._set_cache(
            cache_key,
            result,
        )

        return result

    def resolve_symbol(
        self,
        nse_symbol: str,
        force_refresh: bool = False,
    ) -> Tuple[str, Dict[str, Any]]:
        """
        NSE symbol को FMP-supported symbol में resolve करता है.

        पहले FMP_SYMBOL_OVERRIDES check होता है.
        उसके बाद common Indian suffix candidates test होते हैं.

        Non-Indian company match को स्वीकार नहीं किया जाता.
        """

        clean_symbol = self.clean_nse_symbol(
            nse_symbol
        )

        cache_key = f"resolved-symbol:{clean_symbol}"

        if not force_refresh:
            cached = self._get_cache(cache_key)

            if isinstance(cached, dict):
                return (
                    str(cached["symbol"]),
                    dict(cached["profile"]),
                )

        candidates: List[str] = []

        override = self.symbol_overrides.get(
            clean_symbol
        )

        if override:
            candidates.append(override)

        candidates.extend(
            [
                f"{clean_symbol}.NS",
                f"{clean_symbol}.NSE",
                clean_symbol,
            ]
        )

        unique_candidates = list(
            dict.fromkeys(candidates)
        )

        tested_candidates: List[str] = []

        for candidate in unique_candidates:
            tested_candidates.append(candidate)

            profile = self.get_profile(
                candidate,
                force_refresh=force_refresh,
                raise_if_missing=False,
            )

            if not profile:
                continue

            if not self._profile_matches_india(
                profile
            ):
                logger.warning(
                    "Rejected non-Indian FMP symbol candidate "
                    "%s for NSE symbol %s.",
                    candidate,
                    clean_symbol,
                )
                continue

            returned_symbol = self._first_text(
                profile,
                ["symbol"],
            )

            resolved_symbol = (
                returned_symbol.upper()
                if returned_symbol
                else candidate.upper()
            )

            resolved = {
                "symbol": resolved_symbol,
                "profile": profile,
            }

            self._set_cache(
                cache_key,
                resolved,
            )

            return resolved_symbol, profile

        tested_text = ", ".join(
            tested_candidates
        )

        raise FundamentalServiceError(
            f"FMP fundamental symbol could not be resolved "
            f"for NSE stock '{clean_symbol}'. "
            f"Tested: {tested_text}. "
            f"Add an exact mapping in FMP_SYMBOL_OVERRIDES "
            f"when FMP uses a different symbol."
        )

    # =========================================================
    # FMP ENDPOINT METHODS
    # =========================================================

    def get_profile(
        self,
        symbol: str,
        force_refresh: bool = False,
        raise_if_missing: bool = True,
    ) -> Dict[str, Any]:
        rows = self._get_endpoint_rows(
            endpoint=self.PROFILE_ENDPOINT,
            symbol=symbol,
            cache_namespace="profile",
            force_refresh=force_refresh,
            raise_if_empty=raise_if_missing,
        )

        return self._first_row(rows)

    def get_ratios_ttm(
        self,
        symbol: str,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        rows = self._get_endpoint_rows(
            endpoint=self.RATIOS_TTM_ENDPOINT,
            symbol=symbol,
            cache_namespace="ratios-ttm",
            force_refresh=force_refresh,
            raise_if_empty=False,
        )

        return self._first_row(rows)

    def get_key_metrics_ttm(
        self,
        symbol: str,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        rows = self._get_endpoint_rows(
            endpoint=self.KEY_METRICS_TTM_ENDPOINT,
            symbol=symbol,
            cache_namespace="key-metrics-ttm",
            force_refresh=force_refresh,
            raise_if_empty=False,
        )

        return self._first_row(rows)

    def get_income_statement_growth(
        self,
        symbol: str,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        rows = self._get_endpoint_rows(
            endpoint=self.INCOME_GROWTH_ENDPOINT,
            symbol=symbol,
            cache_namespace="income-growth",
            force_refresh=force_refresh,
            extra_params={
                "period": "annual",
                "limit": 5,
            },
            raise_if_empty=False,
        )

        return self._first_row(rows)

    def get_income_statement(
        self,
        symbol: str,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        rows = self._get_endpoint_rows(
            endpoint=self.INCOME_STATEMENT_ENDPOINT,
            symbol=symbol,
            cache_namespace="income-statement",
            force_refresh=force_refresh,
            extra_params={
                "period": "annual",
                "limit": 2,
            },
            raise_if_empty=False,
        )

        return self._first_row(rows)

    def get_balance_sheet(
        self,
        symbol: str,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        rows = self._get_endpoint_rows(
            endpoint=self.BALANCE_SHEET_ENDPOINT,
            symbol=symbol,
            cache_namespace="balance-sheet",
            force_refresh=force_refresh,
            extra_params={
                "period": "annual",
                "limit": 1,
            },
            raise_if_empty=False,
        )

        return self._first_row(rows)

    def get_cash_flow_statement(
        self,
        symbol: str,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        rows = self._get_endpoint_rows(
            endpoint=self.CASH_FLOW_ENDPOINT,
            symbol=symbol,
            cache_namespace="cash-flow",
            force_refresh=force_refresh,
            extra_params={
                "period": "annual",
                "limit": 1,
            },
            raise_if_empty=False,
        )

        return self._first_row(rows)

    # =========================================================
    # HTTP REQUEST HANDLING
    # =========================================================

    def _get_endpoint_rows(
        self,
        endpoint: str,
        symbol: str,
        cache_namespace: str,
        force_refresh: bool,
        extra_params: Optional[
            Dict[str, Any]
        ] = None,
        raise_if_empty: bool = False,
    ) -> List[Dict[str, Any]]:
        clean_endpoint = endpoint.strip("/")
        clean_symbol = str(symbol or "").strip().upper()

        if not clean_symbol:
            raise FundamentalServiceError(
                f"Symbol is required for {clean_endpoint}."
            )

        cache_key = (
            f"fmp:{cache_namespace}:{clean_symbol}"
        )

        if not force_refresh:
            cached = self._get_cache(cache_key)

            if isinstance(cached, list):
                return cached

        params: Dict[str, Any] = {
            "symbol": clean_symbol,
            "apikey": self.api_key,
        }

        if extra_params:
            params.update(extra_params)

        payload = self._request_json(
            endpoint=clean_endpoint,
            params=params,
        )

        rows = self._normalize_rows(payload)

        if raise_if_empty and not rows:
            raise FundamentalServiceError(
                f"FMP returned no {clean_endpoint} data "
                f"for symbol {clean_symbol}."
            )

        self._set_cache(
            cache_key,
            rows,
        )

        return rows

    def _request_json(
        self,
        endpoint: str,
        params: Dict[str, Any],
    ) -> Any:
        url = f"{self.base_url}/{endpoint}"

        last_error: Optional[Exception] = None

        for attempt in range(
            1,
            self.settings.maximum_retries + 1,
        ):
            try:
                response = self.session.get(
                    url,
                    params=params,
                    timeout=(
                        self.settings
                        .request_timeout_seconds
                    ),
                )

                if response.status_code == 200:
                    try:
                        payload = response.json()
                    except ValueError as exc:
                        raise FundamentalServiceError(
                            f"FMP {endpoint} returned "
                            f"invalid JSON."
                        ) from exc

                    self._raise_for_api_message(
                        payload=payload,
                        endpoint=endpoint,
                    )

                    return payload

                if response.status_code in {
                    401,
                    403,
                }:
                    raise FundamentalServiceError(
                        f"FMP authentication failed for "
                        f"{endpoint}. Verify FMP_API_KEY "
                        f"and subscription access."
                    )

                if response.status_code == 404:
                    return []

                if response.status_code == 429:
                    retry_after = self._parse_retry_after(
                        response.headers.get(
                            "Retry-After"
                        )
                    )

                    delay = (
                        retry_after
                        if retry_after is not None
                        else self._retry_delay(attempt)
                    )

                    if (
                        attempt
                        >= self.settings.maximum_retries
                    ):
                        raise FundamentalServiceError(
                            "FMP request limit was reached "
                            f"while calling {endpoint}."
                        )

                    time.sleep(delay)
                    continue

                if 500 <= response.status_code <= 599:
                    if (
                        attempt
                        >= self.settings.maximum_retries
                    ):
                        raise FundamentalServiceError(
                            f"FMP server error "
                            f"{response.status_code} "
                            f"while calling {endpoint}."
                        )

                    time.sleep(
                        self._retry_delay(attempt)
                    )
                    continue

                response_text = (
                    response.text[:300]
                    if response.text
                    else "No response body"
                )

                raise FundamentalServiceError(
                    f"FMP request failed for {endpoint}: "
                    f"HTTP {response.status_code}. "
                    f"{response_text}"
                )

            except FundamentalServiceError:
                raise

            except (
                requests.Timeout,
                requests.ConnectionError,
            ) as exc:
                last_error = exc

                if (
                    attempt
                    >= self.settings.maximum_retries
                ):
                    break

                time.sleep(
                    self._retry_delay(attempt)
                )

            except requests.RequestException as exc:
                raise FundamentalServiceError(
                    f"FMP network request failed "
                    f"for {endpoint}: {exc}"
                ) from exc

        raise FundamentalServiceError(
            f"FMP request failed for {endpoint} "
            f"after "
            f"{self.settings.maximum_retries} attempts: "
            f"{last_error}"
        )

    @staticmethod
    def _raise_for_api_message(
        payload: Any,
        endpoint: str,
    ) -> None:
        if not isinstance(payload, dict):
            return

        error_text = (
            payload.get("Error Message")
            or payload.get("error")
            or payload.get("message")
        )

        if not error_text:
            return

        lowered = str(error_text).lower()

        error_indicators = (
            "invalid api key",
            "apikey",
            "subscription",
            "limit reached",
            "too many requests",
            "not available under your current",
            "upgrade your plan",
        )

        if any(
            indicator in lowered
            for indicator in error_indicators
        ):
            raise FundamentalServiceError(
                f"FMP {endpoint} error: {error_text}"
            )

    def _retry_delay(
        self,
        attempt: int,
    ) -> float:
        return (
            self.settings
            .retry_base_delay_seconds
            * (2 ** (attempt - 1))
        )

    @staticmethod
    def _parse_retry_after(
        value: Optional[str],
    ) -> Optional[float]:
        if value is None:
            return None

        try:
            parsed = float(value)

            if parsed < 0:
                return None

            return parsed

        except (TypeError, ValueError):
            return None

    # =========================================================
    # METRIC EXTRACTION
    # =========================================================

    def extract_metrics(
        self,
        ratios: Dict[str, Any],
        key_metrics: Dict[str, Any],
        growth: Dict[str, Any],
        income_statement: Dict[str, Any],
        balance_sheet: Dict[str, Any],
        cash_flow: Dict[str, Any],
    ) -> Dict[str, Optional[float]]:
        """
        FMP fields को scanner के standard metrics में बदलता है.

        Missing field None रहता है.
        """

        roe = self._first_number(
            [ratios, key_metrics],
            [
                "returnOnEquityTTM",
                "returnOnEquity",
                "roeTTM",
                "roe",
            ],
        )

        roic = self._first_number(
            [key_metrics, ratios],
            [
                "returnOnInvestedCapitalTTM",
                "returnOnInvestedCapital",
                "roicTTM",
                "roic",
            ],
        )

        roa = self._first_number(
            [ratios, key_metrics],
            [
                "returnOnAssetsTTM",
                "returnOnAssets",
                "roaTTM",
                "roa",
            ],
        )

        debt_to_equity = self._first_number(
            [ratios, key_metrics],
            [
                "debtEquityRatioTTM",
                "debtEquityRatio",
                "debtToEquityTTM",
                "debtToEquity",
            ],
        )

        current_ratio = self._first_number(
            [ratios, key_metrics],
            [
                "currentRatioTTM",
                "currentRatio",
            ],
        )

        quick_ratio = self._first_number(
            [ratios],
            [
                "quickRatioTTM",
                "quickRatio",
            ],
        )

        pe_ratio = self._first_number(
            [ratios, key_metrics],
            [
                "priceToEarningsRatioTTM",
                "priceEarningsRatioTTM",
                "peRatioTTM",
                "peRatio",
            ],
        )

        price_to_book = self._first_number(
            [ratios, key_metrics],
            [
                "priceToBookRatioTTM",
                "priceBookValueRatioTTM",
                "pbRatioTTM",
                "priceToBookRatio",
            ],
        )

        net_profit_margin = self._first_number(
            [ratios, key_metrics],
            [
                "netProfitMarginTTM",
                "netProfitMargin",
            ],
        )

        operating_margin = self._first_number(
            [ratios, key_metrics],
            [
                "operatingProfitMarginTTM",
                "operatingProfitMargin",
                "operatingMarginTTM",
            ],
        )

        revenue_growth = self._first_number(
            [growth],
            [
                "growthRevenue",
                "revenueGrowth",
                "growthRevenuePercentage",
            ],
        )

        eps_growth = self._first_number(
            [growth],
            [
                "growthEPS",
                "epsGrowth",
                "growthEps",
            ],
        )

        net_income_growth = self._first_number(
            [growth],
            [
                "growthNetIncome",
                "netIncomeGrowth",
            ],
        )

        operating_income_growth = self._first_number(
            [growth],
            [
                "growthOperatingIncome",
                "operatingIncomeGrowth",
            ],
        )

        revenue = self._first_number(
            [income_statement],
            ["revenue"],
        )

        net_income = self._first_number(
            [income_statement],
            ["netIncome"],
        )

        eps = self._first_number(
            [income_statement],
            [
                "eps",
                "epsdiluted",
                "epsDiluted",
            ],
        )

        total_debt = self._first_number(
            [balance_sheet],
            [
                "totalDebt",
                "shortTermDebt",
            ],
        )

        cash_and_equivalents = self._first_number(
            [balance_sheet],
            [
                "cashAndCashEquivalents",
                "cashAndShortTermInvestments",
            ],
        )

        operating_cash_flow = self._first_number(
            [cash_flow],
            [
                "operatingCashFlow",
                "netCashProvidedByOperatingActivities",
            ],
        )

        free_cash_flow = self._first_number(
            [cash_flow, key_metrics],
            [
                "freeCashFlow",
                "freeCashFlowTTM",
            ],
        )

        return {
            "roe_percent": self._ratio_to_percent(
                roe
            ),
            "roic_percent": self._ratio_to_percent(
                roic
            ),
            "roa_percent": self._ratio_to_percent(
                roa
            ),
            "debt_to_equity": self._normalize_ratio(
                debt_to_equity
            ),
            "current_ratio": self._normalize_ratio(
                current_ratio
            ),
            "quick_ratio": self._normalize_ratio(
                quick_ratio
            ),
            "pe_ratio": self._normalize_ratio(
                pe_ratio
            ),
            "price_to_book": self._normalize_ratio(
                price_to_book
            ),
            "net_profit_margin_percent": (
                self._ratio_to_percent(
                    net_profit_margin
                )
            ),
            "operating_margin_percent": (
                self._ratio_to_percent(
                    operating_margin
                )
            ),
            "revenue_growth_percent": (
                self._ratio_to_percent(
                    revenue_growth
                )
            ),
            "eps_growth_percent": (
                self._ratio_to_percent(
                    eps_growth
                )
            ),
            "net_income_growth_percent": (
                self._ratio_to_percent(
                    net_income_growth
                )
            ),
            "operating_income_growth_percent": (
                self._ratio_to_percent(
                    operating_income_growth
                )
            ),
            "revenue": self._clean_number(
                revenue
            ),
            "net_income": self._clean_number(
                net_income
            ),
            "eps": self._clean_number(eps),
            "total_debt": self._clean_number(
                total_debt
            ),
            "cash_and_equivalents": (
                self._clean_number(
                    cash_and_equivalents
                )
            ),
            "operating_cash_flow": (
                self._clean_number(
                    operating_cash_flow
                )
            ),
            "free_cash_flow": (
                self._clean_number(
                    free_cash_flow
                )
            ),
        }

    # =========================================================
    # FUNDAMENTAL SCORE
    # =========================================================

    def calculate_fundamental_score(
        self,
        metrics: Dict[str, Optional[float]],
    ) -> Dict[str, Any]:
        """
        Available real metrics के आधार पर maximum 30 marks.

        Missing metric:
        - score में zero मानकर silently शामिल नहीं होती
        - available_score घटता है
        - missing_conditions में दिखाई देती है
        """

        score = 0
        available_score = 0

        positive_conditions: List[str] = []
        negative_conditions: List[str] = []
        missing_conditions: List[str] = []

        def evaluate_higher_is_better(
            metric_key: str,
            maximum_points: int,
            minimum_value: float,
            strong_value: float,
            label: str,
        ) -> None:
            nonlocal score, available_score

            value = metrics.get(metric_key)

            if value is None:
                missing_conditions.append(
                    f"{label} data is unavailable."
                )
                return

            available_score += maximum_points

            if value >= strong_value:
                score += maximum_points

                positive_conditions.append(
                    f"{label} is strong at "
                    f"{self._format_percent(value)}."
                )

            elif value >= minimum_value:
                partial_points = max(
                    1,
                    math.ceil(maximum_points * 0.6),
                )

                score += partial_points

                positive_conditions.append(
                    f"{label} is acceptable at "
                    f"{self._format_percent(value)}."
                )

            else:
                negative_conditions.append(
                    f"{label} is weak at "
                    f"{self._format_percent(value)}."
                )

        def evaluate_lower_is_better(
            metric_key: str,
            maximum_points: int,
            acceptable_maximum: float,
            strong_maximum: float,
            label: str,
        ) -> None:
            nonlocal score, available_score

            value = metrics.get(metric_key)

            if value is None:
                missing_conditions.append(
                    f"{label} data is unavailable."
                )
                return

            available_score += maximum_points

            if value <= strong_maximum:
                score += maximum_points

                positive_conditions.append(
                    f"{label} is strong at "
                    f"{self._format_number(value)}."
                )

            elif value <= acceptable_maximum:
                partial_points = max(
                    1,
                    math.ceil(maximum_points * 0.6),
                )

                score += partial_points

                positive_conditions.append(
                    f"{label} is acceptable at "
                    f"{self._format_number(value)}."
                )

            else:
                negative_conditions.append(
                    f"{label} is high at "
                    f"{self._format_number(value)}."
                )

        evaluate_higher_is_better(
            metric_key="roe_percent",
            maximum_points=5,
            minimum_value=(
                self.settings.minimum_roe_percent
            ),
            strong_value=(
                self.settings.strong_roe_percent
            ),
            label="ROE",
        )

        evaluate_higher_is_better(
            metric_key="roic_percent",
            maximum_points=4,
            minimum_value=(
                self.settings.minimum_roic_percent
            ),
            strong_value=(
                self.settings.strong_roic_percent
            ),
            label="ROIC",
        )

        evaluate_lower_is_better(
            metric_key="debt_to_equity",
            maximum_points=4,
            acceptable_maximum=(
                self.settings.maximum_debt_to_equity
            ),
            strong_maximum=(
                self.settings.strong_debt_to_equity
            ),
            label="Debt-to-equity",
        )

        evaluate_higher_is_better(
            metric_key="revenue_growth_percent",
            maximum_points=4,
            minimum_value=(
                self.settings
                .minimum_revenue_growth_percent
            ),
            strong_value=(
                self.settings
                .strong_revenue_growth_percent
            ),
            label="Revenue growth",
        )

        evaluate_higher_is_better(
            metric_key="eps_growth_percent",
            maximum_points=4,
            minimum_value=(
                self.settings
                .minimum_eps_growth_percent
            ),
            strong_value=(
                self.settings
                .strong_eps_growth_percent
            ),
            label="EPS growth",
        )

        evaluate_higher_is_better(
            metric_key="net_income_growth_percent",
            maximum_points=3,
            minimum_value=(
                self.settings
                .minimum_net_income_growth_percent
            ),
            strong_value=(
                self.settings
                .strong_net_income_growth_percent
            ),
            label="Net-income growth",
        )

        self._score_cash_flow(
            metrics=metrics,
            score_container={
                "score": score,
                "available_score": available_score,
            },
            positive_conditions=positive_conditions,
            negative_conditions=negative_conditions,
            missing_conditions=missing_conditions,
        )

        operating_cash_flow = metrics.get(
            "operating_cash_flow"
        )

        free_cash_flow = metrics.get(
            "free_cash_flow"
        )

        if operating_cash_flow is not None:
            available_score += 2

            if operating_cash_flow > 0:
                score += 2

                positive_conditions.append(
                    "Operating cash flow is positive."
                )
            else:
                negative_conditions.append(
                    "Operating cash flow is not positive."
                )
        else:
            missing_conditions.append(
                "Operating cash-flow data is unavailable."
            )

        if free_cash_flow is not None:
            available_score += 2

            if free_cash_flow > 0:
                score += 2

                positive_conditions.append(
                    "Free cash flow is positive."
                )
            else:
                negative_conditions.append(
                    "Free cash flow is not positive."
                )
        else:
            missing_conditions.append(
                "Free cash-flow data is unavailable."
            )

        current_ratio = metrics.get(
            "current_ratio"
        )

        if current_ratio is not None:
            available_score += 2

            if (
                current_ratio
                >= self.settings.preferred_current_ratio
            ):
                score += 2

                positive_conditions.append(
                    "Current ratio indicates strong "
                    "short-term liquidity."
                )

            elif (
                current_ratio
                >= self.settings.minimum_current_ratio
            ):
                score += 1

                positive_conditions.append(
                    "Current ratio indicates acceptable "
                    "short-term liquidity."
                )

            else:
                negative_conditions.append(
                    "Current ratio indicates weak "
                    "short-term liquidity."
                )
        else:
            missing_conditions.append(
                "Current-ratio data is unavailable."
            )

        score = max(
            0,
            min(self.MAXIMUM_SCORE, score),
        )

        available_score = max(
            0,
            min(
                self.MAXIMUM_SCORE,
                available_score,
            ),
        )

        coverage_percent = (
            available_score
            / self.MAXIMUM_SCORE
            * 100
            if self.MAXIMUM_SCORE > 0
            else 0.0
        )

        normalized_score_percent = (
            score / available_score * 100
            if available_score > 0
            else 0.0
        )

        fundamental_signal = (
            self._get_fundamental_signal(
                raw_score=score,
                available_score=available_score,
                normalized_score_percent=(
                    normalized_score_percent
                ),
                metrics=metrics,
            )
        )

        return {
            "fundamental_score": int(score),
            "available_score": int(
                available_score
            ),
            "coverage_percent": round(
                coverage_percent,
                2,
            ),
            "normalized_score_percent": round(
                normalized_score_percent,
                2,
            ),
            "fundamental_signal": (
                fundamental_signal
            ),
            "positive_conditions": (
                positive_conditions
            ),
            "negative_conditions": (
                negative_conditions
            ),
            "missing_conditions": (
                missing_conditions
            ),
        }

    @staticmethod
    def _score_cash_flow(
        metrics: Dict[str, Optional[float]],
        score_container: Dict[str, int],
        positive_conditions: List[str],
        negative_conditions: List[str],
        missing_conditions: List[str],
    ) -> None:
        """
        Compatibility helper.

        Cash-flow scoring मुख्य scoring method में किया जाता है.
        यह method structure को future extension के लिए रखता है.
        """

        del metrics
        del score_container
        del positive_conditions
        del negative_conditions
        del missing_conditions

    def _get_fundamental_signal(
        self,
        raw_score: int,
        available_score: int,
        normalized_score_percent: float,
        metrics: Dict[str, Optional[float]],
    ) -> str:
        """
        Limited data coverage पर STRONG BUY नहीं दिया जाता.
        """

        if available_score < 18:
            return "INSUFFICIENT DATA"

        debt_to_equity = metrics.get(
            "debt_to_equity"
        )

        operating_cash_flow = metrics.get(
            "operating_cash_flow"
        )

        severe_debt_risk = (
            debt_to_equity is not None
            and debt_to_equity > 2.0
        )

        negative_cash_flow = (
            operating_cash_flow is not None
            and operating_cash_flow <= 0
        )

        if severe_debt_risk:
            return "NO BUY"

        if (
            raw_score >= 24
            and normalized_score_percent >= 80
            and not negative_cash_flow
            and available_score >= 24
        ):
            return "STRONG BUY"

        if (
            raw_score >= 19
            and normalized_score_percent >= 68
        ):
            return "BUY"

        if normalized_score_percent >= 55:
            return "WATCH"

        return "NO BUY"

    # =========================================================
    # SYMBOL VALIDATION
    # =========================================================

    @staticmethod
    def clean_nse_symbol(
        symbol: str,
    ) -> str:
        cleaned = str(symbol or "").strip().upper()

        cleaned = cleaned.replace(
            "NSE:",
            "",
        )

        if cleaned.endswith("-EQ"):
            cleaned = cleaned[:-3]

        if cleaned.endswith(".NS"):
            cleaned = cleaned[:-3]

        if cleaned.endswith(".NSE"):
            cleaned = cleaned[:-4]

        return cleaned.strip()

    @classmethod
    def _profile_matches_india(
        cls,
        profile: Dict[str, Any],
    ) -> bool:
        exchange = cls._first_text(
            profile,
            [
                "exchangeShortName",
                "exchange",
                "exchangeFullName",
            ],
        ).upper()

        country = cls._first_text(
            profile,
            [
                "country",
                "countryCode",
            ],
        ).upper()

        currency = cls._first_text(
            profile,
            ["currency"],
        ).upper()

        symbol = cls._first_text(
            profile,
            ["symbol"],
        ).upper()

        exchange_indicators = (
            "NSE",
            "NATIONAL STOCK EXCHANGE",
            "INDIA",
        )

        exchange_match = any(
            indicator in exchange
            for indicator in exchange_indicators
        )

        country_match = country in {
            "IN",
            "IND",
            "INDIA",
        }

        currency_match = currency == "INR"

        symbol_match = (
            symbol.endswith(".NS")
            or symbol.endswith(".NSE")
        )

        return any(
            [
                exchange_match,
                country_match,
                currency_match,
                symbol_match,
            ]
        )

    # =========================================================
    # CACHE
    # =========================================================

    def _get_cache(
        self,
        key: str,
    ) -> Optional[Any]:
        now = datetime.now(timezone.utc)

        with self._cache_lock:
            entry = self._cache.get(key)

            if entry is None:
                return None

            if entry.expires_at <= now:
                self._cache.pop(
                    key,
                    None,
                )

                return None

            return entry.value

    def _set_cache(
        self,
        key: str,
        value: Any,
    ) -> None:
        expires_at = (
            datetime.now(timezone.utc)
            + timedelta(
                seconds=self.settings.cache_seconds
            )
        )

        with self._cache_lock:
            self._cache[key] = CacheEntry(
                expires_at=expires_at,
                value=value,
            )

    def clear_cache(
        self,
        symbol: Optional[str] = None,
    ) -> None:
        with self._cache_lock:
            if symbol is None:
                self._cache.clear()
                return

            cleaned = self.clean_nse_symbol(
                symbol
            )

            matching_keys = [
                key
                for key in self._cache
                if cleaned in key.upper()
            ]

            for key in matching_keys:
                self._cache.pop(
                    key,
                    None,
                )

    # =========================================================
    # DATA HELPERS
    # =========================================================

    @staticmethod
    def _normalize_rows(
        payload: Any,
    ) -> List[Dict[str, Any]]:
        if isinstance(payload, list):
            return [
                row
                for row in payload
                if isinstance(row, dict)
            ]

        if not isinstance(payload, dict):
            return []

        for key in (
            "data",
            "results",
            "items",
        ):
            value = payload.get(key)

            if isinstance(value, list):
                return [
                    row
                    for row in value
                    if isinstance(row, dict)
                ]

            if isinstance(value, dict):
                return [value]

        error_keys = {
            "Error Message",
            "error",
            "message",
        }

        if error_keys.intersection(
            payload.keys()
        ):
            return []

        return [payload] if payload else []

    @staticmethod
    def _first_row(
        rows: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not rows:
            return {}

        first = rows[0]

        return dict(first)

    @classmethod
    def _first_number(
        cls,
        sources: Sequence[Dict[str, Any]],
        field_names: Sequence[str],
    ) -> Optional[float]:
        for source in sources:
            if not isinstance(source, dict):
                continue

            for field_name in field_names:
                if field_name not in source:
                    continue

                value = cls._clean_number(
                    source.get(field_name)
                )

                if value is not None:
                    return value

        return None

    @staticmethod
    def _first_text(
        source: Dict[str, Any],
        field_names: Sequence[str],
    ) -> str:
        if not isinstance(source, dict):
            return ""

        for field_name in field_names:
            value = source.get(field_name)

            if value is None:
                continue

            text = str(value).strip()

            if text:
                return text

        return ""

    @staticmethod
    def _clean_number(
        value: Any,
    ) -> Optional[float]:
        if value in {
            None,
            "",
            "None",
            "null",
            "N/A",
            "NA",
            "-",
        }:
            return None

        try:
            number = float(value)
        except (TypeError, ValueError):
            return None

        if math.isnan(number) or math.isinf(number):
            return None

        return number

    @classmethod
    def _normalize_ratio(
        cls,
        value: Any,
    ) -> Optional[float]:
        number = cls._clean_number(value)

        if number is None:
            return None

        return round(number, 4)

    @classmethod
    def _ratio_to_percent(
        cls,
        value: Any,
    ) -> Optional[float]:
        """
        FMP ratio कभी decimal और कभी percentage-style value दे सकता है.

        -0.25 से 0.25 जैसे ratio को percentage में बदलता है.
        बड़ी values को पहले से percentage मानता है.
        """

        number = cls._clean_number(value)

        if number is None:
            return None

        if -1.0 <= number <= 1.0:
            number *= 100.0

        return round(number, 2)

    @staticmethod
    def _format_percent(
        value: float,
    ) -> str:
        return f"{value:.2f}%"

    @staticmethod
    def _format_number(
        value: float,
    ) -> str:
        return f"{value:.2f}"

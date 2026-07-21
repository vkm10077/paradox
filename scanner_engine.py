from __future__ import annotations

import copy
import importlib
import logging
import math
import threading
import time
from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed,
)
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd

from config import get_timeframe_config, load_app_config
from fundamental_service import (
    FundamentalService,
    FundamentalServiceError,
)
from fyers_service import (
    FyersService,
    FyersServiceError,
)
from technical_scanner import (
    TechnicalScanner,
    TechnicalScannerError,
)


logger = logging.getLogger(__name__)


class ScannerEngineError(RuntimeError):
    """
    Nifty 500 scanner orchestration में आने वाली application-level error.
    """


@dataclass(frozen=True)
class ScannerSettings:
    """
    Final scanner rules.
    """

    benchmark_symbol: str = "NSE:NIFTY500-INDEX"

    technical_buy_score: int = 65
    technical_strong_buy_score: int = 80

    minimum_fundamental_available_score: int = 18
    minimum_fundamental_normalized_percent: float = 68.0

    final_buy_score: float = 68.0
    final_strong_buy_score: float = 82.0

    technical_weight: float = 0.70
    fundamental_weight: float = 0.30

    maximum_technical_candidates: int = 100
    maximum_final_results: int = 50

    quote_batch_delay_seconds: float = 0.20
    historical_request_delay_seconds: float = 0.15

    technical_workers: int = 4
    fundamental_workers: int = 2

    scanner_cache_seconds: int = 300


@dataclass
class ScannerCacheEntry:
    expires_at: datetime
    value: Dict[str, Any]


class ScannerEngine:
    """
    Complete live Nifty 500 scanner.

    Workflow:

    1. nifty500.py से वास्तविक stock universe पढ़ता है।
    2. FYERS से benchmark historical candles लेता है।
    3. FYERS से हर stock की real historical candles लेता है।
    4. TechnicalScanner से technical analysis करता है।
    5. केवल technical BUY/WATCH candidates को shortlist करता है।
    6. Shortlisted stocks पर FMP fundamentals चलाता है।
    7. Technical + Fundamental score combine करता है।
    8. केवल BUY और STRONG BUY stocks return करता है।
    9. कोई dummy price, fake signal या fallback stock नहीं बनाता।
    """

    ALLOWED_FINAL_SIGNALS = {
        "BUY",
        "STRONG BUY",
    }

    ALLOWED_TECHNICAL_CANDIDATE_SIGNALS = {
        "BUY",
        "STRONG BUY",
    }

    TIMEFRAME_ALIASES = {
        "swing": "swing",
        "quarterly": "quarterly",
        "quarter": "quarterly",
        "half_yearly": "half_yearly",
        "half-yearly": "half_yearly",
        "halfyearly": "half_yearly",
        "yearly": "yearly",
        "annual": "yearly",
        "five_year": "five_year",
        "5_year": "five_year",
        "5-year": "five_year",
        "5year": "five_year",
        "ten_year": "ten_year",
        "10_year": "ten_year",
        "10-year": "ten_year",
        "10year": "ten_year",
    }

    def __init__(
        self,
        access_token: str,
        fyers_service: Optional[FyersService] = None,
        technical_scanner: Optional[TechnicalScanner] = None,
        fundamental_service: Optional[FundamentalService] = None,
        settings: Optional[ScannerSettings] = None,
    ) -> None:
        cleaned_access_token = str(
            access_token or ""
        ).strip()

        if not cleaned_access_token:
            raise ScannerEngineError(
                "FYERS access token is required to run the live scanner."
            )

        app_config = load_app_config()

        self.settings = settings or ScannerSettings(
            technical_workers=max(
                1,
                app_config.max_workers,
            ),
            scanner_cache_seconds=max(
                60,
                app_config.cache_seconds,
            ),
            historical_request_delay_seconds=max(
                0.0,
                app_config.scan_delay_seconds,
            ),
        )

        self.fyers_service = (
            fyers_service
            or FyersService(
                access_token=cleaned_access_token
            )
        )

        self.technical_scanner = (
            technical_scanner
            or TechnicalScanner()
        )

        self.fundamental_service = (
            fundamental_service
            or FundamentalService()
        )

        self.timeframe_config = get_timeframe_config()

        self._scan_cache: Dict[
            str,
            ScannerCacheEntry
        ] = {}

        self._detail_cache: Dict[
            str,
            ScannerCacheEntry
        ] = {}

        self._cache_lock = threading.RLock()
        self._scan_lock = threading.Lock()

    # =========================================================
    # PUBLIC SCANNER METHODS
    # =========================================================

    def run_scan(
        self,
        timeframe: str = "swing",
        force_refresh: bool = False,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Complete Nifty 500 live scan चलाता है।

        केवल final BUY और STRONG BUY stocks results में आते हैं।
        """

        normalized_timeframe = self.normalize_timeframe(
            timeframe
        )

        final_limit = self._normalize_limit(limit)

        cache_key = (
            f"scan:{normalized_timeframe}:{final_limit}"
        )

        if not force_refresh:
            cached = self._get_scan_cache(
                cache_key
            )

            if cached is not None:
                return cached

        acquired = self._scan_lock.acquire(
            blocking=False
        )

        if not acquired:
            existing = self._get_latest_cached_scan(
                normalized_timeframe
            )

            if existing is not None:
                existing_copy = copy.deepcopy(
                    existing
                )

                existing_copy["scan_status"] = (
                    "Previous completed scan returned "
                    "while another scan is running."
                )

                return existing_copy

            raise ScannerEngineError(
                "A live Nifty 500 scan is already running. "
                "Please wait for it to finish."
            )

        started_at = datetime.now(
            timezone.utc
        )

        try:
            symbols = self.load_nifty500_symbols()

            if not symbols:
                raise ScannerEngineError(
                    "No valid stock symbols were found in nifty500.py."
                )

            benchmark_dataframe = (
                self.load_benchmark_history(
                    timeframe=normalized_timeframe
                )
            )

            technical_result = (
                self.scan_technical_candidates(
                    symbols=symbols,
                    benchmark_dataframe=benchmark_dataframe,
                    timeframe=normalized_timeframe,
                )
            )

            technical_candidates = technical_result[
                "candidates"
            ]

            final_candidates = (
                self.scan_fundamentals_and_finalize(
                    technical_candidates=technical_candidates,
                    timeframe=normalized_timeframe,
                )
            )

            final_candidates.sort(
                key=self._final_sort_key,
                reverse=True,
            )

            final_candidates = final_candidates[
                :final_limit
            ]

            completed_at = datetime.now(
                timezone.utc
            )

            duration_seconds = (
                completed_at - started_at
            ).total_seconds()

            result = {
                "scan_status": "Completed",
                "timeframe": normalized_timeframe,
                "timeframe_label": (
                    self.timeframe_config[
                        normalized_timeframe
                    ]["label"]
                ),
                "holding_period": (
                    self.timeframe_config[
                        normalized_timeframe
                    ]["holding_period"]
                ),
                "benchmark_symbol": (
                    self.settings.benchmark_symbol
                ),
                "started_at": started_at.isoformat(),
                "completed_at": completed_at.isoformat(),
                "duration_seconds": round(
                    duration_seconds,
                    2,
                ),
                "market_open": (
                    self.fyers_service
                    .is_regular_market_open()
                ),
                "total_universe": len(symbols),
                "technical_success_count": (
                    technical_result[
                        "success_count"
                    ]
                ),
                "technical_failure_count": (
                    technical_result[
                        "failure_count"
                    ]
                ),
                "technical_candidate_count": len(
                    technical_candidates
                ),
                "final_result_count": len(
                    final_candidates
                ),
                "results": final_candidates,
                "technical_errors": (
                    technical_result["errors"]
                ),
            }

            self._set_scan_cache(
                cache_key,
                result,
            )

            return copy.deepcopy(result)

        finally:
            self._scan_lock.release()

    def get_stock_details(
        self,
        symbol: str,
        timeframe: str = "swing",
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """
        किसी भी stock का complete live detail analysis return करता है।

        Stock final BUY न हो तब भी detail page पर कारण दिखाई देंगे।
        """

        normalized_symbol = (
            self.fyers_service.clean_display_symbol(
                symbol
            )
        )

        if not normalized_symbol:
            raise ScannerEngineError(
                "Stock symbol is required."
            )

        normalized_timeframe = self.normalize_timeframe(
            timeframe
        )

        cache_key = (
            f"detail:{normalized_symbol}:"
            f"{normalized_timeframe}"
        )

        if not force_refresh:
            cached = self._get_detail_cache(
                cache_key
            )

            if cached is not None:
                return cached

        benchmark_dataframe = (
            self.load_benchmark_history(
                timeframe=normalized_timeframe
            )
        )

        technical_result = self.analyze_single_technical(
            symbol=normalized_symbol,
            benchmark_dataframe=benchmark_dataframe,
            timeframe=normalized_timeframe,
        )

        fundamental_result: Optional[
            Dict[str, Any]
        ] = None

        fundamental_error: Optional[str] = None

        try:
            fundamental_result = (
                self.fundamental_service.analyze(
                    symbol=normalized_symbol,
                    force_refresh=force_refresh,
                )
            )

        except FundamentalServiceError as exc:
            fundamental_error = str(exc)

        final_result = self.build_final_result(
            technical_result=technical_result,
            fundamental_result=fundamental_result,
            timeframe=normalized_timeframe,
            require_final_buy=False,
        )

        final_result["fundamental_error"] = (
            fundamental_error
        )

        final_result["detail_generated_at"] = (
            datetime.now(
                timezone.utc
            ).isoformat()
        )

        self._set_detail_cache(
            cache_key,
            final_result,
        )

        return copy.deepcopy(final_result)

    # =========================================================
    # NIFTY 500 UNIVERSE
    # =========================================================

    def load_nifty500_symbols(
        self,
    ) -> List[str]:
        """
        Existing nifty500.py को कई valid structures में पढ़ता है।

        Supported names:
        NIFTY500
        NIFTY_500
        NIFTY500_SYMBOLS
        NIFTY_500_SYMBOLS
        SYMBOLS
        STOCKS

        Supported values:
        list, tuple, set, dictionary
        """

        try:
            module = importlib.import_module(
                "nifty500"
            )

        except Exception as exc:
            raise ScannerEngineError(
                f"nifty500.py could not be imported: {exc}"
            ) from exc

        possible_names = (
            "NIFTY500",
            "NIFTY_500",
            "NIFTY500_SYMBOLS",
            "NIFTY_500_SYMBOLS",
            "SYMBOLS",
            "STOCKS",
        )

        raw_values: Optional[Any] = None

        for name in possible_names:
            if hasattr(module, name):
                raw_values = getattr(
                    module,
                    name,
                )

                if raw_values:
                    break

        if raw_values is None:
            raise ScannerEngineError(
                "nifty500.py must contain one of these variables: "
                "NIFTY500, NIFTY_500, NIFTY500_SYMBOLS, "
                "NIFTY_500_SYMBOLS, SYMBOLS or STOCKS."
            )

        if isinstance(raw_values, dict):
            raw_symbols: Iterable[Any] = (
                raw_values.keys()
            )

        elif isinstance(
            raw_values,
            (list, tuple, set),
        ):
            raw_symbols = raw_values

        else:
            raise ScannerEngineError(
                "Nifty 500 symbol collection must be a "
                "list, tuple, set or dictionary."
            )

        symbols: List[str] = []
        seen = set()

        for raw_symbol in raw_symbols:
            symbol = self._extract_symbol(
                raw_symbol
            )

            if not symbol:
                continue

            try:
                normalized = (
                    self.fyers_service
                    .normalize_symbol(symbol)
                )

            except FyersServiceError:
                logger.warning(
                    "Invalid symbol skipped from nifty500.py: %s",
                    raw_symbol,
                )
                continue

            if normalized in seen:
                continue

            seen.add(normalized)
            symbols.append(normalized)

        if not symbols:
            raise ScannerEngineError(
                "nifty500.py did not contain any valid FYERS symbols."
            )

        return symbols

    @staticmethod
    def _extract_symbol(
        raw_value: Any,
    ) -> str:
        if isinstance(raw_value, str):
            return raw_value.strip()

        if isinstance(raw_value, dict):
            for key in (
                "symbol",
                "ticker",
                "stock",
                "code",
            ):
                value = raw_value.get(key)

                if value:
                    return str(value).strip()

        if isinstance(
            raw_value,
            (list, tuple),
        ):
            if raw_value:
                return str(
                    raw_value[0]
                ).strip()

        return ""

    # =========================================================
    # BENCHMARK
    # =========================================================

    def load_benchmark_history(
        self,
        timeframe: str,
    ) -> pd.DataFrame:
        history_days = self.get_history_days(
            timeframe
        )

        benchmark_candidates = [
            self.settings.benchmark_symbol,
            "NSE:NIFTY50-INDEX",
        ]

        errors: List[str] = []

        for benchmark_symbol in benchmark_candidates:
            try:
                return (
                    self.fyers_service
                    .get_daily_history(
                        symbol=benchmark_symbol,
                        days=history_days,
                    )
                )

            except FyersServiceError as exc:
                errors.append(
                    f"{benchmark_symbol}: {exc}"
                )

        raise ScannerEngineError(
            "Benchmark historical data could not be loaded. "
            + " | ".join(errors)
        )

    # =========================================================
    # TECHNICAL SCAN
    # =========================================================

    def scan_technical_candidates(
        self,
        symbols: Sequence[str],
        benchmark_dataframe: pd.DataFrame,
        timeframe: str,
    ) -> Dict[str, Any]:
        """
        सभी symbols पर technical scan करता है।

        FMP API call यहाँ नहीं होती।
        """

        candidates: List[Dict[str, Any]] = []
        errors: List[Dict[str, str]] = []

        success_count = 0
        failure_count = 0

        maximum_workers = min(
            self.settings.technical_workers,
            max(1, len(symbols)),
        )

        with ThreadPoolExecutor(
            max_workers=maximum_workers
        ) as executor:
            future_map = {
                executor.submit(
                    self.analyze_single_technical,
                    symbol,
                    benchmark_dataframe,
                    timeframe,
                ): symbol
                for symbol in symbols
            }

            for future in as_completed(
                future_map
            ):
                symbol = future_map[future]

                try:
                    result = future.result()
                    success_count += 1

                    technical_signal = str(
                        result.get(
                            "technical_signal",
                            "",
                        )
                    ).upper()

                    if (
                        technical_signal
                        in self.ALLOWED_TECHNICAL_CANDIDATE_SIGNALS
                    ):
                        candidates.append(
                            result
                        )

                except Exception as exc:
                    failure_count += 1

                    display_symbol = (
                        self.fyers_service
                        .clean_display_symbol(
                            symbol
                        )
                    )

                    error_message = str(exc)

                    logger.warning(
                        "Technical scan failed for %s: %s",
                        display_symbol,
                        error_message,
                    )

                    if len(errors) < 100:
                        errors.append(
                            {
                                "symbol": (
                                    display_symbol
                                ),
                                "error": (
                                    error_message
                                ),
                            }
                        )

        candidates.sort(
            key=lambda row: (
                self._safe_float(
                    row.get(
                        "technical_score"
                    )
                ),
                self._safe_float(
                    row.get(
                        "technical_probability"
                    )
                ),
            ),
            reverse=True,
        )

        candidates = candidates[
            :self.settings.maximum_technical_candidates
        ]

        return {
            "success_count": success_count,
            "failure_count": failure_count,
            "candidates": candidates,
            "errors": errors,
        }

    def analyze_single_technical(
        self,
        symbol: str,
        benchmark_dataframe: pd.DataFrame,
        timeframe: str,
    ) -> Dict[str, Any]:
        """
        एक stock का FYERS historical candles आधारित analysis।
        """

        history_days = self.get_history_days(
            timeframe
        )

        historical_dataframe = (
            self.fyers_service.get_daily_history(
                symbol=symbol,
                days=history_days,
            )
        )

        analysis = self.technical_scanner.analyze(
            dataframe=historical_dataframe,
            benchmark_dataframe=benchmark_dataframe,
            timeframe=timeframe,
        )

        fyers_symbol = (
            self.fyers_service.normalize_symbol(
                symbol
            )
        )

        display_symbol = (
            self.fyers_service.clean_display_symbol(
                fyers_symbol
            )
        )

        analysis["symbol"] = display_symbol
        analysis["fyers_symbol"] = fyers_symbol
        analysis["timeframe"] = timeframe

        if (
            self.settings
            .historical_request_delay_seconds
            > 0
        ):
            time.sleep(
                self.settings
                .historical_request_delay_seconds
            )

        return analysis

    # =========================================================
    # FUNDAMENTAL SCAN AND FINAL RESULT
    # =========================================================

    def scan_fundamentals_and_finalize(
        self,
        technical_candidates: Sequence[
            Dict[str, Any]
        ],
        timeframe: str,
    ) -> List[Dict[str, Any]]:
        """
        केवल technical candidates पर fundamentals चलाता है।
        """

        if not technical_candidates:
            return []

        final_results: List[
            Dict[str, Any]
        ] = []

        maximum_workers = min(
            self.settings.fundamental_workers,
            max(
                1,
                len(technical_candidates),
            ),
        )

        with ThreadPoolExecutor(
            max_workers=maximum_workers
        ) as executor:
            future_map = {
                executor.submit(
                    self._analyze_candidate_fundamental,
                    technical_candidate,
                    timeframe,
                ): technical_candidate
                for technical_candidate
                in technical_candidates
            }

            for future in as_completed(
                future_map
            ):
                technical_candidate = (
                    future_map[future]
                )

                symbol = str(
                    technical_candidate.get(
                        "symbol",
                        "",
                    )
                )

                try:
                    final_result = (
                        future.result()
                    )

                    if final_result is not None:
                        final_results.append(
                            final_result
                        )

                except Exception as exc:
                    logger.warning(
                        "Final analysis failed for %s: %s",
                        symbol,
                        exc,
                    )

        return final_results

    def _analyze_candidate_fundamental(
        self,
        technical_result: Dict[str, Any],
        timeframe: str,
    ) -> Optional[Dict[str, Any]]:
        symbol = str(
            technical_result.get(
                "symbol",
                "",
            )
        ).strip()

        if not symbol:
            return None

        try:
            fundamental_result = (
                self.fundamental_service.analyze(
                    symbol=symbol
                )
            )

        except FundamentalServiceError as exc:
            logger.warning(
                "Fundamental data unavailable for %s: %s",
                symbol,
                exc,
            )

            return None

        return self.build_final_result(
            technical_result=technical_result,
            fundamental_result=fundamental_result,
            timeframe=timeframe,
            require_final_buy=True,
        )

    def build_final_result(
        self,
        technical_result: Dict[str, Any],
        fundamental_result: Optional[
            Dict[str, Any]
        ],
        timeframe: str,
        require_final_buy: bool,
    ) -> Optional[Dict[str, Any]]:
        """
        Technical और fundamental analysis combine करता है।
        """

        technical_score = self._safe_float(
            technical_result.get(
                "technical_score"
            )
        )

        technical_probability = (
            self._safe_float(
                technical_result.get(
                    "technical_probability"
                )
            )
        )

        technical_signal = str(
            technical_result.get(
                "technical_signal",
                "NO BUY",
            )
        ).upper()

        fundamental_score = 0.0
        fundamental_available_score = 0.0
        fundamental_normalized_percent = 0.0
        fundamental_signal = "INSUFFICIENT DATA"

        sector = "Data unavailable"
        company_name = str(
            technical_result.get(
                "symbol",
                "",
            )
        )

        if fundamental_result:
            fundamental_score = (
                self._safe_float(
                    fundamental_result.get(
                        "fundamental_score"
                    )
                )
            )

            fundamental_available_score = (
                self._safe_float(
                    fundamental_result.get(
                        "available_score"
                    )
                )
            )

            fundamental_normalized_percent = (
                self._safe_float(
                    fundamental_result.get(
                        "normalized_score_percent"
                    )
                )
            )

            fundamental_signal = str(
                fundamental_result.get(
                    "fundamental_signal",
                    "INSUFFICIENT DATA",
                )
            ).upper()

            sector = str(
                fundamental_result.get(
                    "sector"
                )
                or "Data unavailable"
            )

            company_name = str(
                fundamental_result.get(
                    "company_name"
                )
                or company_name
            )

        has_required_fundamental_coverage = (
            fundamental_available_score
            >= self.settings
            .minimum_fundamental_available_score
        )

        fundamental_pass = (
            has_required_fundamental_coverage
            and fundamental_normalized_percent
            >= self.settings
            .minimum_fundamental_normalized_percent
            and fundamental_signal
            in {
                "BUY",
                "STRONG BUY",
            }
        )

        combined_score = (
            technical_score
            * self.settings.technical_weight
            + fundamental_normalized_percent
            * self.settings.fundamental_weight
        )

        final_signal = self.determine_final_signal(
            technical_signal=technical_signal,
            technical_score=technical_score,
            fundamental_signal=fundamental_signal,
            fundamental_pass=fundamental_pass,
            combined_score=combined_score,
        )

        probability = self.calculate_final_probability(
            technical_probability=technical_probability,
            fundamental_normalized_percent=(
                fundamental_normalized_percent
            ),
            final_signal=final_signal,
        )

        if (
            require_final_buy
            and final_signal
            not in self.ALLOWED_FINAL_SIGNALS
        ):
            return None

        trade_levels = technical_result.get(
            "trade_levels",
            {},
        )

        current_price = self._safe_float(
            technical_result.get(
                "current_price"
            )
        )

        entry_price = self._safe_float(
            trade_levels.get(
                "entry_price"
            )
        )

        stop_loss = self._safe_float(
            trade_levels.get(
                "stop_loss"
            )
        )

        target = self._safe_float(
            trade_levels.get(
                "target"
            )
        )

        positive_conditions = self._combine_text_lists(
            technical_result.get(
                "positive_conditions",
                [],
            ),
            (
                fundamental_result.get(
                    "positive_conditions",
                    [],
                )
                if fundamental_result
                else []
            ),
        )

        negative_conditions = self._combine_text_lists(
            technical_result.get(
                "negative_conditions",
                [],
            ),
            (
                fundamental_result.get(
                    "negative_conditions",
                    [],
                )
                if fundamental_result
                else []
            ),
        )

        missing_conditions = self._combine_text_lists(
            technical_result.get(
                "missing_conditions",
                [],
            ),
            (
                fundamental_result.get(
                    "missing_conditions",
                    [],
                )
                if fundamental_result
                else [
                    "Fundamental data is unavailable."
                ]
            ),
        )

        symbol = str(
            technical_result.get(
                "symbol",
                "",
            )
        )

        return {
            "sector": sector,
            "stock": symbol,
            "symbol": symbol,
            "company_name": company_name,
            "fyers_symbol": technical_result.get(
                "fyers_symbol"
            ),
            "current_price": round(
                current_price,
                2,
            ),
            "entry_price": round(
                entry_price,
                2,
            ),
            "stop_loss": round(
                stop_loss,
                2,
            ),
            "target": round(
                target,
                2,
            ),
            "holding_period": (
                self.timeframe_config[
                    timeframe
                ]["holding_period"]
            ),
            "move_up_probability": round(
                probability,
                2,
            ),
            "signal": final_signal,
            "final_score": round(
                combined_score,
                2,
            ),
            "technical_score": int(
                technical_score
            ),
            "technical_probability": round(
                technical_probability,
                2,
            ),
            "technical_signal": (
                technical_signal
            ),
            "fundamental_score": int(
                fundamental_score
            ),
            "fundamental_available_score": int(
                fundamental_available_score
            ),
            "fundamental_normalized_percent": round(
                fundamental_normalized_percent,
                2,
            ),
            "fundamental_signal": (
                fundamental_signal
            ),
            "fundamental_coverage_pass": (
                has_required_fundamental_coverage
            ),
            "risk_reward_ratio": (
                trade_levels.get(
                    "risk_reward_ratio"
                )
            ),
            "target_percent": (
                trade_levels.get(
                    "target_percent"
                )
            ),
            "risk_percent": (
                trade_levels.get(
                    "risk_percent"
                )
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
            "technical_analysis": (
                technical_result
            ),
            "fundamental_analysis": (
                fundamental_result
            ),
            "generated_at": datetime.now(
                timezone.utc
            ).isoformat(),
        }

    def determine_final_signal(
        self,
        technical_signal: str,
        technical_score: float,
        fundamental_signal: str,
        fundamental_pass: bool,
        combined_score: float,
    ) -> str:
        """
        Final BUY decision.

        Fundamental coverage या quality pass न होने पर BUY नहीं दिया जाएगा।
        """

        if technical_signal not in {
            "BUY",
            "STRONG BUY",
        }:
            return "NO BUY"

        if not fundamental_pass:
            return "NO BUY"

        if fundamental_signal not in {
            "BUY",
            "STRONG BUY",
        }:
            return "NO BUY"

        if (
            technical_score
            >= self.settings
            .technical_strong_buy_score
            and combined_score
            >= self.settings
            .final_strong_buy_score
            and fundamental_signal
            == "STRONG BUY"
        ):
            return "STRONG BUY"

        if (
            technical_score
            >= self.settings
            .technical_buy_score
            and combined_score
            >= self.settings.final_buy_score
        ):
            return "BUY"

        return "NO BUY"

    def calculate_final_probability(
        self,
        technical_probability: float,
        fundamental_normalized_percent: float,
        final_signal: str,
    ) -> float:
        """
        Model confidence calculation.

        यह guaranteed profit probability नहीं है।
        """

        probability = (
            technical_probability
            * self.settings.technical_weight
            + fundamental_normalized_percent
            * self.settings.fundamental_weight
        )

        if final_signal == "STRONG BUY":
            probability += 2.0

        elif final_signal == "NO BUY":
            probability -= 5.0

        return max(
            1.0,
            min(95.0, probability),
        )

    # =========================================================
    # TIMEFRAME
    # =========================================================

    def normalize_timeframe(
        self,
        timeframe: str,
    ) -> str:
        cleaned = str(
            timeframe or "swing"
        ).strip().lower()

        cleaned = cleaned.replace(
            " ",
            "_",
        )

        normalized = self.TIMEFRAME_ALIASES.get(
            cleaned
        )

        if (
            normalized is None
            or normalized
            not in self.timeframe_config
        ):
            valid_values = ", ".join(
                self.timeframe_config.keys()
            )

            raise ScannerEngineError(
                f"Invalid timeframe '{timeframe}'. "
                f"Valid values: {valid_values}."
            )

        return normalized

    def get_history_days(
        self,
        timeframe: str,
    ) -> int:
        normalized = self.normalize_timeframe(
            timeframe
        )

        raw_days = (
            self.timeframe_config[
                normalized
            ].get(
                "history_days",
                "420",
            )
        )

        try:
            days = int(raw_days)

        except (
            TypeError,
            ValueError,
        ) as exc:
            raise ScannerEngineError(
                f"Invalid history_days for timeframe "
                f"{normalized}."
            ) from exc

        minimum_days = {
            "swing": 420,
            "quarterly": 730,
            "half_yearly": 1095,
            "yearly": 1825,
            "five_year": 3650,
            "ten_year": 3650,
        }.get(
            normalized,
            420,
        )

        return max(
            days,
            minimum_days,
        )

    # =========================================================
    # SEARCH
    # =========================================================

    def search_stock(
        self,
        search_text: str,
        timeframe: str = "swing",
    ) -> Dict[str, Any]:
        """
        Search bar से stock detail analysis।
        """

        cleaned = str(
            search_text or ""
        ).strip().upper()

        if not cleaned:
            raise ScannerEngineError(
                "Enter a stock symbol to search."
            )

        symbols = self.load_nifty500_symbols()

        matched_symbol: Optional[str] = None

        for fyers_symbol in symbols:
            display_symbol = (
                self.fyers_service
                .clean_display_symbol(
                    fyers_symbol
                )
            )

            if cleaned == display_symbol:
                matched_symbol = (
                    fyers_symbol
                )
                break

        if matched_symbol is None:
            partial_matches = []

            for fyers_symbol in symbols:
                display_symbol = (
                    self.fyers_service
                    .clean_display_symbol(
                        fyers_symbol
                    )
                )

                if cleaned in display_symbol:
                    partial_matches.append(
                        fyers_symbol
                    )

            if len(partial_matches) == 1:
                matched_symbol = (
                    partial_matches[0]
                )

            elif len(partial_matches) > 1:
                suggestions = [
                    self.fyers_service
                    .clean_display_symbol(
                        symbol
                    )
                    for symbol in partial_matches[
                        :10
                    ]
                ]

                raise ScannerEngineError(
                    "Multiple stocks matched. "
                    "Use the exact symbol: "
                    + ", ".join(suggestions)
                )

        if matched_symbol is None:
            raise ScannerEngineError(
                f"'{cleaned}' was not found in the "
                f"Nifty 500 symbol list."
            )

        return self.get_stock_details(
            symbol=matched_symbol,
            timeframe=timeframe,
        )

    # =========================================================
    # CACHE
    # =========================================================

    def _get_scan_cache(
        self,
        key: str,
    ) -> Optional[Dict[str, Any]]:
        with self._cache_lock:
            entry = self._scan_cache.get(
                key
            )

            if entry is None:
                return None

            if (
                entry.expires_at
                <= datetime.now(
                    timezone.utc
                )
            ):
                self._scan_cache.pop(
                    key,
                    None,
                )

                return None

            return copy.deepcopy(
                entry.value
            )

    def _set_scan_cache(
        self,
        key: str,
        value: Dict[str, Any],
    ) -> None:
        expires_at = (
            datetime.now(
                timezone.utc
            )
            + timedelta(
                seconds=(
                    self.settings
                    .scanner_cache_seconds
                )
            )
        )

        with self._cache_lock:
            self._scan_cache[key] = (
                ScannerCacheEntry(
                    expires_at=expires_at,
                    value=copy.deepcopy(
                        value
                    ),
                )
            )

    def _get_detail_cache(
        self,
        key: str,
    ) -> Optional[Dict[str, Any]]:
        with self._cache_lock:
            entry = self._detail_cache.get(
                key
            )

            if entry is None:
                return None

            if (
                entry.expires_at
                <= datetime.now(
                    timezone.utc
                )
            ):
                self._detail_cache.pop(
                    key,
                    None,
                )

                return None

            return copy.deepcopy(
                entry.value
            )

    def _set_detail_cache(
        self,
        key: str,
        value: Dict[str, Any],
    ) -> None:
        expires_at = (
            datetime.now(
                timezone.utc
            )
            + timedelta(
                seconds=(
                    self.settings
                    .scanner_cache_seconds
                )
            )
        )

        with self._cache_lock:
            self._detail_cache[key] = (
                ScannerCacheEntry(
                    expires_at=expires_at,
                    value=copy.deepcopy(
                        value
                    ),
                )
            )

    def _get_latest_cached_scan(
        self,
        timeframe: str,
    ) -> Optional[Dict[str, Any]]:
        now = datetime.now(
            timezone.utc
        )

        with self._cache_lock:
            valid_entries = [
                entry
                for key, entry
                in self._scan_cache.items()
                if (
                    f"scan:{timeframe}:"
                    in key
                    and entry.expires_at > now
                )
            ]

            if not valid_entries:
                return None

            latest = max(
                valid_entries,
                key=lambda entry: (
                    entry.value.get(
                        "completed_at",
                        "",
                    )
                ),
            )

            return copy.deepcopy(
                latest.value
            )

    def clear_cache(self) -> None:
        with self._cache_lock:
            self._scan_cache.clear()
            self._detail_cache.clear()

        self.fundamental_service.clear_cache()

    # =========================================================
    # HELPERS
    # =========================================================

    def _normalize_limit(
        self,
        limit: Optional[int],
    ) -> int:
        if limit is None:
            return (
                self.settings
                .maximum_final_results
            )

        try:
            parsed = int(limit)

        except (
            TypeError,
            ValueError,
        ) as exc:
            raise ScannerEngineError(
                "Result limit must be an integer."
            ) from exc

        return max(
            1,
            min(
                parsed,
                self.settings
                .maximum_final_results,
            ),
        )

    @staticmethod
    def _safe_float(
        value: Any,
        default: float = 0.0,
    ) -> float:
        try:
            number = float(value)

            if (
                math.isnan(number)
                or math.isinf(number)
            ):
                return default

            return number

        except (
            TypeError,
            ValueError,
        ):
            return default

    @staticmethod
    def _combine_text_lists(
        first: Any,
        second: Any,
    ) -> List[str]:
        combined: List[str] = []

        for collection in (
            first,
            second,
        ):
            if not isinstance(
                collection,
                (list, tuple, set),
            ):
                continue

            for item in collection:
                text = str(
                    item or ""
                ).strip()

                if (
                    text
                    and text not in combined
                ):
                    combined.append(
                        text
                    )

        return combined

    @staticmethod
    def _final_sort_key(
        row: Dict[str, Any],
    ) -> Tuple[int, float, float]:
        signal_rank = {
            "STRONG BUY": 2,
            "BUY": 1,
        }.get(
            str(
                row.get(
                    "signal",
                    "",
                )
            ).upper(),
            0,
        )

        try:
            final_score = float(
                row.get(
                    "final_score",
                    0,
                )
            )
        except (
            TypeError,
            ValueError,
        ):
            final_score = 0.0

        try:
            probability = float(
                row.get(
                    "move_up_probability",
                    0,
                )
            )
        except (
            TypeError,
            ValueError,
        ):
            probability = 0.0

        return (
            signal_rank,
            final_score,
            probability,
        )

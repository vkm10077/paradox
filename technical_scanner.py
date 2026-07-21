from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


class TechnicalScannerError(RuntimeError):
    """
    Historical market data या technical calculation में आने वाली
    application-level error.
    """


@dataclass(frozen=True)
class TechnicalSettings:
    """
    Technical indicator configuration.
    """

    ema_fast: int = 9
    ema_short: int = 20
    ema_medium: int = 50
    ema_long: int = 200

    rsi_period: int = 14

    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9

    atr_period: int = 14

    adx_period: int = 14

    supertrend_period: int = 10
    supertrend_multiplier: float = 3.0

    volume_period: int = 20

    breakout_period: int = 20

    fifty_two_week_period: int = 252

    minimum_required_candles: int = 220


class TechnicalScanner:
    """
    Live historical candles पर complete technical analysis.

    इसमें calculations शामिल हैं:

    - EMA 9, 20, 50, 200
    - RSI
    - MACD
    - ATR
    - ADX
    - Supertrend
    - Volume strength
    - Breakout
    - Relative Strength
    - 52-week position
    - Price action
    - Candlestick patterns
    - Chart patterns
    - Support and resistance
    - Entry, stop-loss and target
    - Technical score
    """

    def __init__(
        self,
        settings: Optional[TechnicalSettings] = None,
    ) -> None:
        self.settings = settings or TechnicalSettings()

    # =========================================================
    # PUBLIC ANALYSIS METHOD
    # =========================================================

    def analyze(
        self,
        dataframe: pd.DataFrame,
        benchmark_dataframe: Optional[pd.DataFrame] = None,
        timeframe: str = "swing",
    ) -> Dict[str, Any]:
        """
        Stock historical dataframe का complete technical analysis करता है.

        Required columns:
        open, high, low, close, volume

        benchmark_dataframe optional है.
        Relative-strength calculation के लिए benchmark दिया जा सकता है.
        """

        df = self.prepare_dataframe(dataframe)

        minimum_candles = self._minimum_candles_for_timeframe(
            timeframe
        )

        if len(df) < minimum_candles:
            raise TechnicalScannerError(
                f"Technical analysis requires at least "
                f"{minimum_candles} valid candles, but only "
                f"{len(df)} candles were received."
            )

        df = self.add_indicators(df)

        latest = df.iloc[-1]
        previous = df.iloc[-2]

        trend_analysis = self.analyze_trend(df)
        momentum_analysis = self.analyze_momentum(df)
        volume_analysis = self.analyze_volume(df)
        volatility_analysis = self.analyze_volatility(df)
        price_action_analysis = self.analyze_price_action(df)
        candlestick_analysis = self.detect_candlestick_patterns(df)
        chart_pattern_analysis = self.detect_chart_patterns(df)
        support_resistance = self.calculate_support_resistance(df)

        relative_strength = self.calculate_relative_strength(
            stock_dataframe=df,
            benchmark_dataframe=benchmark_dataframe,
            timeframe=timeframe,
        )

        risk_levels = self.calculate_trade_levels(
            dataframe=df,
            timeframe=timeframe,
            support_resistance=support_resistance,
        )

        score_result = self.calculate_technical_score(
            dataframe=df,
            trend_analysis=trend_analysis,
            momentum_analysis=momentum_analysis,
            volume_analysis=volume_analysis,
            volatility_analysis=volatility_analysis,
            price_action_analysis=price_action_analysis,
            candlestick_analysis=candlestick_analysis,
            chart_pattern_analysis=chart_pattern_analysis,
            relative_strength=relative_strength,
            risk_levels=risk_levels,
        )

        current_price = self.safe_float(
            latest.get("close")
        )

        price_change = current_price - self.safe_float(
            previous.get("close")
        )

        previous_close = self.safe_float(
            previous.get("close")
        )

        price_change_percent = (
            (price_change / previous_close) * 100
            if previous_close > 0
            else 0.0
        )

        return {
            "current_price": self.round_price(current_price),
            "price_change": self.round_price(price_change),
            "price_change_percent": self.round_number(
                price_change_percent,
                2,
            ),
            "latest_candle_time": self._serialize_datetime(
                latest.get("datetime")
            ),
            "technical_score": score_result["technical_score"],
            "technical_signal": score_result["technical_signal"],
            "technical_probability": score_result[
                "technical_probability"
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
            "trend": trend_analysis,
            "momentum": momentum_analysis,
            "volume": volume_analysis,
            "volatility": volatility_analysis,
            "relative_strength": relative_strength,
            "price_action": price_action_analysis,
            "candlestick_patterns": candlestick_analysis,
            "chart_patterns": chart_pattern_analysis,
            "support_resistance": support_resistance,
            "trade_levels": risk_levels,
            "indicator_values": self.get_latest_indicator_values(df),
        }

    # =========================================================
    # DATA PREPARATION
    # =========================================================

    def prepare_dataframe(
        self,
        dataframe: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        Historical candle dataframe को clean और validate करता है.
        """

        if dataframe is None:
            raise TechnicalScannerError(
                "Historical dataframe is missing."
            )

        if not isinstance(dataframe, pd.DataFrame):
            raise TechnicalScannerError(
                "Historical data must be a pandas DataFrame."
            )

        if dataframe.empty:
            raise TechnicalScannerError(
                "Historical dataframe is empty."
            )

        required_columns = {
            "open",
            "high",
            "low",
            "close",
            "volume",
        }

        missing_columns = required_columns.difference(
            dataframe.columns
        )

        if missing_columns:
            missing_text = ", ".join(
                sorted(missing_columns)
            )

            raise TechnicalScannerError(
                f"Historical dataframe is missing columns: "
                f"{missing_text}"
            )

        df = dataframe.copy()

        numeric_columns = [
            "open",
            "high",
            "low",
            "close",
            "volume",
        ]

        for column in numeric_columns:
            df[column] = pd.to_numeric(
                df[column],
                errors="coerce",
            )

        df.replace(
            [np.inf, -np.inf],
            np.nan,
            inplace=True,
        )

        df.dropna(
            subset=numeric_columns,
            inplace=True,
        )

        df = df[
            (df["open"] > 0)
            & (df["high"] > 0)
            & (df["low"] > 0)
            & (df["close"] > 0)
            & (df["volume"] >= 0)
        ]

        df = df[
            (df["high"] >= df["low"])
            & (df["high"] >= df["open"])
            & (df["high"] >= df["close"])
            & (df["low"] <= df["open"])
            & (df["low"] <= df["close"])
        ]

        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_numeric(
                df["timestamp"],
                errors="coerce",
            )

            df.sort_values(
                "timestamp",
                inplace=True,
            )

            df.drop_duplicates(
                subset=["timestamp"],
                keep="last",
                inplace=True,
            )

        elif "datetime" in df.columns:
            df["datetime"] = pd.to_datetime(
                df["datetime"],
                errors="coerce",
            )

            df.sort_values(
                "datetime",
                inplace=True,
            )

            df.drop_duplicates(
                subset=["datetime"],
                keep="last",
                inplace=True,
            )

        df.reset_index(
            drop=True,
            inplace=True,
        )

        if df.empty:
            raise TechnicalScannerError(
                "No valid historical candles remain after cleaning."
            )

        return df

    # =========================================================
    # INDICATORS
    # =========================================================

    def add_indicators(
        self,
        dataframe: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        सभी required indicators dataframe में जोड़ता है.
        """

        df = dataframe.copy()
        settings = self.settings

        df["ema_9"] = self.calculate_ema(
            df["close"],
            settings.ema_fast,
        )

        df["ema_20"] = self.calculate_ema(
            df["close"],
            settings.ema_short,
        )

        df["ema_50"] = self.calculate_ema(
            df["close"],
            settings.ema_medium,
        )

        df["ema_200"] = self.calculate_ema(
            df["close"],
            settings.ema_long,
        )

        df["rsi"] = self.calculate_rsi(
            df["close"],
            settings.rsi_period,
        )

        macd_line, macd_signal, macd_histogram = (
            self.calculate_macd(
                df["close"],
                fast_period=settings.macd_fast,
                slow_period=settings.macd_slow,
                signal_period=settings.macd_signal,
            )
        )

        df["macd"] = macd_line
        df["macd_signal"] = macd_signal
        df["macd_histogram"] = macd_histogram

        df["atr"] = self.calculate_atr(
            df,
            settings.atr_period,
        )

        plus_di, minus_di, adx = self.calculate_adx(
            df,
            settings.adx_period,
        )

        df["plus_di"] = plus_di
        df["minus_di"] = minus_di
        df["adx"] = adx

        supertrend, supertrend_direction = (
            self.calculate_supertrend(
                df,
                period=settings.supertrend_period,
                multiplier=settings.supertrend_multiplier,
            )
        )

        df["supertrend"] = supertrend
        df["supertrend_direction"] = (
            supertrend_direction
        )

        df["volume_average_20"] = (
            df["volume"]
            .rolling(
                window=settings.volume_period,
                min_periods=settings.volume_period,
            )
            .mean()
        )

        df["volume_ratio"] = (
            df["volume"]
            / df["volume_average_20"].replace(0, np.nan)
        )

        df["highest_20"] = (
            df["high"]
            .rolling(
                window=settings.breakout_period,
                min_periods=settings.breakout_period,
            )
            .max()
        )

        df["lowest_20"] = (
            df["low"]
            .rolling(
                window=settings.breakout_period,
                min_periods=settings.breakout_period,
            )
            .min()
        )

        df["highest_52_week"] = (
            df["high"]
            .rolling(
                window=settings.fifty_two_week_period,
                min_periods=min(
                    settings.fifty_two_week_period,
                    len(df),
                ),
            )
            .max()
        )

        df["lowest_52_week"] = (
            df["low"]
            .rolling(
                window=settings.fifty_two_week_period,
                min_periods=min(
                    settings.fifty_two_week_period,
                    len(df),
                ),
            )
            .min()
        )

        df["return_1_day"] = (
            df["close"].pct_change(1) * 100
        )

        df["return_5_day"] = (
            df["close"].pct_change(5) * 100
        )

        df["return_20_day"] = (
            df["close"].pct_change(20) * 100
        )

        df["return_60_day"] = (
            df["close"].pct_change(60) * 100
        )

        df["return_125_day"] = (
            df["close"].pct_change(125) * 100
        )

        df["return_252_day"] = (
            df["close"].pct_change(252) * 100
        )

        df["candle_body"] = (
            df["close"] - df["open"]
        )

        df["absolute_body"] = (
            df["candle_body"].abs()
        )

        df["candle_range"] = (
            df["high"] - df["low"]
        )

        df["upper_wick"] = (
            df["high"]
            - df[["open", "close"]].max(axis=1)
        )

        df["lower_wick"] = (
            df[["open", "close"]].min(axis=1)
            - df["low"]
        )

        df["body_percent"] = (
            df["absolute_body"]
            / df["candle_range"].replace(0, np.nan)
        ) * 100

        df.replace(
            [np.inf, -np.inf],
            np.nan,
            inplace=True,
        )

        return df

    @staticmethod
    def calculate_ema(
        series: pd.Series,
        period: int,
    ) -> pd.Series:
        return series.ewm(
            span=period,
            adjust=False,
            min_periods=period,
        ).mean()

    @staticmethod
    def calculate_rsi(
        close: pd.Series,
        period: int = 14,
    ) -> pd.Series:
        change = close.diff()

        gain = change.clip(lower=0)
        loss = -change.clip(upper=0)

        average_gain = gain.ewm(
            alpha=1 / period,
            adjust=False,
            min_periods=period,
        ).mean()

        average_loss = loss.ewm(
            alpha=1 / period,
            adjust=False,
            min_periods=period,
        ).mean()

        relative_strength = (
            average_gain
            / average_loss.replace(0, np.nan)
        )

        rsi = 100 - (
            100 / (1 + relative_strength)
        )

        rsi = rsi.where(
            average_loss != 0,
            100.0,
        )

        return rsi.clip(
            lower=0,
            upper=100,
        )

    @staticmethod
    def calculate_macd(
        close: pd.Series,
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9,
    ) -> Tuple[pd.Series, pd.Series, pd.Series]:
        fast_ema = close.ewm(
            span=fast_period,
            adjust=False,
            min_periods=fast_period,
        ).mean()

        slow_ema = close.ewm(
            span=slow_period,
            adjust=False,
            min_periods=slow_period,
        ).mean()

        macd_line = fast_ema - slow_ema

        signal_line = macd_line.ewm(
            span=signal_period,
            adjust=False,
            min_periods=signal_period,
        ).mean()

        histogram = macd_line - signal_line

        return macd_line, signal_line, histogram

    @staticmethod
    def calculate_true_range(
        dataframe: pd.DataFrame,
    ) -> pd.Series:
        previous_close = dataframe["close"].shift(1)

        high_low = (
            dataframe["high"] - dataframe["low"]
        )

        high_previous_close = (
            dataframe["high"] - previous_close
        ).abs()

        low_previous_close = (
            dataframe["low"] - previous_close
        ).abs()

        return pd.concat(
            [
                high_low,
                high_previous_close,
                low_previous_close,
            ],
            axis=1,
        ).max(axis=1)

    def calculate_atr(
        self,
        dataframe: pd.DataFrame,
        period: int = 14,
    ) -> pd.Series:
        true_range = self.calculate_true_range(
            dataframe
        )

        return true_range.ewm(
            alpha=1 / period,
            adjust=False,
            min_periods=period,
        ).mean()

    def calculate_adx(
        self,
        dataframe: pd.DataFrame,
        period: int = 14,
    ) -> Tuple[pd.Series, pd.Series, pd.Series]:
        high_difference = dataframe["high"].diff()
        low_difference = -dataframe["low"].diff()

        plus_directional_movement = pd.Series(
            np.where(
                (
                    high_difference
                    > low_difference
                )
                & (high_difference > 0),
                high_difference,
                0.0,
            ),
            index=dataframe.index,
        )

        minus_directional_movement = pd.Series(
            np.where(
                (
                    low_difference
                    > high_difference
                )
                & (low_difference > 0),
                low_difference,
                0.0,
            ),
            index=dataframe.index,
        )

        atr = self.calculate_atr(
            dataframe,
            period,
        )

        smoothed_plus_dm = (
            plus_directional_movement.ewm(
                alpha=1 / period,
                adjust=False,
                min_periods=period,
            ).mean()
        )

        smoothed_minus_dm = (
            minus_directional_movement.ewm(
                alpha=1 / period,
                adjust=False,
                min_periods=period,
            ).mean()
        )

        plus_di = (
            100
            * smoothed_plus_dm
            / atr.replace(0, np.nan)
        )

        minus_di = (
            100
            * smoothed_minus_dm
            / atr.replace(0, np.nan)
        )

        directional_sum = (
            plus_di + minus_di
        ).replace(0, np.nan)

        directional_index = (
            100
            * (plus_di - minus_di).abs()
            / directional_sum
        )

        adx = directional_index.ewm(
            alpha=1 / period,
            adjust=False,
            min_periods=period,
        ).mean()

        return plus_di, minus_di, adx

    def calculate_supertrend(
        self,
        dataframe: pd.DataFrame,
        period: int = 10,
        multiplier: float = 3.0,
    ) -> Tuple[pd.Series, pd.Series]:
        atr = self.calculate_atr(
            dataframe,
            period,
        )

        hl2 = (
            dataframe["high"] + dataframe["low"]
        ) / 2

        basic_upper_band = (
            hl2 + multiplier * atr
        )

        basic_lower_band = (
            hl2 - multiplier * atr
        )

        final_upper_band = basic_upper_band.copy()
        final_lower_band = basic_lower_band.copy()

        supertrend = pd.Series(
            np.nan,
            index=dataframe.index,
            dtype="float64",
        )

        direction = pd.Series(
            0,
            index=dataframe.index,
            dtype="int64",
        )

        for index in range(1, len(dataframe)):
            previous_index = index - 1

            if pd.isna(atr.iloc[index]):
                continue

            previous_upper = final_upper_band.iloc[
                previous_index
            ]

            previous_lower = final_lower_band.iloc[
                previous_index
            ]

            previous_close = dataframe["close"].iloc[
                previous_index
            ]

            current_basic_upper = basic_upper_band.iloc[
                index
            ]

            current_basic_lower = basic_lower_band.iloc[
                index
            ]

            if (
                pd.isna(previous_upper)
                or current_basic_upper < previous_upper
                or previous_close > previous_upper
            ):
                final_upper_band.iloc[index] = (
                    current_basic_upper
                )
            else:
                final_upper_band.iloc[index] = (
                    previous_upper
                )

            if (
                pd.isna(previous_lower)
                or current_basic_lower > previous_lower
                or previous_close < previous_lower
            ):
                final_lower_band.iloc[index] = (
                    current_basic_lower
                )
            else:
                final_lower_band.iloc[index] = (
                    previous_lower
                )

            previous_supertrend = supertrend.iloc[
                previous_index
            ]

            current_close = dataframe["close"].iloc[
                index
            ]

            if pd.isna(previous_supertrend):
                if current_close >= final_lower_band.iloc[index]:
                    supertrend.iloc[index] = (
                        final_lower_band.iloc[index]
                    )

                    direction.iloc[index] = 1

                else:
                    supertrend.iloc[index] = (
                        final_upper_band.iloc[index]
                    )

                    direction.iloc[index] = -1

                continue

            if math.isclose(
                previous_supertrend,
                previous_upper,
                rel_tol=1e-9,
                abs_tol=1e-9,
            ):
                if current_close <= final_upper_band.iloc[index]:
                    supertrend.iloc[index] = (
                        final_upper_band.iloc[index]
                    )

                    direction.iloc[index] = -1

                else:
                    supertrend.iloc[index] = (
                        final_lower_band.iloc[index]
                    )

                    direction.iloc[index] = 1

            else:
                if current_close >= final_lower_band.iloc[index]:
                    supertrend.iloc[index] = (
                        final_lower_band.iloc[index]
                    )

                    direction.iloc[index] = 1

                else:
                    supertrend.iloc[index] = (
                        final_upper_band.iloc[index]
                    )

                    direction.iloc[index] = -1

        return supertrend, direction

    # =========================================================
    # TREND ANALYSIS
    # =========================================================

    def analyze_trend(
        self,
        dataframe: pd.DataFrame,
    ) -> Dict[str, Any]:
        latest = dataframe.iloc[-1]
        previous = dataframe.iloc[-2]

        close = self.safe_float(latest["close"])
        ema_9 = self.safe_float(latest["ema_9"])
        ema_20 = self.safe_float(latest["ema_20"])
        ema_50 = self.safe_float(latest["ema_50"])
        ema_200 = self.safe_float(latest["ema_200"])

        bullish_alignment = (
            close > ema_9 > ema_20 > ema_50 > ema_200
        )

        medium_bullish_alignment = (
            close > ema_20 > ema_50
        )

        long_term_bullish = (
            close > ema_200
            and ema_50 > ema_200
        )

        ema_20_rising = (
            self.safe_float(latest["ema_20"])
            > self.safe_float(previous["ema_20"])
        )

        ema_50_rising = (
            self.safe_float(latest["ema_50"])
            > self.safe_float(previous["ema_50"])
        )

        ema_200_rising = (
            self.safe_float(latest["ema_200"])
            > self.safe_float(previous["ema_200"])
        )

        supertrend_bullish = (
            int(
                self.safe_float(
                    latest["supertrend_direction"]
                )
            )
            == 1
        )

        adx = self.safe_float(latest["adx"])
        plus_di = self.safe_float(latest["plus_di"])
        minus_di = self.safe_float(latest["minus_di"])

        directional_bullish = (
            plus_di > minus_di
        )

        if (
            bullish_alignment
            and supertrend_bullish
            and directional_bullish
            and adx >= 25
        ):
            trend_status = "Strong Bullish"

        elif (
            medium_bullish_alignment
            and supertrend_bullish
        ):
            trend_status = "Bullish"

        elif (
            close < ema_20 < ema_50
            and not supertrend_bullish
        ):
            trend_status = "Bearish"

        else:
            trend_status = "Sideways"

        return {
            "status": trend_status,
            "bullish_alignment": bullish_alignment,
            "medium_bullish_alignment": (
                medium_bullish_alignment
            ),
            "long_term_bullish": long_term_bullish,
            "ema_20_rising": ema_20_rising,
            "ema_50_rising": ema_50_rising,
            "ema_200_rising": ema_200_rising,
            "supertrend_bullish": supertrend_bullish,
            "directional_bullish": directional_bullish,
            "adx": self.round_number(adx, 2),
            "plus_di": self.round_number(
                plus_di,
                2,
            ),
            "minus_di": self.round_number(
                minus_di,
                2,
            ),
        }

    # =========================================================
    # MOMENTUM ANALYSIS
    # =========================================================

    def analyze_momentum(
        self,
        dataframe: pd.DataFrame,
    ) -> Dict[str, Any]:
        latest = dataframe.iloc[-1]
        previous = dataframe.iloc[-2]

        rsi = self.safe_float(latest["rsi"])
        macd = self.safe_float(latest["macd"])
        macd_signal = self.safe_float(
            latest["macd_signal"]
        )
        macd_histogram = self.safe_float(
            latest["macd_histogram"]
        )

        previous_histogram = self.safe_float(
            previous["macd_histogram"]
        )

        macd_bullish = (
            macd > macd_signal
            and macd_histogram > 0
        )

        macd_momentum_rising = (
            macd_histogram > previous_histogram
        )

        rsi_bullish = (
            55 <= rsi <= 75
        )

        rsi_overbought = (
            rsi > 75
        )

        return_5_day = self.safe_float(
            latest.get("return_5_day")
        )

        return_20_day = self.safe_float(
            latest.get("return_20_day")
        )

        return_60_day = self.safe_float(
            latest.get("return_60_day")
        )

        positive_momentum = (
            return_5_day > 0
            and return_20_day > 0
        )

        if (
            rsi_bullish
            and macd_bullish
            and macd_momentum_rising
            and positive_momentum
        ):
            momentum_status = "Strong Bullish"

        elif (
            rsi >= 50
            and macd > macd_signal
        ):
            momentum_status = "Bullish"

        elif (
            rsi < 45
            and macd < macd_signal
        ):
            momentum_status = "Bearish"

        else:
            momentum_status = "Neutral"

        return {
            "status": momentum_status,
            "rsi": self.round_number(rsi, 2),
            "rsi_bullish": rsi_bullish,
            "rsi_overbought": rsi_overbought,
            "macd": self.round_number(macd, 4),
            "macd_signal": self.round_number(
                macd_signal,
                4,
            ),
            "macd_histogram": self.round_number(
                macd_histogram,
                4,
            ),
            "macd_bullish": macd_bullish,
            "macd_momentum_rising": (
                macd_momentum_rising
            ),
            "return_5_day": self.round_number(
                return_5_day,
                2,
            ),
            "return_20_day": self.round_number(
                return_20_day,
                2,
            ),
            "return_60_day": self.round_number(
                return_60_day,
                2,
            ),
            "positive_momentum": positive_momentum,
        }

    # =========================================================
    # VOLUME ANALYSIS
    # =========================================================

    def analyze_volume(
        self,
        dataframe: pd.DataFrame,
    ) -> Dict[str, Any]:
        latest = dataframe.iloc[-1]

        current_volume = self.safe_float(
            latest["volume"]
        )

        average_volume = self.safe_float(
            latest["volume_average_20"]
        )

        volume_ratio = self.safe_float(
            latest["volume_ratio"]
        )

        price_up = (
            self.safe_float(latest["close"])
            > self.safe_float(latest["open"])
        )

        high_volume = (
            volume_ratio >= 1.5
        )

        strong_volume = (
            volume_ratio >= 2.0
        )

        bullish_volume = (
            price_up and volume_ratio >= 1.2
        )

        recent = dataframe.tail(20).copy()

        up_volume = recent.loc[
            recent["close"] > recent["open"],
            "volume",
        ].sum()

        down_volume = recent.loc[
            recent["close"] < recent["open"],
            "volume",
        ].sum()

        accumulation = (
            up_volume > down_volume * 1.15
        )

        if strong_volume and price_up:
            volume_status = "Strong Bullish"

        elif bullish_volume or accumulation:
            volume_status = "Bullish"

        elif volume_ratio < 0.7:
            volume_status = "Weak"

        else:
            volume_status = "Normal"

        return {
            "status": volume_status,
            "current_volume": int(current_volume),
            "average_volume_20": int(
                average_volume
            ),
            "volume_ratio": self.round_number(
                volume_ratio,
                2,
            ),
            "high_volume": high_volume,
            "strong_volume": strong_volume,
            "bullish_volume": bullish_volume,
            "accumulation": accumulation,
            "up_volume_20": int(up_volume),
            "down_volume_20": int(down_volume),
        }

    # =========================================================
    # VOLATILITY ANALYSIS
    # =========================================================

    def analyze_volatility(
        self,
        dataframe: pd.DataFrame,
    ) -> Dict[str, Any]:
        latest = dataframe.iloc[-1]

        atr = self.safe_float(latest["atr"])
        close = self.safe_float(latest["close"])

        atr_percent = (
            (atr / close) * 100
            if close > 0
            else 0.0
        )

        recent_returns = (
            dataframe["close"]
            .pct_change()
            .tail(20)
            .dropna()
        )

        annualized_volatility = (
            recent_returns.std()
            * math.sqrt(252)
            * 100
            if not recent_returns.empty
            else 0.0
        )

        if atr_percent < 1.5:
            volatility_status = "Low"

        elif atr_percent <= 4.0:
            volatility_status = "Normal"

        else:
            volatility_status = "High"

        return {
            "status": volatility_status,
            "atr": self.round_price(atr),
            "atr_percent": self.round_number(
                atr_percent,
                2,
            ),
            "annualized_volatility": (
                self.round_number(
                    annualized_volatility,
                    2,
                )
            ),
        }

    # =========================================================
    # PRICE ACTION
    # =========================================================

    def analyze_price_action(
        self,
        dataframe: pd.DataFrame,
    ) -> Dict[str, Any]:
        latest = dataframe.iloc[-1]
        previous = dataframe.iloc[-2]

        current_close = self.safe_float(
            latest["close"]
        )

        previous_20_high = self.safe_float(
            dataframe["high"]
            .shift(1)
            .rolling(20)
            .max()
            .iloc[-1]
        )

        previous_50_high = self.safe_float(
            dataframe["high"]
            .shift(1)
            .rolling(50)
            .max()
            .iloc[-1]
        )

        previous_20_low = self.safe_float(
            dataframe["low"]
            .shift(1)
            .rolling(20)
            .min()
            .iloc[-1]
        )

        breakout_20 = (
            previous_20_high > 0
            and current_close > previous_20_high
        )

        breakout_50 = (
            previous_50_high > 0
            and current_close > previous_50_high
        )

        breakdown_20 = (
            previous_20_low > 0
            and current_close < previous_20_low
        )

        higher_high = (
            self.safe_float(latest["high"])
            > self.safe_float(previous["high"])
        )

        higher_low = (
            self.safe_float(latest["low"])
            > self.safe_float(previous["low"])
        )

        strong_bullish_candle = (
            current_close
            > self.safe_float(latest["open"])
            and self.safe_float(
                latest["body_percent"]
            )
            >= 60
        )

        closes = dataframe["close"].tail(10)

        higher_close_count = int(
            (closes.diff() > 0).sum()
        )

        recent_swing_structure = (
            higher_close_count >= 6
        )

        high_52_week = self.safe_float(
            latest["highest_52_week"]
        )

        low_52_week = self.safe_float(
            latest["lowest_52_week"]
        )

        distance_from_52_week_high = (
            (
                current_close - high_52_week
            )
            / high_52_week
            * 100
            if high_52_week > 0
            else 0.0
        )

        position_in_52_week_range = (
            (
                current_close - low_52_week
            )
            / (high_52_week - low_52_week)
            * 100
            if high_52_week > low_52_week
            else 0.0
        )

        near_52_week_high = (
            distance_from_52_week_high >= -10
        )

        if breakout_50:
            price_action_status = "Major Breakout"

        elif breakout_20:
            price_action_status = "Breakout"

        elif (
            higher_high
            and higher_low
            and recent_swing_structure
        ):
            price_action_status = "Bullish Structure"

        elif breakdown_20:
            price_action_status = "Breakdown"

        else:
            price_action_status = "Consolidation"

        return {
            "status": price_action_status,
            "breakout_20": breakout_20,
            "breakout_50": breakout_50,
            "breakdown_20": breakdown_20,
            "higher_high": higher_high,
            "higher_low": higher_low,
            "strong_bullish_candle": (
                strong_bullish_candle
            ),
            "higher_close_count_10": (
                higher_close_count
            ),
            "bullish_swing_structure": (
                recent_swing_structure
            ),
            "previous_20_high": self.round_price(
                previous_20_high
            ),
            "previous_50_high": self.round_price(
                previous_50_high
            ),
            "previous_20_low": self.round_price(
                previous_20_low
            ),
            "high_52_week": self.round_price(
                high_52_week
            ),
            "low_52_week": self.round_price(
                low_52_week
            ),
            "distance_from_52_week_high": (
                self.round_number(
                    distance_from_52_week_high,
                    2,
                )
            ),
            "position_in_52_week_range": (
                self.round_number(
                    position_in_52_week_range,
                    2,
                )
            ),
            "near_52_week_high": near_52_week_high,
        }

    # =========================================================
    # CANDLESTICK PATTERNS
    # =========================================================

    def detect_candlestick_patterns(
        self,
        dataframe: pd.DataFrame,
    ) -> Dict[str, Any]:
        if len(dataframe) < 3:
            return {
                "bullish_patterns": [],
                "bearish_patterns": [],
                "primary_pattern": "None",
                "bullish_pattern_found": False,
                "bearish_pattern_found": False,
            }

        current = dataframe.iloc[-1]
        previous = dataframe.iloc[-2]
        third = dataframe.iloc[-3]

        bullish_patterns: List[str] = []
        bearish_patterns: List[str] = []

        current_open = self.safe_float(
            current["open"]
        )

        current_close = self.safe_float(
            current["close"]
        )

        current_high = self.safe_float(
            current["high"]
        )

        current_low = self.safe_float(
            current["low"]
        )

        current_body = abs(
            current_close - current_open
        )

        current_range = (
            current_high - current_low
        )

        upper_wick = (
            current_high
            - max(current_open, current_close)
        )

        lower_wick = (
            min(current_open, current_close)
            - current_low
        )

        previous_open = self.safe_float(
            previous["open"]
        )

        previous_close = self.safe_float(
            previous["close"]
        )

        previous_body = abs(
            previous_close - previous_open
        )

        third_open = self.safe_float(
            third["open"]
        )

        third_close = self.safe_float(
            third["close"]
        )

        current_bullish = (
            current_close > current_open
        )

        current_bearish = (
            current_close < current_open
        )

        previous_bullish = (
            previous_close > previous_open
        )

        previous_bearish = (
            previous_close < previous_open
        )

        third_bearish = (
            third_close < third_open
        )

        third_bullish = (
            third_close > third_open
        )

        if current_range > 0:
            if (
                lower_wick >= current_body * 2
                and upper_wick <= current_body
                and current_close
                >= current_low + current_range * 0.6
            ):
                bullish_patterns.append("Hammer")

            if (
                upper_wick >= current_body * 2
                and lower_wick <= current_body
                and current_close
                <= current_low + current_range * 0.4
            ):
                bearish_patterns.append(
                    "Shooting Star"
                )

            if (
                current_body
                <= current_range * 0.1
            ):
                bullish_patterns.append("Doji")
                bearish_patterns.append("Doji")

            if (
                current_bullish
                and current_body
                >= current_range * 0.8
            ):
                bullish_patterns.append(
                    "Bullish Marubozu"
                )

            if (
                current_bearish
                and current_body
                >= current_range * 0.8
            ):
                bearish_patterns.append(
                    "Bearish Marubozu"
                )

        if (
            previous_bearish
            and current_bullish
            and current_open <= previous_close
            and current_close >= previous_open
            and current_body > previous_body
        ):
            bullish_patterns.append(
                "Bullish Engulfing"
            )

        if (
            previous_bullish
            and current_bearish
            and current_open >= previous_close
            and current_close <= previous_open
            and current_body > previous_body
        ):
            bearish_patterns.append(
                "Bearish Engulfing"
            )

        previous_midpoint = (
            previous_open + previous_close
        ) / 2

        if (
            previous_bearish
            and current_bullish
            and current_open < previous_close
            and current_close > previous_midpoint
            and current_close < previous_open
        ):
            bullish_patterns.append(
                "Piercing Pattern"
            )

        if (
            previous_bullish
            and current_bearish
            and current_open > previous_close
            and current_close < previous_midpoint
            and current_close > previous_open
        ):
            bearish_patterns.append(
                "Dark Cloud Cover"
            )

        small_previous_body = (
            previous_body
            <= abs(
                third_close - third_open
            ) * 0.5
        )

        if (
            third_bearish
            and small_previous_body
            and current_bullish
            and current_close
            > (third_open + third_close) / 2
        ):
            bullish_patterns.append(
                "Morning Star"
            )

        if (
            third_bullish
            and small_previous_body
            and current_bearish
            and current_close
            < (third_open + third_close) / 2
        ):
            bearish_patterns.append(
                "Evening Star"
            )

        if (
            previous_bearish
            and current_bullish
            and current_open > previous_close
            and current_close < previous_open
        ):
            bullish_patterns.append(
                "Bullish Harami"
            )

        if (
            previous_bullish
            and current_bearish
            and current_open < previous_close
            and current_close > previous_open
        ):
            bearish_patterns.append(
                "Bearish Harami"
            )

        bullish_patterns = list(
            dict.fromkeys(bullish_patterns)
        )

        bearish_patterns = list(
            dict.fromkeys(bearish_patterns)
        )

        primary_pattern = "None"

        if bullish_patterns:
            primary_pattern = bullish_patterns[0]

        elif bearish_patterns:
            primary_pattern = bearish_patterns[0]

        return {
            "bullish_patterns": bullish_patterns,
            "bearish_patterns": bearish_patterns,
            "primary_pattern": primary_pattern,
            "bullish_pattern_found": bool(
                bullish_patterns
            ),
            "bearish_pattern_found": bool(
                bearish_patterns
            ),
        }

    # =========================================================
    # CHART PATTERNS
    # =========================================================

    def detect_chart_patterns(
        self,
        dataframe: pd.DataFrame,
    ) -> Dict[str, Any]:
        patterns: List[str] = []

        if len(dataframe) < 60:
            return {
                "patterns": patterns,
                "primary_pattern": "None",
                "bullish_pattern_found": False,
            }

        recent_20 = dataframe.tail(20)
        recent_40 = dataframe.tail(40)
        recent_60 = dataframe.tail(60)

        current_close = self.safe_float(
            dataframe.iloc[-1]["close"]
        )

        high_20 = self.safe_float(
            recent_20["high"].max()
        )

        low_20 = self.safe_float(
            recent_20["low"].min()
        )

        high_40 = self.safe_float(
            recent_40["high"].max()
        )

        low_40 = self.safe_float(
            recent_40["low"].min()
        )

        range_20_percent = (
            ((high_20 - low_20) / low_20) * 100
            if low_20 > 0
            else 0.0
        )

        range_40_percent = (
            ((high_40 - low_40) / low_40) * 100
            if low_40 > 0
            else 0.0
        )

        previous_high_20 = self.safe_float(
            dataframe["high"]
            .iloc[-21:-1]
            .max()
        )

        if (
            range_20_percent <= 8
            and current_close > previous_high_20
        ):
            patterns.append(
                "Consolidation Breakout"
            )

        high_first_half = self.safe_float(
            recent_40.iloc[:20]["high"].max()
        )

        high_second_half = self.safe_float(
            recent_40.iloc[20:]["high"].max()
        )

        high_difference_percent = (
            abs(
                high_first_half
                - high_second_half
            )
            / max(
                high_first_half,
                high_second_half,
            )
            * 100
            if max(
                high_first_half,
                high_second_half,
            )
            > 0
            else 100.0
        )

        middle_low = self.safe_float(
            recent_40.iloc[10:30]["low"].min()
        )

        double_top_high = min(
            high_first_half,
            high_second_half,
        )

        if (
            high_difference_percent <= 3
            and middle_low
            < double_top_high * 0.92
            and current_close
            > double_top_high
        ):
            patterns.append(
                "Double Top Breakout"
            )

        low_first_half = self.safe_float(
            recent_40.iloc[:20]["low"].min()
        )

        low_second_half = self.safe_float(
            recent_40.iloc[20:]["low"].min()
        )

        low_difference_percent = (
            abs(
                low_first_half
                - low_second_half
            )
            / max(
                low_first_half,
                low_second_half,
            )
            * 100
            if max(
                low_first_half,
                low_second_half,
            )
            > 0
            else 100.0
        )

        middle_high = self.safe_float(
            recent_40.iloc[10:30]["high"].max()
        )

        double_bottom_low = max(
            low_first_half,
            low_second_half,
        )

        if (
            low_difference_percent <= 3
            and middle_high
            > double_bottom_low * 1.08
            and current_close
            > middle_high
        ):
            patterns.append(
                "Double Bottom Breakout"
            )

        recent_highs = (
            recent_20["high"].reset_index(
                drop=True
            )
        )

        recent_lows = (
            recent_20["low"].reset_index(
                drop=True
            )
        )

        high_slope = np.polyfit(
            np.arange(len(recent_highs)),
            recent_highs,
            1,
        )[0]

        low_slope = np.polyfit(
            np.arange(len(recent_lows)),
            recent_lows,
            1,
        )[0]

        if (
            high_slope < 0
            and low_slope > 0
            and current_close
            >= high_20 * 0.98
        ):
            patterns.append(
                "Symmetrical Triangle Breakout"
            )

        recent_60_high = self.safe_float(
            recent_60["high"].max()
        )

        cup_low = self.safe_float(
            recent_60.iloc[15:45]["low"].min()
        )

        left_high = self.safe_float(
            recent_60.iloc[:15]["high"].max()
        )

        right_high = self.safe_float(
            recent_60.iloc[-15:]["high"].max()
        )

        cup_high_difference = (
            abs(left_high - right_high)
            / max(left_high, right_high)
            * 100
            if max(left_high, right_high) > 0
            else 100.0
        )

        cup_depth_percent = (
            (min(left_high, right_high) - cup_low)
            / min(left_high, right_high)
            * 100
            if min(left_high, right_high) > 0
            else 0.0
        )

        if (
            cup_high_difference <= 5
            and 8 <= cup_depth_percent <= 35
            and current_close
            >= recent_60_high * 0.98
        ):
            patterns.append(
                "Cup and Handle Candidate"
            )

        patterns = list(
            dict.fromkeys(patterns)
        )

        return {
            "patterns": patterns,
            "primary_pattern": (
                patterns[0]
                if patterns
                else "None"
            ),
            "bullish_pattern_found": bool(
                patterns
            ),
            "range_20_percent": (
                self.round_number(
                    range_20_percent,
                    2,
                )
            ),
            "range_40_percent": (
                self.round_number(
                    range_40_percent,
                    2,
                )
            ),
        }

    # =========================================================
    # SUPPORT AND RESISTANCE
    # =========================================================

    def calculate_support_resistance(
        self,
        dataframe: pd.DataFrame,
    ) -> Dict[str, Any]:
        latest = dataframe.iloc[-1]

        current_price = self.safe_float(
            latest["close"]
        )

        atr = self.safe_float(
            latest["atr"]
        )

        recent_20 = dataframe.tail(20)
        recent_50 = dataframe.tail(50)

        support_20 = self.safe_float(
            recent_20["low"].min()
        )

        support_50 = self.safe_float(
            recent_50["low"].min()
        )

        resistance_20 = self.safe_float(
            dataframe["high"]
            .shift(1)
            .tail(20)
            .max()
        )

        resistance_50 = self.safe_float(
            dataframe["high"]
            .shift(1)
            .tail(50)
            .max()
        )

        ema_20 = self.safe_float(
            latest["ema_20"]
        )

        ema_50 = self.safe_float(
            latest["ema_50"]
        )

        support_candidates = [
            value
            for value in [
                support_20,
                support_50,
                ema_20,
                ema_50,
                current_price - atr,
            ]
            if value > 0 and value < current_price
        ]

        resistance_candidates = [
            value
            for value in [
                resistance_20,
                resistance_50,
                current_price + atr,
            ]
            if value > current_price
        ]

        nearest_support = (
            max(support_candidates)
            if support_candidates
            else 0.0
        )

        nearest_resistance = (
            min(resistance_candidates)
            if resistance_candidates
            else 0.0
        )

        return {
            "support_20": self.round_price(
                support_20
            ),
            "support_50": self.round_price(
                support_50
            ),
            "resistance_20": self.round_price(
                resistance_20
            ),
            "resistance_50": self.round_price(
                resistance_50
            ),
            "ema_20_support": self.round_price(
                ema_20
            ),
            "ema_50_support": self.round_price(
                ema_50
            ),
            "nearest_support": self.round_price(
                nearest_support
            ),
            "nearest_resistance": (
                self.round_price(
                    nearest_resistance
                )
            ),
        }

    # =========================================================
    # RELATIVE STRENGTH
    # =========================================================

    def calculate_relative_strength(
        self,
        stock_dataframe: pd.DataFrame,
        benchmark_dataframe: Optional[pd.DataFrame],
        timeframe: str,
    ) -> Dict[str, Any]:
        period = self._relative_strength_period(
            timeframe
        )

        if len(stock_dataframe) <= period:
            return {
                "available": False,
                "status": "Insufficient Data",
                "period_candles": period,
                "stock_return_percent": None,
                "benchmark_return_percent": None,
                "outperformance_percent": None,
                "outperforming": False,
            }

        stock_return = self.calculate_period_return(
            stock_dataframe["close"],
            period,
        )

        if (
            benchmark_dataframe is None
            or not isinstance(
                benchmark_dataframe,
                pd.DataFrame,
            )
            or benchmark_dataframe.empty
            or "close" not in benchmark_dataframe.columns
        ):
            return {
                "available": False,
                "status": "Benchmark Not Available",
                "period_candles": period,
                "stock_return_percent": (
                    self.round_number(
                        stock_return,
                        2,
                    )
                ),
                "benchmark_return_percent": None,
                "outperformance_percent": None,
                "outperforming": False,
            }

        benchmark_df = self.prepare_dataframe(
            benchmark_dataframe
        )

        if len(benchmark_df) <= period:
            return {
                "available": False,
                "status": "Insufficient Benchmark Data",
                "period_candles": period,
                "stock_return_percent": (
                    self.round_number(
                        stock_return,
                        2,
                    )
                ),
                "benchmark_return_percent": None,
                "outperformance_percent": None,
                "outperforming": False,
            }

        benchmark_return = self.calculate_period_return(
            benchmark_df["close"],
            period,
        )

        outperformance = (
            stock_return - benchmark_return
        )

        if outperformance >= 10:
            status = "Strong Outperformance"

        elif outperformance > 0:
            status = "Outperforming"

        elif outperformance <= -10:
            status = "Strong Underperformance"

        else:
            status = "Underperforming"

        return {
            "available": True,
            "status": status,
            "period_candles": period,
            "stock_return_percent": (
                self.round_number(
                    stock_return,
                    2,
                )
            ),
            "benchmark_return_percent": (
                self.round_number(
                    benchmark_return,
                    2,
                )
            ),
            "outperformance_percent": (
                self.round_number(
                    outperformance,
                    2,
                )
            ),
            "outperforming": (
                outperformance > 0
            ),
        }

    @staticmethod
    def calculate_period_return(
        close: pd.Series,
        period: int,
    ) -> float:
        if len(close) <= period:
            return 0.0

        starting_price = float(
            close.iloc[-period - 1]
        )

        ending_price = float(
            close.iloc[-1]
        )

        if starting_price <= 0:
            return 0.0

        return (
            (ending_price - starting_price)
            / starting_price
            * 100
        )

    # =========================================================
    # ENTRY, STOP LOSS AND TARGET
    # =========================================================

    def calculate_trade_levels(
        self,
        dataframe: pd.DataFrame,
        timeframe: str,
        support_resistance: Dict[str, Any],
    ) -> Dict[str, Any]:
        latest = dataframe.iloc[-1]

        current_price = self.safe_float(
            latest["close"]
        )

        atr = self.safe_float(
            latest["atr"]
        )

        previous_20_high = self.safe_float(
            dataframe["high"]
            .shift(1)
            .rolling(20)
            .max()
            .iloc[-1]
        )

        nearest_support = self.safe_float(
            support_resistance.get(
                "nearest_support"
            )
        )

        entry_buffer = self._entry_buffer(
            timeframe,
            atr,
        )

        if (
            previous_20_high > 0
            and current_price
            >= previous_20_high * 0.98
        ):
            entry_price = max(
                current_price,
                previous_20_high + entry_buffer,
            )

        else:
            entry_price = current_price

        atr_multiplier = self._stop_loss_atr_multiplier(
            timeframe
        )

        atr_stop = (
            entry_price - atr * atr_multiplier
        )

        if (
            nearest_support > 0
            and nearest_support < entry_price
        ):
            support_stop = (
                nearest_support - atr * 0.25
            )

            stop_loss = max(
                atr_stop,
                support_stop,
            )

        else:
            stop_loss = atr_stop

        if stop_loss <= 0 or stop_loss >= entry_price:
            stop_loss = (
                entry_price
                * (
                    1
                    - self._fallback_stop_percent(
                        timeframe
                    )
                    / 100
                )
            )

        risk_per_share = (
            entry_price - stop_loss
        )

        target_multiplier = (
            self._target_risk_multiplier(
                timeframe
            )
        )

        target = (
            entry_price
            + risk_per_share
            * target_multiplier
        )

        risk_percent = (
            risk_per_share
            / entry_price
            * 100
            if entry_price > 0
            else 0.0
        )

        reward_per_share = (
            target - entry_price
        )

        risk_reward_ratio = (
            reward_per_share
            / risk_per_share
            if risk_per_share > 0
            else 0.0
        )

        target_percent = (
            reward_per_share
            / entry_price
            * 100
            if entry_price > 0
            else 0.0
        )

        valid_risk_reward = (
            risk_reward_ratio >= 2.0
            and risk_percent > 0
        )

        return {
            "entry_price": self.round_price(
                entry_price
            ),
            "stop_loss": self.round_price(
                stop_loss
            ),
            "target": self.round_price(
                target
            ),
            "risk_per_share": self.round_price(
                risk_per_share
            ),
            "reward_per_share": self.round_price(
                reward_per_share
            ),
            "risk_percent": self.round_number(
                risk_percent,
                2,
            ),
            "target_percent": self.round_number(
                target_percent,
                2,
            ),
            "risk_reward_ratio": (
                self.round_number(
                    risk_reward_ratio,
                    2,
                )
            ),
            "valid_risk_reward": valid_risk_reward,
        }

    # =========================================================
    # TECHNICAL SCORE
    # =========================================================

    def calculate_technical_score(
        self,
        dataframe: pd.DataFrame,
        trend_analysis: Dict[str, Any],
        momentum_analysis: Dict[str, Any],
        volume_analysis: Dict[str, Any],
        volatility_analysis: Dict[str, Any],
        price_action_analysis: Dict[str, Any],
        candlestick_analysis: Dict[str, Any],
        chart_pattern_analysis: Dict[str, Any],
        relative_strength: Dict[str, Any],
        risk_levels: Dict[str, Any],
    ) -> Dict[str, Any]:
        score = 0

        positive_conditions: List[str] = []
        negative_conditions: List[str] = []
        missing_conditions: List[str] = []

        def add_condition(
            condition: bool,
            points: int,
            positive_text: str,
            missing_text: str,
            negative: bool = False,
        ) -> None:
            nonlocal score

            if condition:
                score += points
                positive_conditions.append(
                    positive_text
                )

            else:
                missing_conditions.append(
                    missing_text
                )

                if negative:
                    negative_conditions.append(
                        missing_text
                    )

        add_condition(
            trend_analysis["bullish_alignment"],
            14,
            "Price and EMA 9/20/50/200 are in strong bullish alignment.",
            "Strong EMA 9/20/50/200 bullish alignment is missing.",
        )

        add_condition(
            trend_analysis["long_term_bullish"],
            8,
            "Price and EMA 50 are above EMA 200.",
            "Long-term trend above EMA 200 is not confirmed.",
        )

        add_condition(
            trend_analysis["supertrend_bullish"],
            8,
            "Supertrend is bullish.",
            "Supertrend is not bullish.",
        )

        add_condition(
            (
                trend_analysis["directional_bullish"]
                and trend_analysis["adx"] >= 20
            ),
            8,
            "ADX and directional movement confirm bullish trend strength.",
            "ADX and directional trend strength are weak.",
        )

        add_condition(
            momentum_analysis["rsi_bullish"],
            7,
            "RSI is in the bullish momentum zone.",
            "RSI is outside the preferred 55–75 bullish zone.",
        )

        add_condition(
            momentum_analysis["macd_bullish"],
            8,
            "MACD is bullish.",
            "MACD bullish confirmation is missing.",
        )

        add_condition(
            momentum_analysis[
                "macd_momentum_rising"
            ],
            4,
            "MACD momentum is rising.",
            "MACD histogram momentum is not rising.",
        )

        add_condition(
            momentum_analysis[
                "positive_momentum"
            ],
            6,
            "Short-term and monthly price momentum are positive.",
            "Short-term price momentum is not fully positive.",
        )

        add_condition(
            volume_analysis["bullish_volume"],
            7,
            "Price rise is supported by above-average volume.",
            "Bullish above-average volume confirmation is missing.",
        )

        add_condition(
            volume_analysis["accumulation"],
            5,
            "Recent volume indicates accumulation.",
            "Recent volume accumulation is not confirmed.",
        )

        add_condition(
            (
                price_action_analysis[
                    "breakout_20"
                ]
                or price_action_analysis[
                    "breakout_50"
                ]
            ),
            8,
            "Price has confirmed a resistance breakout.",
            "Fresh 20-day or 50-day breakout is not confirmed.",
        )

        add_condition(
            price_action_analysis[
                "bullish_swing_structure"
            ],
            5,
            "Recent price structure is bullish.",
            "Recent bullish swing structure is incomplete.",
        )

        add_condition(
            price_action_analysis[
                "near_52_week_high"
            ],
            4,
            "Price is trading near its 52-week high.",
            "Price is not near its 52-week high.",
        )

        add_condition(
            candlestick_analysis[
                "bullish_pattern_found"
            ],
            4,
            "A bullish candlestick pattern is present.",
            "No bullish candlestick pattern is present.",
        )

        add_condition(
            chart_pattern_analysis[
                "bullish_pattern_found"
            ],
            4,
            "A bullish chart pattern is present.",
            "No confirmed bullish chart pattern is present.",
        )

        if relative_strength["available"]:
            add_condition(
                relative_strength["outperforming"],
                6,
                "Stock is outperforming the benchmark index.",
                "Stock is not outperforming the benchmark index.",
            )

        else:
            missing_conditions.append(
                "Benchmark relative-strength data is unavailable."
            )

        add_condition(
            risk_levels["valid_risk_reward"],
            8,
            "Risk-reward ratio is at least 1:2.",
            "Risk-reward ratio is below 1:2.",
        )

        if momentum_analysis["rsi_overbought"]:
            score -= 5

            negative_conditions.append(
                "RSI is overbought above 75."
            )

        if price_action_analysis["breakdown_20"]:
            score -= 15

            negative_conditions.append(
                "Price has broken below its 20-day support."
            )

        if candlestick_analysis[
            "bearish_pattern_found"
        ]:
            score -= 5

            negative_conditions.append(
                "A bearish candlestick pattern is present."
            )

        if volatility_analysis["status"] == "High":
            score -= 3

            negative_conditions.append(
                "Current volatility is high."
            )

        score = max(
            0,
            min(100, score),
        )

        if (
            score >= 80
            and not price_action_analysis[
                "breakdown_20"
            ]
            and risk_levels["valid_risk_reward"]
        ):
            technical_signal = "STRONG BUY"

        elif (
            score >= 65
            and trend_analysis[
                "supertrend_bullish"
            ]
            and risk_levels["valid_risk_reward"]
        ):
            technical_signal = "BUY"

        elif score >= 50:
            technical_signal = "WATCH"

        else:
            technical_signal = "NO BUY"

        technical_probability = self.calculate_probability(
            score=score,
            trend_analysis=trend_analysis,
            momentum_analysis=momentum_analysis,
            volume_analysis=volume_analysis,
            price_action_analysis=price_action_analysis,
            relative_strength=relative_strength,
            risk_levels=risk_levels,
        )

        return {
            "technical_score": int(score),
            "technical_signal": technical_signal,
            "technical_probability": (
                technical_probability
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

    def calculate_probability(
        self,
        score: int,
        trend_analysis: Dict[str, Any],
        momentum_analysis: Dict[str, Any],
        volume_analysis: Dict[str, Any],
        price_action_analysis: Dict[str, Any],
        relative_strength: Dict[str, Any],
        risk_levels: Dict[str, Any],
    ) -> float:
        """
        यह model confidence है, guaranteed return probability नहीं.
        """

        probability = 35.0 + score * 0.55

        if (
            trend_analysis["status"]
            == "Strong Bullish"
        ):
            probability += 3.0

        if (
            momentum_analysis["status"]
            == "Strong Bullish"
        ):
            probability += 2.0

        if (
            volume_analysis["status"]
            == "Strong Bullish"
        ):
            probability += 2.0

        if (
            price_action_analysis["breakout_50"]
        ):
            probability += 2.0

        if (
            relative_strength["available"]
            and relative_strength[
                "outperforming"
            ]
        ):
            probability += 2.0

        if risk_levels["valid_risk_reward"]:
            probability += 1.0

        if momentum_analysis["rsi_overbought"]:
            probability -= 4.0

        probability = max(
            1.0,
            min(95.0, probability),
        )

        return self.round_number(
            probability,
            2,
        )

    # =========================================================
    # LATEST INDICATOR VALUES
    # =========================================================

    def get_latest_indicator_values(
        self,
        dataframe: pd.DataFrame,
    ) -> Dict[str, Any]:
        latest = dataframe.iloc[-1]

        return {
            "open": self.round_price(
                latest["open"]
            ),
            "high": self.round_price(
                latest["high"]
            ),
            "low": self.round_price(
                latest["low"]
            ),
            "close": self.round_price(
                latest["close"]
            ),
            "volume": int(
                self.safe_float(
                    latest["volume"]
                )
            ),
            "ema_9": self.round_price(
                latest["ema_9"]
            ),
            "ema_20": self.round_price(
                latest["ema_20"]
            ),
            "ema_50": self.round_price(
                latest["ema_50"]
            ),
            "ema_200": self.round_price(
                latest["ema_200"]
            ),
            "rsi": self.round_number(
                latest["rsi"],
                2,
            ),
            "macd": self.round_number(
                latest["macd"],
                4,
            ),
            "macd_signal": self.round_number(
                latest["macd_signal"],
                4,
            ),
            "macd_histogram": self.round_number(
                latest["macd_histogram"],
                4,
            ),
            "atr": self.round_price(
                latest["atr"]
            ),
            "adx": self.round_number(
                latest["adx"],
                2,
            ),
            "plus_di": self.round_number(
                latest["plus_di"],
                2,
            ),
            "minus_di": self.round_number(
                latest["minus_di"],
                2,
            ),
            "supertrend": self.round_price(
                latest["supertrend"]
            ),
            "supertrend_direction": (
                "Bullish"
                if int(
                    self.safe_float(
                        latest[
                            "supertrend_direction"
                        ]
                    )
                )
                == 1
                else "Bearish"
            ),
            "volume_ratio": self.round_number(
                latest["volume_ratio"],
                2,
            ),
        }

    # =========================================================
    # TIMEFRAME SETTINGS
    # =========================================================

    def _minimum_candles_for_timeframe(
        self,
        timeframe: str,
    ) -> int:
        timeframe_map = {
            "swing": 220,
            "quarterly": 252,
            "half_yearly": 300,
            "yearly": 350,
            "five_year": 500,
            "ten_year": 500,
        }

        return timeframe_map.get(
            timeframe,
            self.settings.minimum_required_candles,
        )

    @staticmethod
    def _relative_strength_period(
        timeframe: str,
    ) -> int:
        timeframe_map = {
            "swing": 20,
            "quarterly": 60,
            "half_yearly": 125,
            "yearly": 252,
            "five_year": 500,
            "ten_year": 750,
        }

        return timeframe_map.get(
            timeframe,
            20,
        )

    @staticmethod
    def _stop_loss_atr_multiplier(
        timeframe: str,
    ) -> float:
        timeframe_map = {
            "swing": 1.5,
            "quarterly": 2.0,
            "half_yearly": 2.5,
            "yearly": 3.0,
            "five_year": 4.0,
            "ten_year": 5.0,
        }

        return timeframe_map.get(
            timeframe,
            1.5,
        )

    @staticmethod
    def _target_risk_multiplier(
        timeframe: str,
    ) -> float:
        timeframe_map = {
            "swing": 2.0,
            "quarterly": 2.5,
            "half_yearly": 3.0,
            "yearly": 3.5,
            "five_year": 4.0,
            "ten_year": 5.0,
        }

        return timeframe_map.get(
            timeframe,
            2.0,
        )

    @staticmethod
    def _fallback_stop_percent(
        timeframe: str,
    ) -> float:
        timeframe_map = {
            "swing": 4.0,
            "quarterly": 6.0,
            "half_yearly": 8.0,
            "yearly": 10.0,
            "five_year": 15.0,
            "ten_year": 20.0,
        }

        return timeframe_map.get(
            timeframe,
            4.0,
        )

    @staticmethod
    def _entry_buffer(
        timeframe: str,
        atr: float,
    ) -> float:
        multiplier_map = {
            "swing": 0.10,
            "quarterly": 0.15,
            "half_yearly": 0.20,
            "yearly": 0.25,
            "five_year": 0.30,
            "ten_year": 0.35,
        }

        multiplier = multiplier_map.get(
            timeframe,
            0.10,
        )

        return atr * multiplier

    # =========================================================
    # GENERAL HELPERS
    # =========================================================

    @staticmethod
    def safe_float(
        value: Any,
        default: float = 0.0,
    ) -> float:
        try:
            if value is None:
                return default

            number = float(value)

            if math.isnan(number) or math.isinf(number):
                return default

            return number

        except (TypeError, ValueError):
            return default

    @staticmethod
    def round_number(
        value: Any,
        digits: int = 2,
    ) -> float:
        try:
            number = float(value)

            if math.isnan(number) or math.isinf(number):
                return 0.0

            return round(number, digits)

        except (TypeError, ValueError):
            return 0.0

    @classmethod
    def round_price(
        cls,
        value: Any,
    ) -> float:
        number = cls.safe_float(value)

        if number >= 1000:
            return round(number, 2)

        if number >= 100:
            return round(number, 2)

        if number >= 1:
            return round(number, 2)

        return round(number, 4)

    @staticmethod
    def _serialize_datetime(
        value: Any,
    ) -> Optional[str]:
        if value is None:
            return None

        if isinstance(value, pd.Timestamp):
            return value.isoformat()

        try:
            parsed = pd.to_datetime(
                value,
                errors="coerce",
            )

            if pd.isna(parsed):
                return None

            return parsed.isoformat()

        except Exception:
            return str(value)

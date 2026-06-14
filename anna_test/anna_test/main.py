from datetime import datetime, timezone
from collections import deque

from contracts.bots import Strategy, StrategySettings, Trader
from contracts.market.data import KLine
from contracts.market.market import OrderSide


class AnnaTestStrategy(Strategy):
    def __init__(self, *, trader: Trader, init_balance: int, settings: StrategySettings) -> None:
        super().__init__(trader=trader, init_balance=init_balance, settings=settings)

        # 6-1 momentum parameters (in hourly candles)
        # 6 months ~ 6 * 30 * 24 = 4320 candles
        # 1 month  ~ 1 * 30 * 24 = 720 candles
        self.lookback = 4320
        self.skip = 720

        # Store enough close prices for the full lookback
        self.prices = deque(maxlen=self.lookback + 1)

        # Track position
        self.in_position = False

    def _momentum_signal(self) -> float | None:
        """
        6-1 time series momentum signal.
        Returns the return from 6 months ago to 1 month ago.
        Positive = uptrend, Negative = downtrend.
        """
        if len(self.prices) < self.lookback + 1:
            return None  # not enough data yet

        window = list(self.prices)

        price_window = window[: -(self.skip)]

        compounded = 1.0
        for i in range(1, len(price_window)):
            r = price_window[i] / price_window[i - 1]
            compounded *= r

        return compounded - 1

    async def on_tick(self, *, reference_time: datetime, kline_data: dict[str, KLine]) -> None:
        btc = kline_data.get("BTCUSDT")
        if btc is None:
            return

        # Record close price
        self.prices.append(btc.close_price)

        # Compute signal
        signal = self._momentum_signal()
        if signal is None:
            remaining = (self.lookback + 1) - len(self.prices)
            print(f"[{reference_time}] Warming up — {remaining} candles remaining")
            return

        print(
            f"[{reference_time}] Signal: {signal:.4f} | Price: {btc.close_price:.2f} | In position: {self.in_position}"
        )

        # ENTER — signal positive and not already holding
        if signal > 0 and not self.in_position:
            quantity = round(self.balance * 0.99 / btc.close_price, 6)
            print(f"  → BUY {quantity} BTC at {btc.close_price:.2f}")
            await self._send_order(
                base="BTC", quote="USDT", side=OrderSide.BUY, quantity=quantity, deadline="1h", price=None
            )
            self.in_position = True

        # EXIT — signal negative and currently holding
        elif signal <= 0 and self.in_position:
            quantity = round(self.bank.get("BTC", 0), 6)
            if quantity > 0:
                print(f"  → SELL {quantity} BTC at {btc.close_price:.2f}")
                await self._send_order(
                    base="BTC", quote="USDT", side=OrderSide.SELL, quantity=quantity, deadline="1h", price=None
                )
            self.in_position = False

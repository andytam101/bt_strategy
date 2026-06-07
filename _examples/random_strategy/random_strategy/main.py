from contracts.bots import Strategy
from contracts.market.data import KLine
from contracts.market.market import OrderSide, TimeInterval
from contracts.market.order import OrderStatus, TradingPriority

from strategies.random_strategy.exceptions import InvalidOrderStatusException

from datetime import datetime
import random


class RandomStrategy(Strategy):
    def __init__(self, *, trader, settings):
        super().__init__(trader=trader, settings=settings)
        
        self.quantity = 0.001
        self.threshold = 0.95
        self.hold = False

    async def on_tick(self, *, reference_time: datetime, kline_data: dict[str, KLine]) -> None:
        x = random.random()
        if x < self.threshold:
            return
        
        if self.hold:
            result = await self._send_order(
                ticker="BTCUSDT",
                side=OrderSide.BUY,
                quantity=self.quantity,
                price=None,
                deadline=TimeInterval(seconds=30),
                priority=TradingPriority.FILL
            )

            if result.status == OrderStatus.FILLED:
                self.hold = True
            else:
                raise InvalidOrderStatusException(f"Strategy cannot handle order status {result.status}. Only {OrderStatus.FILLED} is supported.")

            
        else:
            result = await self._send_order(
                ticker="BTCUSDT",
                side=OrderSide.SELL,
                quantity=self.quantity,
                price=None,
                deadline=TimeInterval(seconds=30),
                priority=TradingPriority.FILL
            )

            if result.status == OrderStatus.FILLED:
                self.hold = False
            else:
                raise InvalidOrderStatusException(f"Strategy cannot handle order status {result.status}. Only {OrderStatus.FILLED} is supported.")

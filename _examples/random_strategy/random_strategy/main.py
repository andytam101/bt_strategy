import random
from datetime import datetime
from typing import Mapping

from contracts.bots import Strategy, StrategySettings, Trader
from contracts.engine import Bank, KLineStreamer
from contracts.market import KLine, OrderResult, OrderSide
from pydantic import BaseModel, Field


class RandomStrategyParameters(BaseModel):
    threshold: float = Field(description="Probability of making an action", default=0.95)

    quantity: float = Field(description="Amount of BTC per transaction", default=0.001)


class RandomStrategy(Strategy):
    def __init__(
        self,
        *,
        bot_id: str,
        kline_streamer: KLineStreamer,
        trader: Trader,
        bank: Bank,
        backfilled_data: dict[str, list[KLine]],
        settings: StrategySettings,
    ) -> None:
        super().__init__(
            bot_id=bot_id,
            kline_streamer=kline_streamer,
            trader=trader,
            bank=bank,
            backfilled_data=backfilled_data,
            settings=settings,
        )

        params = RandomStrategyParameters.model_validate(settings.parameters)
        self.threshold = params.threshold
        self.quantity = params.quantity

    def on_tick(self, reference_time: datetime, kline_data: Mapping[str, KLine]) -> None:
        holding: float = self.bank.get_amount("BTC")
        x = random.random()

        if x < self.threshold:
            return

        if holding == 0:
            # BUY
            self._send_order(
                base="BTC", quote="USDT", side=OrderSide.BUY, quantity=self.quantity, price=None, deadline="30m"
            )
        else:
            # SELL
            self._send_order(
                base="BTC", quote="USDT", side=OrderSide.BUY, quantity=self.quantity, price=None, deadline="30m"
            )

    def on_order_result(self, reference_time: datetime, order_result: OrderResult) -> None:
        pass

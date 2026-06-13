import random
from datetime import datetime

from contracts.bots import Strategy, StrategySettings, Trader
from contracts.market import KLine, OrderSide
from pydantic import BaseModel, Field


class RandomStrategyParameters(BaseModel):
    threshold: float = Field(description="Probability of making an action", default=0.95)

    quantity: float = Field(description="Amount of BTC per transaction", default=0.001)


class RandomStrategy(Strategy):
    def __init__(self, *, trader: Trader, init_balance: int, settings: StrategySettings) -> None:
        super().__init__(trader=trader, init_balance=init_balance, settings=settings)

        params = RandomStrategyParameters.model_validate(settings.parameters)
        self.threshold = params.threshold
        self.quantity = params.quantity

    async def on_tick(self, *, reference_time: datetime, kline_data: dict[str, KLine]) -> None:
        holding: float = self.bank.get("BTC", 0)
        x = random.random()

        if x < self.threshold:
            return

        if holding == 0:
            # BUY
            result = await self._send_order(
                base="BTC", quote="USDT", side=OrderSide.BUY, quantity=self.quantity, price=None, deadline="30m"
            )

            self._update_bank_from_order(result)
        else:
            # SELL
            result = await self._send_order(
                base="BTC", quote="USDT", side=OrderSide.BUY, quantity=self.quantity, price=None, deadline="30m"
            )

            self._update_bank_from_order(result)

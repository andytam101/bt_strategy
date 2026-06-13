from datetime import datetime

from contracts.bots import Strategy, StrategySettings, Trader
from contracts.market.data import KLine


class _TemplateStrategy(Strategy):
    def __init__(self, *, trader: Trader, init_balance: int, settings: StrategySettings) -> None:
        super().__init__(trader=trader, init_balance=init_balance, settings=settings)

    async def on_tick(self, *, reference_time: datetime, kline_data: dict[str, KLine]) -> None:
        raise NotImplementedError("TODO: implement on_tick logic for _TemplateStrategy")

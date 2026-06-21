from datetime import datetime
from typing import Mapping

from contracts.bots import Strategy, StrategySettings, Trader
from contracts.engine import Bank, KLineStreamer
from contracts.market import KLine, OrderResult


class _TemplateStrategy(Strategy):
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

    def on_order_result(self, reference_time: datetime, order_result: OrderResult) -> None:
        raise NotImplementedError("TODO: implement on_order_result")

    def on_tick(self, reference_time: datetime, kline_data: Mapping[str, KLine]) -> None:
        raise NotImplementedError("TODO: implement on_tick")

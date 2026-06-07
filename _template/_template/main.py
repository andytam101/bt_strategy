from contracts.bots import Strategy
from contracts.market.data import KLineData

from datetime import datetime
import random

from contracts.market.market import OrderSide, TimeInterval
from contracts.market.order import TradingPriority

class _TemplateStrategy(Strategy):
    def __init__(self, *, trader, settings):
        super().__init__(trader=trader, settings=settings)

    def on_tick(self, *, reference_time: datetime, kline_data: dict[str, KLineData]) -> None:
        raise NotImplementedError("TODO: implement on_tick logic for _Template strategy")

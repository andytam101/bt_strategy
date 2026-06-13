import asyncio
import importlib
import inspect
import sys
from argparse import ArgumentParser, Namespace
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import requests
import yaml
from contracts.bots import Strategy, StrategySettings, UnsupportedPriorityError
from contracts.bots.trader import Trader
from contracts.market import OrderRequest, OrderResult, OrderSide, OrderStatus, TradingPriority
from contracts.market.data import KLine


class BacktestDifficulty(Enum):
    IDEAL = "ideal"
    STANDARD = "standard"
    HARD = "hard"
    WORST_CASE = "worst_case"

    @staticmethod
    def from_str(x: str) -> "BacktestDifficulty":
        if not x:
            return BacktestDifficulty.STANDARD
        first_letter = x[0].lower()
        if first_letter == "i":
            return BacktestDifficulty.IDEAL
        elif first_letter == "w":
            return BacktestDifficulty.WORST_CASE
        elif first_letter == "h":
            return BacktestDifficulty.HARD
        else:
            return BacktestDifficulty.STANDARD


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


SERVER_IP = "46.225.83.27"


@dataclass
class FillSimulation:
    """Result of simulating order execution, before balance validation.

    All quantities are denominated in the base asset; prices are in the
    quote currency per unit of base.
    """

    base_qty: float  # how much of the base asset was filled
    price: float  # average fill price (quote per base)
    status: OrderStatus  # FILLED, PARTIALLY_FILLED, or CANCELLED


class BacktestTrader(Trader):
    """Simulated trader that walks historical kline data and executes orders.

    Supports market orders (``requested_price=None``) and limit orders.

    Limit orders use a simple heuristic to estimate what fraction fills at
    the requested price; the remainder is handled per ``TradingPriority``.
    """

    PRICE_MARGIN: float = 0.0  # fractional tolerance when checking reasonableness

    def __init__(self, currency: str, init_balance: int, difficulty: BacktestDifficulty) -> None:
        super().__init__()
        self.next_klines: dict[str, KLine] = {}
        self.balance: float = init_balance
        self.difficulty = difficulty
        self.currency = currency
        self.all_balances: dict[str, float] = {currency: init_balance}

        self.exchange: dict[tuple[str, str], float] = {}
        self.price_histories: dict[str, list[KLine]] = {}
        self.order_history: list[OrderResult] = []
        self.wealth_history: list[tuple[datetime, float]] = []

    def evaluate_wealth(self) -> float:
        total: float = 0
        for currency in self.all_balances:
            if currency == self.currency:
                total += self.all_balances[currency]
            else:
                # TODO: will fail if it doesn't exist, need to calculated inferred value
                total += self.exchange[(currency, self.currency)] * self.all_balances[currency]

        return total

    def set_next_klines(self, klines: dict[str, KLine]) -> None:
        # record current wealth first
        reference_time = get_closing_time(klines)
        self.wealth_history.append((reference_time, self.evaluate_wealth()))
        
        self.next_klines = klines
        for symbol, kline in klines.items():
            history = self.price_histories.setdefault(symbol, [])
            history.append(kline)
            self.exchange[(kline.base, kline.quote)] = kline.close_price

    def _resolve_market_price(self, side: OrderSide, kline: KLine) -> float:
        """Return a realistic fill price given the current difficulty."""
        match self.difficulty:
            case BacktestDifficulty.IDEAL:
                return kline.open_price
            case BacktestDifficulty.STANDARD:
                return (kline.high_price + kline.low_price) / 2
            case BacktestDifficulty.HARD:
                if side == OrderSide.BUY:
                    return kline.high_price * 0.75 + kline.low_price * 0.25
                else:
                    return kline.high_price * 0.25 + kline.low_price * 0.75
            case BacktestDifficulty.WORST_CASE:
                if side == OrderSide.BUY:
                    return kline.high_price
                else:
                    return kline.low_price

    def _is_price_reasonable(self, price: float, side: OrderSide, kline: KLine) -> bool:
        """Check whether a limit price could realistically have been filled.

        A price is reasonable if at least some of the order could have been
        filled within this candle's range (expanded by ``PRICE_MARGIN``).
        """
        margin = self.PRICE_MARGIN
        if side == OrderSide.BUY:
            return price >= kline.low_price * (1 - margin)
        else:  # SELL
            return price <= kline.high_price * (1 + margin)

    def _estimate_limit_fill_ratio(self, price: float, side: OrderSide, kline: KLine) -> float:
        """Rough heuristic: what fraction fills at the exact limit price?

        Returns a value in [0, 1].
          - BUY: price near the low → most fills at limit.
          - SELL: price near the high → most fills at limit.
        """
        spread = kline.high_price - kline.low_price
        if spread == 0:
            return 1.0

        if side == OrderSide.BUY:
            return max(0.0, min(1.0, (kline.high_price - price) / spread))
        else:  # SELL
            return max(0.0, min(1.0, (price - kline.low_price) / spread))

    def simulate_fill(self, order_request: OrderRequest, kline: KLine) -> FillSimulation:
        """Step 1: Compute the fill outcome without checking balance constraints.

        Returns the quantity filled (in base asset), the average price
        (in quote per base), and the resulting status.
        """
        qty = order_request.quantity
        requested_price = order_request.price
        side = order_request.side
        priority = order_request.priority

        # Market order
        if requested_price is None:
            return FillSimulation(
                base_qty=qty,
                price=self._resolve_market_price(side, kline),
                status=OrderStatus.FILLED,
            )

        # Limit order — check reasonableness
        if not self._is_price_reasonable(requested_price, side, kline):
            if priority == TradingPriority.FILL:
                # Fall back to market
                return FillSimulation(
                    base_qty=qty,
                    price=self._resolve_market_price(side, kline),
                    status=OrderStatus.FILLED,
                )
            else:  # PRICE
                return FillSimulation(base_qty=0, price=0.0, status=OrderStatus.CANCELLED)

        # Price is reachable — heuristic partial fill at limit
        limit_ratio = self._estimate_limit_fill_ratio(requested_price, side, kline)
        limit_qty = qty * limit_ratio
        remainder = qty - limit_qty

        if priority == TradingPriority.FILL:
            market_price = self._resolve_market_price(side, kline)
            avg_price = (limit_qty * requested_price + remainder * market_price) / qty
            return FillSimulation(base_qty=qty, price=avg_price, status=OrderStatus.FILLED)
        else:  # PRICE
            if limit_qty > 0:
                return FillSimulation(base_qty=limit_qty, price=requested_price, status=OrderStatus.PARTIALLY_FILLED)
            else:
                return FillSimulation(base_qty=0, price=0.0, status=OrderStatus.CANCELLED)

    async def place_order(self, order_request: OrderRequest) -> OrderResult:
        if order_request.priority == TradingPriority.AUTO:
            raise UnsupportedPriorityError("AUTO Priority is not supported by backfill")

        self.all_balances.setdefault(order_request.base, 0)
        self.all_balances.setdefault(order_request.quote, 0)

        kline = self.next_klines[order_request.symbol]

        # ── Step 1: Simulate execution (price & quantity, ignoring balance) ──
        fill = self.simulate_fill(order_request, kline)

        # ── Step 2: Validate against available balance & inventory ───────────
        if order_request.side == OrderSide.BUY:
            cost = fill.price * fill.base_qty
            in_stock = self.all_balances[order_request.quote]
            if cost <= in_stock:
                result = OrderResult(
                    order_id=order_request.order_id,
                    timestamp=order_request.timestamp,
                    symbol=order_request.symbol,
                    base=order_request.base,
                    quote=order_request.quote,
                    side=order_request.side,
                    requested_quantity=order_request.quantity,
                    requested_price=order_request.price,
                    filled_quantity=fill.base_qty,
                    average_filled_price=fill.price,
                    status=fill.status,
                )
            else:
                result = OrderResult(
                    order_id=order_request.order_id,
                    timestamp=order_request.timestamp,
                    symbol=order_request.symbol,
                    base=order_request.base,
                    quote=order_request.quote,
                    side=order_request.side,
                    requested_quantity=order_request.quantity,
                    requested_price=order_request.price,
                    filled_quantity=in_stock / fill.price,
                    average_filled_price=fill.price,
                    status=OrderStatus.PARTIALLY_FILLED,
                )

            self.all_balances[order_request.base] += result.filled_quantity
            self.all_balances[order_request.quote] -= result.filled_quantity * result.average_filled_price

        else:
            cost = fill.base_qty
            in_stock = self.all_balances[order_request.base]
            if cost <= in_stock:
                result = OrderResult(
                    order_id=order_request.order_id,
                    timestamp=order_request.timestamp,
                    symbol=order_request.symbol,
                    base=order_request.base,
                    quote=order_request.quote,
                    side=order_request.side,
                    requested_quantity=order_request.quantity,
                    requested_price=order_request.price,
                    filled_quantity=fill.base_qty,
                    average_filled_price=fill.price,
                    status=fill.status,
                )
            else:
                result = OrderResult(
                    order_id=order_request.order_id,
                    timestamp=order_request.timestamp,
                    symbol=order_request.symbol,
                    base=order_request.base,
                    quote=order_request.quote,
                    side=order_request.side,
                    requested_quantity=order_request.quantity,
                    requested_price=order_request.price,
                    filled_quantity=in_stock,
                    average_filled_price=fill.price,
                    status=OrderStatus.PARTIALLY_FILLED,
                )

            self.all_balances[order_request.base] -= result.filled_quantity
            self.all_balances[order_request.quote] += result.filled_quantity * result.average_filled_price

        self.order_history.append(result)
        return result


def parse_args() -> Namespace:
    parser = ArgumentParser()

    parser.add_argument("bot", type=str)
    parser.add_argument("-i", "--initial", default=1000, type=int)

    parser.add_argument("-s", "--start", type=_parse_date, default=(datetime.now() - timedelta(days=30)).date())
    parser.add_argument("-e", "--end", type=_parse_date, default=datetime.now().date())

    parser.add_argument("-d", "--difficulty", type=BacktestDifficulty, default=BacktestDifficulty.STANDARD)

    return parser.parse_args()


def create_strategy_object(
    path: str, init_balance: int, difficulty: BacktestDifficulty
) -> tuple[Strategy, BacktestTrader]:
    """Dynamically import a Strategy subclass from a bot directory.

    Expects the convention::

        <bot_name>/
            settings.yaml
            <bot_name>/
                __init__.py
                main.py              # contains a Strategy subclass

    The strategy is instantiated with a ``BacktestTrader`` and settings
    loaded from ``settings.yaml``.
    """
    bot_dir = Path(path).resolve()
    bot_name = bot_dir.name

    # ── Dynamically import the bot's main module ──────────────────────
    sys.path.insert(0, str(bot_dir))
    try:
        module = importlib.import_module(f"{bot_name}.main")
    except ModuleNotFoundError as exc:
        raise ImportError(
            f"Could not import {bot_name}.main from {bot_dir}. "
            "Make sure the bot directory follows the convention:\n"
            f"  {bot_name}/settings.yaml\n"
            f"  {bot_name}/{bot_name}/main.py"
        ) from exc

    # ── Find the Strategy subclass (skip the abstract base itself) ────
    strategy_class: type[Strategy] | None = None
    for _name, obj in inspect.getmembers(module):
        if isinstance(obj, type) and issubclass(obj, Strategy) and obj is not Strategy:
            strategy_class = obj
            break

    if strategy_class is None:
        raise ValueError(
            f"No Strategy subclass found in module {bot_name}.main (looked inside {bot_dir / bot_name / 'main.py'})"
        )

    # ── Load settings ─────────────────────────────────────────────────
    settings_path = bot_dir / "settings.yaml"
    if not settings_path.exists():
        raise FileNotFoundError(f"settings.yaml not found at {settings_path}")

    with open(settings_path) as f:
        raw: dict[str, Any] = yaml.safe_load(f)

    settings = StrategySettings.model_validate(raw)

    # ── Instantiate ──
    trader = BacktestTrader(settings.currency, init_balance, difficulty)
    return strategy_class(trader=trader, init_balance=init_balance, settings=settings), trader


def transpose_klines(data: dict[str, list[KLine]]) -> list[dict[str, KLine]]:
    """Transpose ``{symbol: [kline, ...]}`` to ``[{symbol: kline}, ...]``.

    Each element of the returned list represents one tick across all symbols.
    Assumes all symbol lists have the same length and are time-aligned.
    """
    if not data:
        return []

    # Use the first symbol's kline count as the expected length
    first_key = next(iter(data))
    n = len(data[first_key])

    return [{symbol: klines[i] for symbol, klines in data.items()} for i in range(n)]


def get_data(
    start_date: date,
    end_date: date,
    interval: str,
    tickers: list[str],
) -> dict[str, list[KLine]]:
    """Fetch klines for all tickers from the indexer service.

    Queries the batch endpoint so all tickers are fetched in one call.
    Returns ``{symbol: [KLine, ...], ...}``.
    """
    base_url = f"http://{SERVER_IP}:5000/api/v1"

    params: dict[str, str] = {
        "symbols": ",".join(tickers),
        "interval": interval,
        "start_time": datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc).isoformat(),
        "end_time": datetime.combine(end_date, datetime.max.time(), tzinfo=timezone.utc).isoformat(),
    }

    resp = requests.get(f"{base_url}/klines/batch", params=params, timeout=120)
    resp.raise_for_status()

    body = resp.json()
    return {symbol: [KLine(**k) for k in raw_klines] for symbol, raw_klines in body["klines"].items()}


def get_closing_time(backtest_data: dict[str, KLine]) -> datetime:
    key = next(iter(backtest_data.keys()))
    return backtest_data[key].close_time


async def main() -> None:
    args = parse_args()

    initial: int = args.initial
    bot: str = args.bot
    start_date: date = args.start
    end_date: date = args.end

    strategy, trader = create_strategy_object(bot, initial, args.difficulty)
    print(
        f"Loaded {type(strategy).__name__}  |  "
        f"capital={initial} {strategy.currency}  |  "
        "range=[{start_date}, {end_date}]  |  interval={strategy.interval}"
    )

    data = get_data(start_date, end_date, strategy.interval, strategy.tickers_of_interest)
    for symbol, klines in data.items():
        print(f"Fetched {symbol}: {len(klines)} klines  [{klines[0].open_time} .. {klines[-1].open_time}]")

    backtest_data = transpose_klines(data)
    trader.set_next_klines(backtest_data[0])
    pairwise = zip(backtest_data[:-1], backtest_data[1:])

    print("Beginning backtest simulation")
    for current, future in pairwise:
        trader.set_next_klines(future)
        await strategy.on_tick(reference_time=get_closing_time(current), kline_data=current)

    print("Backtest simulation ended")

    wealth_list = [x[1] for x in trader.wealth_history]
    max_wealth = max(wealth_list)
    min_wealth = min(wealth_list)

    fill_rate = len([x for x in trader.order_history if x.status == OrderStatus.FILLED]) / len(trader.order_history)
    final_bal = trader.evaluate_wealth()
    holdings = ", ".join([f"{symbol}: {count:.3f}" for symbol, count in trader.all_balances.items()])

    print("=========== RESULTS ===========")
    print(f"Final holdings: {holdings}")
    print(f"Evaluated balance: {final_bal:.2f}")
    print(f"Return: {(final_bal - initial) / initial * 100:.2f}%")
    print(f"Number of orders executed: {len(trader.order_history)}")
    print(f"Max capital: {max_wealth:.2f}")
    print(f"Min capital: {min_wealth:.2f}")
    print(f"Max Gap: {max_wealth - min_wealth:.2f}")
    print(f"Fill rate: {fill_rate:.2f}")


if __name__ == "__main__":
    asyncio.run(main())

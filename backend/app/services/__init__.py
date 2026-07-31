"""Business logic shared by the REST API and the LLM auto-executor.

Public API:
    portfolio.get_portfolio(conn, cache)
    portfolio.execute_trade(conn, cache, source, ticker, side, quantity)  # async
    portfolio.record_snapshot(conn, cache)
    portfolio.list_history(conn)
    portfolio.priced_tickers(conn)

    watchlist_service.list_with_prices(conn, cache)
    watchlist_service.add_ticker(conn, cache, source, ticker)     # async
    watchlist_service.remove_ticker(conn, cache, source, ticker)  # async

Every rejection is a TradeError whose message is shown to the user verbatim.
"""

from . import portfolio, watchlist_service
from .errors import TradeError

__all__ = ["TradeError", "portfolio", "watchlist_service"]

"""Market data subsystem for FinAlly.

Public API:
    PriceUpdate         - Immutable price snapshot dataclass
    PriceCache          - Thread-safe in-memory price store
    MarketDataSource    - Abstract interface for data providers
    UnknownSymbolError  - Permanent rejection of a symbol (HTTP 400)
    PricingUnavailableError - Transient pricing failure (HTTP 503)
    create_market_data_source - Factory that selects simulator or Massive
    create_stream_router - FastAPI router factory for SSE endpoint
    normalize_symbol     - Shape-validate and uppercase a user-supplied ticker
"""

from .cache import PriceCache
from .factory import create_market_data_source
from .interface import MarketDataSource, PricingUnavailableError, UnknownSymbolError
from .models import PriceUpdate
from .stream import create_stream_router
from .symbols import normalize_symbol

__all__ = [
    "PriceUpdate",
    "PriceCache",
    "MarketDataSource",
    "UnknownSymbolError",
    "PricingUnavailableError",
    "create_market_data_source",
    "create_stream_router",
    "normalize_symbol",
]

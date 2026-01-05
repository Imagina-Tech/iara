"""
Collectors Module - Coleta de Dados (ETL)
"""

from .market_data import MarketDataCollector
from .news_scraper import NewsScraper
from .buzz_factory import BuzzFactory
from .macro_data import MacroDataCollector

__all__ = ["MarketDataCollector", "NewsScraper", "BuzzFactory", "MacroDataCollector"]

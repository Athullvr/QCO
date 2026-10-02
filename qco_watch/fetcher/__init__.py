from .anakin import AnakinFetcher, CreditLedger
from .base import BudgetExceeded, FetchError, FetchResult, Fetcher
from .chain import FetcherChain
from .drop import DropFolderFetcher
from .http import HttpFetcher
from .polite import Politeness
from .store import RawStore, sha256_bytes


def build_chain(settings, *, render: bool = False) -> FetcherChain:
    polite = Politeness(settings.user_agent, settings.min_request_interval_s)
    http = HttpFetcher(RawStore(settings.raw_dir), polite, ttl_hours=settings.listing_ttl_hours,
                       timeout=settings.request_timeout_s, render=render)
    anakin = AnakinFetcher(settings.anakin_api_key.get_secret_value(), RawStore(settings.anakin_cache_dir),
                           CreditLedger(settings.anakin_ledger), max_credits=settings.anakin_max_credits,
                           base_url=settings.anakin_base_url)
    return FetcherChain(http, anakin, DropFolderFetcher(settings.drop_dir))

import json
import logging
from typing import List, Union

import requests
from aiohttp import ClientSession

from pragma.core.assets import PragmaAsset, PragmaFutureAsset
from pragma.core.entry import FutureEntry
from pragma.core.utils import currency_pair_to_pair_id
from pragma.publisher.types import PublisherFetchError, PublisherInterfaceT

logger = logging.getLogger(__name__)


class OkxFutureFetcher(PublisherInterfaceT):
    BASE_URL: str = "https://okx.com/api/v5/market/tickers"
    SOURCE: str = "OKX"
    TIMESTAMP_URL: str = "https://www.okx.com/api/v5/public/instruments"
    publisher: str

    def __init__(self, assets: List[PragmaAsset], publisher):
        self.assets = assets
        self.publisher = publisher

    async def fetch_expiry_timestamp(self, asset, id, session):
        pair = asset["pair"]
        url = self.format_expiry_timestamp_url(id)
        async with session.get(url) as resp:
            if resp.status == 404:
                return PublisherFetchError(
                    f"No data found for {'/'.join(pair)} from OKX"
                )
            result = await resp.json(content_type="application/json")
            if (
                result["code"] == "51001"
                or result["msg"] == "Instrument ID does not exist"
            ):
                return PublisherFetchError(
                    f"No data found for {'/'.join(pair)} from OKX"
                )
            return result["data"][0]["expTime"]

    def format_expiry_timestamp_url(self, id):
        return f"{self.TIMESTAMP_URL}?instType=FUTURES&instId={id}"

    def fetch_sync_expiry_timestamp(self, asset, id):
        pair = asset["pair"]
        url = self.format_expiry_timestamp_url(id)
        resp = requests.get(url)
        if resp.status_code == 404:
            return PublisherFetchError(f"No data found for {'/'.join(pair)} from OKX")
        result = resp.json()
        if result["code"] == "51001" or result["msg"] == "Instrument ID does not exist":
            return PublisherFetchError(f"No data found for {'/'.join(pair)} from OKX")
        return result["data"][0]["expTime"]

    async def _fetch_pair(self, asset: PragmaFutureAsset, session: ClientSession):
        pair = asset["pair"]
        url = f"{self.BASE_URL}?instType=FUTURES&uly={pair[0]}-{pair[1]}"
        future_entries = []
        async with session.get(url) as resp:
            if resp.status == 404:
                return PublisherFetchError(
                    f"No data found for {'/'.join(pair)} from OKX"
                )

            content_type = resp.content_type
            if content_type and "json" in content_type:
                text = await resp.text()
                result = json.loads(text)
            else:
                raise ValueError(f"OKX: Unexpected content type: {content_type}")

            if (
                result["code"] == "51001"
                or result["msg"] == "Instrument ID does not exist"
            ):
                return PublisherFetchError(
                    f"No data found for {'/'.join(pair)} from OKX"
                )
            result_len = len(result["data"])
            if result_len > 1:
                for i in range(0, result_len):
                    expiry_timestamp = await self.fetch_expiry_timestamp(
                        asset, result["data"][i]["instId"], session
                    )
                    future_entries.append(
                        self._construct(asset, result["data"][i], expiry_timestamp)
                    )
            return future_entries

    def _fetch_pair_sync(
        self, asset: PragmaFutureAsset
    ) -> Union[FutureEntry, PublisherFetchError]:
        pair = asset["pair"]
        future_entries = []
        url = f"{self.BASE_URL}?instType=FUTURES&uly={pair[0]}-{pair[1]}"

        resp = requests.get(url)
        if resp.status_code == 404:
            return PublisherFetchError(f"No data found for {'/'.join(pair)} from OKX")

        text = resp.text
        result = json.loads(text)

        if result["code"] == "51001" or result["msg"] == "Instrument ID does not exist":
            return PublisherFetchError(f"No data found for {'/'.join(pair)} from OKX")
        result_len = len(result["data"])

        if result_len > 1:
            for i in range(0, result_len):
                expiry_timestamp = self.fetch_sync_expiry_timestamp(
                    asset, result["data"][i]["instId"]
                )
                future_entries.append(
                    self._construct(asset, result["data"][i], expiry_timestamp)
                )
        return future_entries

    def fetch_sync(self):
        entries = []
        for asset in self.assets:
            if asset["type"] != "FUTURE":
                logger.debug(f"Skipping OKX for non-future asset {asset}")
                continue
            future_entries = self._fetch_pair_sync(asset)
            if isinstance(future_entries, list):
                entries.extend(future_entries)
            else:
                entries.append(future_entries)
        return entries

    async def fetch(self, session: ClientSession):
        entries = []
        for asset in self.assets:
            if asset["type"] != "FUTURE":
                logger.debug(f"Skipping OKX for non-future asset {asset}")
                continue
            future_entries = await self._fetch_pair(asset, session)
            if isinstance(future_entries, list):
                entries.extend(future_entries)
            else:
                entries.append(future_entries)
        return entries

    def format_url(self, quote_asset, base_asset):
        url = f"{self.BASE_URL}?instType=FUTURES&uly={quote_asset}-{base_asset}"
        return url

    def _construct(self, asset, data, expiry_timestamp) -> List[FutureEntry]:
        pair = asset["pair"]
        timestamp = int(int(data["ts"]) / 1000)
        price = float(data["last"])
        price_int = int(price * (10 ** asset["decimals"]))
        pair_id = currency_pair_to_pair_id(*pair)
        volume = float(data["volCcy24h"])
        logger.info(f"Fetched future for {'/'.join(pair)} from OKX")

        return FutureEntry(
            pair_id=pair_id,
            price=price_int,
            volume=volume,
            timestamp=timestamp,
            source=self.SOURCE,
            publisher=self.publisher,
            expiry_timestamp=int(expiry_timestamp),
        )

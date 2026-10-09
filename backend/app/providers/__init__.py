import json
import os

from .alibaba import AlibabaProvider
from .alibaba_ground import AlibabaBusProvider, AlibabaTrainProvider
from .base import FlightProvider
from .flytoday import FlyTodayFlightProvider, FlyTodayTrainProvider
from .http_json import HttpJsonProvider
from .mock import MockProvider, SELLERS
from .mrbilit import MrBilitBusProvider, MrBilitFlightProvider, MrBilitTrainProvider
from .safarmarket import SafarmarketProvider


def _demo() -> list[FlightProvider]:
    return [MockProvider(n, m) for n, m in zip(SELLERS, (0.0, 0.03, 0.06, 0.01))]


def load_providers() -> list[FlightProvider]:
    """Pick the sellers.

    TORUB_PROVIDERS=alibaba,safarmarket,mrbilit,flytoday real sellers by name (comma list; `demo` = fictional sellers)
    TORUB_PROVIDERS_CONFIG=file.json   full control (types: alibaba, safarmarket, mrbilit, flytoday, http_json, mock)
    Neither set -> demo sellers.
    """
    path = os.getenv("TORUB_PROVIDERS_CONFIG")
    if path:
        out: list[FlightProvider] = []
        for cfg in json.load(open(path, encoding="utf-8")):
            t = cfg["type"]
            if t == "http_json":
                out.append(HttpJsonProvider(cfg))
            elif t == "mock":
                out.append(MockProvider(cfg["name"], cfg.get("markup", 0)))
            elif t == "alibaba":
                out.append(AlibabaProvider(max_concurrency=cfg.get("max_concurrency", 2)))
                out += [AlibabaTrainProvider(), AlibabaBusProvider()]
            elif t == "safarmarket":
                out.append(SafarmarketProvider(max_concurrency=cfg.get("max_concurrency", 2)))
            elif t == "mrbilit":
                out += [MrBilitFlightProvider(max_concurrency=cfg.get("max_concurrency", 3)), MrBilitTrainProvider(), MrBilitBusProvider()]
            elif t == "flytoday":
                out += [FlyTodayFlightProvider(max_concurrency=cfg.get("max_concurrency", 2)), FlyTodayTrainProvider()]
            else:
                raise ValueError(f"unknown provider type {t}")
        return out
    out = []
    for name in [n.strip().lower() for n in os.getenv("TORUB_PROVIDERS", "demo").split(",") if n.strip()]:
        if name == "alibaba":
            out += [AlibabaProvider(), AlibabaTrainProvider(), AlibabaBusProvider()]
        elif name == "safarmarket":
            out.append(SafarmarketProvider())
        elif name == "mrbilit":
            out += [MrBilitFlightProvider(), MrBilitTrainProvider(), MrBilitBusProvider()]
        elif name == "flytoday":
            out += [FlyTodayFlightProvider(), FlyTodayTrainProvider()]
        elif name == "demo":
            out.extend(_demo())
        else:
            raise ValueError(f"unknown provider {name!r} (known: alibaba, safarmarket, mrbilit, flytoday, demo)")
    return out


def is_demo(providers: list[FlightProvider]) -> bool:
    return all(isinstance(p, MockProvider) for p in providers)

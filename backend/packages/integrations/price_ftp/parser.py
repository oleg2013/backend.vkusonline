from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger("price_parser")

PRICE_TYPES = ("trade", "base", "sale", "cost")


@dataclass
class ParsedGoodPrice:
    article: str
    name: str
    prices: dict[str, int | None] = field(default_factory=dict)  # kopecks or None


def _parse_price_value(text: str | None) -> int | None:
    if not text or not text.strip():
        return None
    try:
        value = float(text.strip().replace(",", "."))
        return int(round(value * 100))
    except (ValueError, TypeError):
        return None


def parse_price_xml(xml_content: str) -> list[ParsedGoodPrice]:
    root = ET.fromstring(xml_content)
    goods_el = root.find("goods")
    if goods_el is None:
        return []

    results = []
    for good in goods_el.findall("good"):
        article_el = good.find("article")
        article = (article_el.text or "").strip() if article_el is not None else ""
        if not article:
            continue

        name_el = good.find("name")
        name = (name_el.text or "").strip() if name_el is not None else ""

        prices_el = good.find("prices")
        prices: dict[str, int | None] = {}
        if prices_el is not None:
            for pt in PRICE_TYPES:
                el = prices_el.find(pt)
                if el is not None:
                    prices[pt] = _parse_price_value(el.text)
                # If element doesn't exist at all, don't include in dict

        results.append(ParsedGoodPrice(article=article, name=name, prices=prices))

    logger.info("price_xml_parsed", total_goods=len(results))
    return results

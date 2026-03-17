"""
Клиент DaData API.
Автокомплит адресов (город, улица, дом) с получением координат.
"""

import time
import json
import logging
import requests
from typing import Optional

from geo_utils import safe_headers_for_log

logger = logging.getLogger("dadata_api")

SUGGEST_URL = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/suggest/address"


class DaDataAPIError(Exception):
    """Ошибка при работе с DaData API."""
    pass


class DaDataAPI:
    """Клиент для DaData Suggestions API (автокомплит адресов)."""

    def __init__(self, api_key: str, secret_key: str):
        self.api_key = api_key
        self.secret_key = secret_key

        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Token {api_key}",
            "X-Secret": secret_key,
        })

    def _request(self, body: dict) -> list:
        """
        Общий метод запроса к DaData Suggestions API.
        Возвращает список suggestions.
        """
        logger.info("→ POST %s", SUGGEST_URL)
        logger.debug("  Body: %s", json.dumps(body, ensure_ascii=False))
        logger.debug("  Headers: %s", safe_headers_for_log(dict(self.session.headers)))

        start = time.time()
        try:
            resp = self.session.post(SUGGEST_URL, json=body)
        except requests.RequestException as e:
            logger.error("Ошибка сети DaData: %s", e)
            raise DaDataAPIError(f"Ошибка сети DaData: {e}")

        elapsed = time.time() - start
        logger.info("← %d DaData (%.2f сек)", resp.status_code, elapsed)
        logger.debug("  Ответ (%d байт): %s", len(resp.content), resp.text[:2000])

        if resp.status_code != 200:
            raise DaDataAPIError(
                f"DaData HTTP {resp.status_code}: {resp.text[:300]}"
            )

        data = resp.json()
        suggestions = data.get("suggestions", [])
        logger.info("  Получено вариантов: %d", len(suggestions))
        return suggestions

    # ── Автокомплит города ───────────────────────────────────────────

    def suggest_city(self, query: str, count: int = 10) -> list:
        """
        Ищет города по введённой строке.
        Возвращает список вариантов с ФИАС-идентификаторами и координатами.

        Каждый элемент результата:
        {
            "value": "г Москва",
            "data": {
                "city": "Москва",
                "city_fias_id": "...",
                "region": "Москва",
                "geo_lat": "55.75396",
                "geo_lon": "37.620393",
                ...
            }
        }
        """
        body = {
            "query": query,
            "count": count,
            "from_bound": {"value": "city"},
            "to_bound": {"value": "city"},
        }

        logger.info("Поиск города: '%s'", query)
        return self._request(body)

    # ── Автокомплит улицы ────────────────────────────────────────────

    def suggest_street(self, query: str, city_fias_id: str, count: int = 10) -> list:
        """
        Ищет улицы по введённой строке в рамках конкретного города.

        Каждый элемент:
        {
            "value": "г Москва, ул Паустовского",
            "data": {
                "street": "Паустовского",
                "street_fias_id": "...",
                "street_type": "ул",
                "geo_lat": "...",
                "geo_lon": "...",
                ...
            }
        }
        """
        body = {
            "query": query,
            "count": count,
            "from_bound": {"value": "street"},
            "to_bound": {"value": "street"},
            "locations": [{"city_fias_id": city_fias_id}],
        }

        logger.info("Поиск улицы: '%s' (city_fias_id=%s)", query, city_fias_id)
        return self._request(body)

    # ── Автокомплит дома ─────────────────────────────────────────────

    def suggest_house(self, query: str, street_fias_id: str, count: int = 10) -> list:
        """
        Ищет номер дома по введённой строке в рамках конкретной улицы.

        Каждый элемент:
        {
            "value": "г Москва, ул Паустовского, д 5",
            "data": {
                "house": "5",
                "house_fias_id": "...",
                "geo_lat": "55.642",
                "geo_lon": "37.519",
                ...
            }
        }
        """
        body = {
            "query": query,
            "count": count,
            "from_bound": {"value": "house"},
            "to_bound": {"value": "house"},
            "locations": [{"street_fias_id": street_fias_id}],
        }

        logger.info("Поиск дома: '%s' (street_fias_id=%s)", query, street_fias_id)
        return self._request(body)

    # ── Полный адрес (свободный поиск) ───────────────────────────────

    def suggest_address(self, query: str, count: int = 10,
                        city_fias_id: str = None) -> list:
        """
        Свободный поиск адреса (город + улица + дом в одном запросе).
        Полезно как fallback, если пошаговый поиск не дал результата.
        """
        body = {
            "query": query,
            "count": count,
        }

        if city_fias_id:
            body["locations"] = [{"city_fias_id": city_fias_id}]

        logger.info("Свободный поиск адреса: '%s'", query)
        return self._request(body)

    # ── Извлечение данных из suggestion ──────────────────────────────

    @staticmethod
    def get_coordinates(suggestion: dict) -> tuple:
        """
        Извлекает координаты из результата DaData.
        Возвращает (lat, lon) или (None, None).
        """
        data = suggestion.get("data", {})
        lat = data.get("geo_lat")
        lon = data.get("geo_lon")

        if lat and lon:
            try:
                return float(lat), float(lon)
            except (ValueError, TypeError):
                return None, None
        return None, None

    @staticmethod
    def get_city_name(suggestion: dict) -> str:
        """Извлекает название города."""
        data = suggestion.get("data", {})
        # Приоритет: city, settlement, area
        return (data.get("city") or
                data.get("settlement") or
                data.get("area") or
                suggestion.get("value", ""))

    @staticmethod
    def get_city_fias_id(suggestion: dict) -> Optional[str]:
        """Извлекает ФИАС ID города."""
        data = suggestion.get("data", {})
        return data.get("city_fias_id") or data.get("settlement_fias_id")

    @staticmethod
    def get_street_name(suggestion: dict) -> str:
        """Извлекает название улицы."""
        data = suggestion.get("data", {})
        street_type = data.get("street_type", "")
        street = data.get("street", "")
        if street_type and street:
            return f"{street_type} {street}"
        return street or suggestion.get("value", "")

    @staticmethod
    def get_street_fias_id(suggestion: dict) -> Optional[str]:
        """Извлекает ФИАС ID улицы."""
        return suggestion.get("data", {}).get("street_fias_id")

    @staticmethod
    def get_house(suggestion: dict) -> str:
        """Извлекает номер дома."""
        data = suggestion.get("data", {})
        return data.get("house", suggestion.get("value", ""))

    @staticmethod
    def get_full_address(suggestion: dict) -> str:
        """Возвращает полный адрес из suggestion."""
        return suggestion.get("value", "")

    @staticmethod
    def get_region(suggestion: dict) -> str:
        """Извлекает регион."""
        return suggestion.get("data", {}).get("region_with_type", "")

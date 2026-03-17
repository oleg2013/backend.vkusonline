"""
Клиент DaData API для подсказок адресов и геокодирования.
Используется для интерактивного ввода: город → улица → дом.
Возвращает координаты (geo_lat, geo_lon) из ответа suggest.
"""

import logging
import json
from typing import Optional

import requests

import config
from utils import mask_token

logger = logging.getLogger("dadata_api")


class DaDataAPI:
    """Клиент DaData Suggest API."""

    def __init__(self):
        self.api_key = config.DADATA_API_KEY
        self.base_url = config.DADATA_SUGGEST_URL
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Token {self.api_key}",
        })

    def _request(self, body: dict) -> list[dict]:
        """
        Отправить запрос к DaData Suggest API.
        Возвращает список suggestions.
        """
        logger.info(f">>> REQUEST: POST {self.base_url}")
        logger.info(f">>> BODY: {json.dumps(body, ensure_ascii=False)}")

        try:
            response = self.session.post(self.base_url, json=body, timeout=10)
            logger.info(f"<<< RESPONSE: {response.status_code}")
            logger.debug(f"<<< BODY: {response.text[:2000]}")

            response.raise_for_status()
            data = response.json()
            suggestions = data.get("suggestions", [])
            logger.info(f"<<< Получено подсказок: {len(suggestions)}")
            return suggestions

        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка запроса к DaData: {e}")
            return []

    def suggest_city(self, query: str, count: int = 10) -> list[dict]:
        """
        Поиск города по началу названия.
        Возвращает список словарей с полями:
          - value: полное название
          - data.city: город
          - data.region_with_type: регион
          - data.city_fias_id: ФИАС-код города
          - data.geo_lat, data.geo_lon: координаты
        """
        body = {
            "query": query,
            "count": count,
            "from_bound": {"value": "city"},
            "to_bound": {"value": "city"},
        }
        logger.info(f"Поиск города: '{query}'")
        return self._request(body)

    def suggest_street(self, query: str, city_fias_id: str, count: int = 10) -> list[dict]:
        """
        Поиск улицы в пределах города.
        """
        body = {
            "query": query,
            "count": count,
            "locations": [{"city_fias_id": city_fias_id}],
            "from_bound": {"value": "street"},
            "to_bound": {"value": "street"},
        }
        logger.info(f"Поиск улицы: '{query}' в городе (ФИАС: {city_fias_id})")
        return self._request(body)

    def suggest_house(self, query: str, street_fias_id: str, count: int = 10) -> list[dict]:
        """
        Поиск дома на улице.
        Возвращает результаты с координатами (geo_lat, geo_lon).
        """
        body = {
            "query": query,
            "count": count,
            "locations": [{"street_fias_id": street_fias_id}],
            "from_bound": {"value": "house"},
            "to_bound": {"value": "house"},
        }
        logger.info(f"Поиск дома: '{query}' на улице (ФИАС: {street_fias_id})")
        return self._request(body)

    @staticmethod
    def get_display_city(suggestion: dict) -> str:
        """Получить отображаемое название города из подсказки."""
        data = suggestion.get("data", {})
        city = data.get("city", "")
        region = data.get("region_with_type", "")
        if region and region != city:
            return f"{city} ({region})"
        return city

    @staticmethod
    def get_display_street(suggestion: dict) -> str:
        """Получить отображаемое название улицы из подсказки."""
        data = suggestion.get("data", {})
        street_with_type = data.get("street_with_type", "")
        return street_with_type or suggestion.get("value", "")

    @staticmethod
    def get_display_house(suggestion: dict) -> str:
        """Получить отображаемый номер дома из подсказки."""
        data = suggestion.get("data", {})
        house = data.get("house", "")
        block_type = data.get("block_type", "")
        block = data.get("block", "")

        result = f"д. {house}"
        if block_type and block:
            result += f" {block_type} {block}"
        return result

    @staticmethod
    def get_coordinates(suggestion: dict) -> Optional[tuple[float, float]]:
        """
        Получить координаты из подсказки DaData.
        Возвращает (lat, lon) или None.
        """
        data = suggestion.get("data", {})
        geo_lat = data.get("geo_lat")
        geo_lon = data.get("geo_lon")

        if geo_lat and geo_lon:
            try:
                return float(geo_lat), float(geo_lon)
            except (ValueError, TypeError):
                return None
        return None

    @staticmethod
    def get_full_address(suggestion: dict) -> str:
        """Получить полный адрес из подсказки."""
        return suggestion.get("value", "")

    @staticmethod
    def get_city_fias_id(suggestion: dict) -> str:
        """Получить ФИАС-код города."""
        return suggestion.get("data", {}).get("city_fias_id", "")

    @staticmethod
    def get_street_fias_id(suggestion: dict) -> str:
        """Получить ФИАС-код улицы."""
        return suggestion.get("data", {}).get("street_fias_id", "")

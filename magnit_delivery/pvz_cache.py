"""
Кэш ПВЗ Magnit с поиском ближайших городов.

Загружает ВСЕ ПВЗ один раз, кэширует в файл, строит индекс по городам.
Если в выбранном городе нет ПВЗ — находит ближайшие города где они есть.
"""

import os
import json
import time
import logging
from typing import Optional
from collections import defaultdict

from magnit_api import MagnitAPI, MagnitAPIError
from geo_utils import haversine

logger = logging.getLogger("pvz_cache")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(SCRIPT_DIR, "cache")
CACHE_FILE = os.path.join(CACHE_DIR, "pvz_all.json")


class PVZCache:
    """
    Кэш всех ПВЗ Magnit с индексом по городам.

    - Загружает все ПВЗ через API (с пагинацией)
    - Сохраняет в cache/pvz_all.json
    - TTL настраивается (по умолчанию 24 часа)
    - Ищет ПВЗ по городу, региону, координатам
    - Если в городе нет ПВЗ — предлагает ближайшие города
    """

    def __init__(self, magnit_api: MagnitAPI, ttl_hours: int = 24):
        self.magnit = magnit_api
        self.ttl_seconds = ttl_hours * 3600

        self._all_points: list = []
        self._city_index: dict[str, list] = {}       # город (lower) → [пвз]
        self._city_coords: dict[str, tuple] = {}     # город (lower) → (avg_lat, avg_lon)
        self._loaded = False

    # ── Загрузка / обновление кэша ───────────────────────────────────

    def load(self, force_refresh: bool = False) -> int:
        """
        Загружает ПВЗ из кэша или API.

        Args:
            force_refresh: True = игнорировать кэш, загрузить из API

        Returns:
            Количество загруженных ПВЗ
        """
        if not force_refresh and self._try_load_from_file():
            self._build_index()
            self._loaded = True
            logger.info("ПВЗ загружены из кэша: %d точек, %d городов",
                        len(self._all_points), len(self._city_index))
            return len(self._all_points)

        # Загружаем из API
        logger.info("Загрузка всех ПВЗ из API Magnit...")
        self._all_points = self._fetch_all_from_api()
        self._save_to_file()
        self._build_index()
        self._loaded = True

        logger.info("ПВЗ загружены из API: %d точек, %d городов",
                    len(self._all_points), len(self._city_index))
        return len(self._all_points)

    def _try_load_from_file(self) -> bool:
        """Пытается загрузить из файла кэша. Возвращает True если успешно."""
        if not os.path.exists(CACHE_FILE):
            logger.debug("Файл кэша не найден: %s", CACHE_FILE)
            return False

        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Ошибка чтения кэша: %s", e)
            return False

        # Проверяем TTL
        cached_at = data.get("cached_at", 0)
        age_seconds = time.time() - cached_at
        age_hours = age_seconds / 3600

        if age_seconds > self.ttl_seconds:
            logger.info("Кэш устарел (%.1f ч, TTL=%d ч) — обновляем",
                        age_hours, self.ttl_seconds // 3600)
            return False

        self._all_points = data.get("points", [])
        logger.info("Кэш актуален (%.1f ч): %d ПВЗ", age_hours, len(self._all_points))
        return True

    def _save_to_file(self):
        """Сохраняет ПВЗ в файл кэша."""
        os.makedirs(CACHE_DIR, exist_ok=True)

        data = {
            "cached_at": time.time(),
            "cached_at_human": time.strftime("%Y-%m-%d %H:%M:%S"),
            "count": len(self._all_points),
            "points": self._all_points,
        }

        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
            logger.info("Кэш сохранён: %s (%d ПВЗ)", CACHE_FILE, len(self._all_points))
        except OSError as e:
            logger.error("Ошибка сохранения кэша: %s", e)

    def _fetch_all_from_api(self) -> list:
        """Загружает ВСЕ ПВЗ из API Magnit (все города, с пагинацией)."""
        all_points = []
        page = 1
        page_size = 1000

        while True:
            try:
                data = self.magnit._request(
                    "GET",
                    "/api/v1/magnit-post/pickup-points",
                    params={"page": page, "size": page_size},
                )
            except MagnitAPIError as e:
                logger.error("Ошибка загрузки ПВЗ (страница %d): %s", page, e)
                break

            if isinstance(data, list):
                points = data
            elif isinstance(data, dict):
                points = (data.get("items") or
                          data.get("pickupPoints") or
                          data.get("pickup_points") or [])
            else:
                points = []

            all_points.extend(points)
            logger.info("  Страница %d: получено %d ПВЗ (всего %d)",
                        page, len(points), len(all_points))

            if len(points) < page_size:
                break
            page += 1

        return all_points

    # ── Индексация ───────────────────────────────────────────────────

    def _build_index(self):
        """Строит индексы: по городу и средние координаты городов."""
        self._city_index = defaultdict(list)
        city_lat_sum = defaultdict(float)
        city_lon_sum = defaultdict(float)
        city_coord_count = defaultdict(int)

        for pp in self._all_points:
            city_raw = pp.get("city", "").strip()
            if not city_raw:
                continue

            city_key = city_raw.lower()
            self._city_index[city_key].append(pp)

            # Собираем координаты для средней точки города
            coords = pp.get("coordinates", {})
            lat = coords.get("latitude")
            lon = coords.get("longitude")
            if lat is not None and lon is not None:
                try:
                    city_lat_sum[city_key] += float(lat)
                    city_lon_sum[city_key] += float(lon)
                    city_coord_count[city_key] += 1
                except (ValueError, TypeError):
                    pass

        # Средние координаты для каждого города
        self._city_coords = {}
        for city_key in city_coord_count:
            n = city_coord_count[city_key]
            self._city_coords[city_key] = (
                city_lat_sum[city_key] / n,
                city_lon_sum[city_key] / n,
            )

        # Нормализуем defaultdict → обычный dict
        self._city_index = dict(self._city_index)

        logger.debug("Индекс построен: %d городов", len(self._city_index))

    # ── Поиск ПВЗ ───────────────────────────────────────────────────

    def get_cities_list(self) -> list:
        """Возвращает список всех городов где есть ПВЗ, с количеством."""
        self._ensure_loaded()
        result = []
        for city_key, points in sorted(self._city_index.items()):
            # Берём оригинальное написание из первого ПВЗ
            original_name = points[0].get("city", city_key)
            result.append({
                "city": original_name,
                "city_key": city_key,
                "count": len(points),
            })
        return result

    def get_points_in_city(self, city_name: str) -> list:
        """Возвращает все ПВЗ в указанном городе."""
        self._ensure_loaded()
        city_key = city_name.lower().strip()
        return list(self._city_index.get(city_key, []))

    def has_city(self, city_name: str) -> bool:
        """Проверяет есть ли ПВЗ в городе."""
        self._ensure_loaded()
        return city_name.lower().strip() in self._city_index

    def find_nearest_cities(self, lat: float, lon: float, limit: int = 5,
                            exclude_city: str = None) -> list:
        """
        Находит ближайшие города с ПВЗ относительно заданных координат.

        Args:
            lat, lon: Координаты точки (обычно — координаты города клиента)
            limit: Сколько городов вернуть
            exclude_city: Город который нужно исключить из результатов

        Returns:
            Список словарей:
            [{"city": "Хабаровск", "count": 15, "distance_km": 120.5}, ...]
        """
        self._ensure_loaded()

        exclude_key = exclude_city.lower().strip() if exclude_city else None
        cities_with_dist = []

        for city_key, (city_lat, city_lon) in self._city_coords.items():
            if city_key == exclude_key:
                continue

            dist = haversine(lat, lon, city_lat, city_lon)
            original_name = self._city_index[city_key][0].get("city", city_key)
            count = len(self._city_index[city_key])

            cities_with_dist.append({
                "city": original_name,
                "city_key": city_key,
                "count": count,
                "distance_km": round(dist, 1),
                "lat": city_lat,
                "lon": city_lon,
            })

        cities_with_dist.sort(key=lambda x: x["distance_km"])
        return cities_with_dist[:limit]

    def find_nearest_points(self, lat: float, lon: float, city_name: str = None,
                            limit: int = 10) -> list:
        """
        Находит ближайшие ПВЗ к заданным координатам.

        Args:
            lat, lon: Координаты клиента
            city_name: Если указан — ищем только в этом городе
            limit: Сколько ПВЗ вернуть

        Returns:
            Список ПВЗ с добавленным полем _distance_km
        """
        self._ensure_loaded()

        if city_name:
            points = self.get_points_in_city(city_name)
        else:
            points = list(self._all_points)

        for pp in points:
            coords = pp.get("coordinates", {})
            pp_lat = coords.get("latitude")
            pp_lon = coords.get("longitude")

            if pp_lat is not None and pp_lon is not None:
                try:
                    dist = haversine(lat, lon, float(pp_lat), float(pp_lon))
                    pp["_distance_km"] = round(dist, 2)
                except (ValueError, TypeError):
                    pp["_distance_km"] = 99999
            else:
                pp["_distance_km"] = 99999

        points.sort(key=lambda p: p.get("_distance_km", 99999))
        return points[:limit]

    def get_stats(self) -> dict:
        """Возвращает статистику кэша."""
        self._ensure_loaded()
        return {
            "total_points": len(self._all_points),
            "total_cities": len(self._city_index),
            "cache_file": CACHE_FILE,
            "cache_exists": os.path.exists(CACHE_FILE),
        }

    def _ensure_loaded(self):
        if not self._loaded:
            raise RuntimeError("Кэш не загружен. Вызовите .load() сначала.")

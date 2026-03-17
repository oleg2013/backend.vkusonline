"""
Клиент API 5Post.
JWT-аутентификация, загрузка точек выдачи, складов, создание заказов.
Файловый кэш точек выдачи с настраиваемым TTL.
"""

import base64
import json
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Optional

import requests

import config
from models import (
    PickupPoint, Rate, CellLimits, WorkHours, Warehouse, Order
)
from utils import mask_token

logger = logging.getLogger("fivepost_api")


class FivePostAPI:
    """Клиент REST API 5Post."""

    def __init__(self):
        self.base_url = config.FIVEPOST_BASE_URL
        self.api_key = config.FIVEPOST_API_KEY
        self.session = requests.Session()

        # JWT-токен и время его истечения
        self._jwt_token: Optional[str] = None
        self._jwt_expires_at: float = 0.0

        # Кэш точек выдачи в памяти
        self._pickup_points_memory: Optional[list[PickupPoint]] = None

        # Путь к файловому кэшу
        os.makedirs(config.CACHE_DIR, exist_ok=True)
        self._cache_file = os.path.join(config.CACHE_DIR, config.PICKUP_POINTS_CACHE_FILE)

    # ======================== JWT ========================

    def _get_jwt_expiration(self, token: str) -> float:
        """Извлечь время истечения (exp) из JWT-токена."""
        try:
            parts = token.split(".")
            if len(parts) != 3:
                return 0.0
            payload_b64 = parts[1]
            padding = 4 - len(payload_b64) % 4
            if padding != 4:
                payload_b64 += "=" * padding
            payload_bytes = base64.urlsafe_b64decode(payload_b64)
            payload = json.loads(payload_bytes)
            return float(payload.get("exp", 0))
        except Exception as e:
            logger.warning(f"Не удалось извлечь exp из JWT: {e}")
            return 0.0

    def _is_token_valid(self) -> bool:
        """Проверить, действителен ли текущий JWT-токен (с запасом 5 мин)."""
        if not self._jwt_token:
            return False
        return time.time() < (self._jwt_expires_at - 300)

    def _ensure_token(self):
        """Получить или обновить JWT-токен при необходимости."""
        if not self._is_token_valid():
            self._refresh_token()

    def _refresh_token(self):
        """Получить новый JWT-токен от 5Post API."""
        url = f"{self.base_url}/jwt-generate-claims/rs256/1"
        params = {"apikey": self.api_key}
        headers = {"content-type": "application/x-www-form-urlencoded"}
        data = "subject=OpenAPI&audience=A122019!"

        logger.info(f">>> REQUEST: POST {url}?apikey=***")
        logger.info(f">>> BODY: {data}")

        try:
            response = self.session.post(
                url, params=params, headers=headers, data=data, timeout=30
            )
            logger.info(f"<<< RESPONSE: {response.status_code}")

            if response.status_code == 401:
                error_data = response.json()
                logger.error(f"Ошибка аутентификации: {json.dumps(error_data, ensure_ascii=False)}")
                raise RuntimeError(f"Ошибка получения JWT-токена: {error_data}")

            response.raise_for_status()
            result = response.json()

            if result.get("status") == "ok" and "jwt" in result:
                self._jwt_token = result["jwt"]
                self._jwt_expires_at = self._get_jwt_expiration(self._jwt_token)
                logger.info(
                    f"JWT-токен получен: {mask_token(self._jwt_token)}, "
                    f"истекает: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self._jwt_expires_at))}"
                )
            else:
                logger.error(f"Неожиданный ответ при получении токена: {result}")
                raise RuntimeError(f"Не удалось получить JWT-токен: {result}")

        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка сети при получении токена: {e}")
            raise RuntimeError(f"Ошибка подключения к API 5Post: {e}")

    def _get_auth_headers(self) -> dict:
        """Получить заголовки с авторизацией."""
        self._ensure_token()
        return {
            "authorization": f"Bearer {self._jwt_token}",
            "content-type": "application/json",
        }

    def _api_request(self, method: str, endpoint: str,
                     json_data: Optional[dict] = None,
                     params: Optional[dict] = None,
                     retry_on_401: bool = True) -> dict:
        """
        Универсальный метод для API-запросов с авторизацией.
        При получении 401 — обновляет токен и повторяет запрос (один раз).
        """
        url = f"{self.base_url}{endpoint}"
        headers = self._get_auth_headers()

        # Логирование запроса
        log_headers = {k: (mask_token(v.replace("Bearer ", "")) if k == "authorization" else v)
                       for k, v in headers.items()}
        logger.info(f">>> REQUEST: {method.upper()} {url}")
        logger.info(f">>> HEADERS: {json.dumps(log_headers, ensure_ascii=False)}")
        if json_data:
            body_str = json.dumps(json_data, ensure_ascii=False)
            if len(body_str) > 2000:
                logger.info(f">>> BODY: {body_str[:2000]}... (обрезано, всего {len(body_str)} символов)")
            else:
                logger.info(f">>> BODY: {body_str}")
        if params:
            logger.info(f">>> PARAMS: {params}")

        try:
            response = self.session.request(
                method=method, url=url, headers=headers,
                json=json_data, params=params, timeout=60
            )

            # Логирование ответа
            logger.info(f"<<< RESPONSE: {response.status_code}")
            body_text = response.text
            if len(body_text) > 3000:
                logger.info(f"<<< BODY: {body_text[:3000]}... (обрезано, всего {len(body_text)} символов)")
            else:
                logger.info(f"<<< BODY: {body_text}")

            # Обработка 401 — обновление токена
            if response.status_code == 401 and retry_on_401:
                logger.warning("Получен 401 — обновляю JWT-токен и повторяю запрос...")
                self._refresh_token()
                return self._api_request(
                    method, endpoint, json_data, params, retry_on_401=False
                )

            response.raise_for_status()
            return response.json()

        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка API-запроса: {e}")
            raise

    # ======================== Склады ========================

    def get_warehouses(self) -> list[Warehouse]:
        """
        Получить список всех складов партнёра.
        GET /api/v1/getWarehouseAll?page=N
        """
        logger.info("=== Загрузка складов ===")
        warehouses = []
        page = 0

        while True:
            data = self._api_request("GET", "/api/v1/getWarehouseAll", params={"page": page})

            content = data.get("content", [])
            for item in content:
                wh = Warehouse(
                    id=item.get("id", ""),
                    name=item.get("name", ""),
                    full_address=self._build_warehouse_address(item),
                    partner_location_id=item.get("partnerLocationId", ""),
                    city=item.get("city", ""),
                    status=item.get("status", ""),
                )
                if wh.status == "ACTIVE":
                    warehouses.append(wh)

            total_pages = data.get("totalPages", 1)
            page += 1
            if page >= total_pages:
                break

        logger.info(f"Загружено складов: {len(warehouses)}")
        return warehouses

    @staticmethod
    def _build_warehouse_address(item: dict) -> str:
        """Собрать полный адрес склада."""
        parts = []
        if item.get("city"):
            parts.append(f"г. {item['city']}")
        if item.get("street"):
            parts.append(f"ул. {item['street']}")
        if item.get("houseNumber"):
            parts.append(f"д. {item['houseNumber']}")
        return ", ".join(parts) if parts else item.get("fullAddress", "Адрес не указан")

    # ======================== Кэш точек выдачи ========================

    def _is_cache_valid(self) -> bool:
        """Проверить, актуален ли файловый кэш точек выдачи."""
        if not os.path.exists(self._cache_file):
            logger.info("Файл кэша не найден.")
            return False

        try:
            with open(self._cache_file, "r", encoding="utf-8") as f:
                cache_data = json.load(f)

            cached_at_str = cache_data.get("cached_at", "")
            if not cached_at_str:
                return False

            cached_at = datetime.fromisoformat(cached_at_str)
            ttl = timedelta(hours=config.PICKUP_POINTS_CACHE_TTL_HOURS)
            is_valid = datetime.now() < cached_at + ttl
            points_count = len(cache_data.get("points", []))

            if is_valid:
                logger.info(
                    f"Кэш актуален: {points_count} точек, "
                    f"создан {cached_at.strftime('%Y-%m-%d %H:%M:%S')}, "
                    f"TTL {config.PICKUP_POINTS_CACHE_TTL_HOURS}ч"
                )
            else:
                logger.info(
                    f"Кэш устарел: создан {cached_at.strftime('%Y-%m-%d %H:%M:%S')}, "
                    f"TTL {config.PICKUP_POINTS_CACHE_TTL_HOURS}ч истёк"
                )

            return is_valid

        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.warning(f"Ошибка чтения кэша: {e}")
            return False

    def _load_from_cache(self) -> list[PickupPoint]:
        """Загрузить точки выдачи из файлового кэша."""
        logger.info(f"Загрузка точек из кэша: {self._cache_file}")

        with open(self._cache_file, "r", encoding="utf-8") as f:
            cache_data = json.load(f)

        points = []
        for item in cache_data.get("points", []):
            point = self._parse_pickup_point(item)
            if point:
                points.append(point)

        logger.info(f"Загружено из кэша: {len(points)} точек")
        return points

    def _save_to_cache(self, raw_points: list[dict]):
        """Сохранить сырые данные точек выдачи в файловый кэш."""
        cache_data = {
            "cached_at": datetime.now().isoformat(),
            "points_count": len(raw_points),
            "points": raw_points,
        }

        with open(self._cache_file, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, ensure_ascii=False)

        file_size_mb = os.path.getsize(self._cache_file) / (1024 * 1024)
        logger.info(
            f"Кэш сохранён: {len(raw_points)} точек, "
            f"файл: {self._cache_file} ({file_size_mb:.1f} МБ)"
        )

    # ======================== Точки выдачи ========================

    def load_pickup_points_from_cache(self) -> list[PickupPoint]:
        """
        Загрузить точки выдачи ТОЛЬКО из файлового кэша.
        Возвращает пустой список, если кэш отсутствует или повреждён.
        Используется основной программой (main.py).
        """
        # Кэш в памяти (для повторных вызовов в одной сессии)
        if self._pickup_points_memory is not None:
            logger.info(f"Используем кэш в памяти: {len(self._pickup_points_memory)} точек")
            return self._pickup_points_memory

        if not os.path.exists(self._cache_file):
            logger.warning(f"Файл кэша не найден: {self._cache_file}")
            return []

        try:
            points = self._load_from_cache()
            self._pickup_points_memory = points
            return points
        except Exception as e:
            logger.error(f"Ошибка загрузки кэша: {e}")
            return []

    def get_cache_info(self) -> dict:
        """Получить информацию о состоянии кэша."""
        if not os.path.exists(self._cache_file):
            return {"exists": False}

        try:
            with open(self._cache_file, "r", encoding="utf-8") as f:
                cache_data = json.load(f)

            cached_at_str = cache_data.get("cached_at", "")
            cached_at = datetime.fromisoformat(cached_at_str) if cached_at_str else None
            points_count = cache_data.get("points_count", len(cache_data.get("points", [])))
            file_size_mb = os.path.getsize(self._cache_file) / (1024 * 1024)

            is_expired = False
            if cached_at:
                ttl = timedelta(hours=config.PICKUP_POINTS_CACHE_TTL_HOURS)
                is_expired = datetime.now() >= cached_at + ttl

            return {
                "exists": True,
                "cached_at": cached_at,
                "points_count": points_count,
                "file_size_mb": file_size_mb,
                "is_expired": is_expired,
            }
        except Exception:
            return {"exists": True, "error": True}

    def update_pickup_points_cache(self) -> int:
        """
        Принудительно обновить кэш точек выдачи из API.
        Используется скриптом update_cache.py.
        Возвращает количество загруженных точек.
        """
        points = self._load_from_api()
        self._pickup_points_memory = points
        return len(points)

    def get_pickup_points(self, force_reload: bool = False) -> list[PickupPoint]:
        """
        Получить все активные точки выдачи.
        Приоритет: память → файловый кэш → API.
        Файловый кэш обновляется раз в PICKUP_POINTS_CACHE_TTL_HOURS часов.
        """
        # 1. Кэш в памяти (мгновенно, для повторных заказов в одной сессии)
        if self._pickup_points_memory is not None and not force_reload:
            logger.info(f"Используем кэш в памяти: {len(self._pickup_points_memory)} точек")
            return self._pickup_points_memory

        # 2. Файловый кэш (быстро, не тратит лимиты API)
        if not force_reload and self._is_cache_valid():
            points = self._load_from_cache()
            if points:
                self._pickup_points_memory = points
                return points

        # 3. Загрузка из API (медленно, тратит лимит 50000 точек/час)
        points = self._load_from_api()
        self._pickup_points_memory = points
        return points

    def _load_from_api(self) -> list[PickupPoint]:
        """Загрузить все точки выдачи из API с задержкой между запросами."""
        logger.info("=== Загрузка точек выдачи из API ===")
        all_points = []
        all_raw_points = []  # Сырые данные для кэша
        page = 0
        total_pages = 1

        while page < total_pages:
            body = {
                "pageSize": config.PICKUP_POINTS_PAGE_SIZE,
                "pageNumber": page,
            }

            try:
                data = self._api_request("POST", "/api/v1/pickuppoints/query", json_data=body)
            except requests.exceptions.HTTPError as e:
                if e.response is not None and e.response.status_code == 429:
                    logger.warning(
                        f"Rate limit (429) на странице {page + 1}. "
                        f"Загружено {len(all_points)} точек из доступных."
                    )
                    break
                raise

            total_pages = data.get("totalPages", 1)
            total_elements = data.get("totalElements", 0)
            content = data.get("content", [])

            if page == 0:
                logger.info(f"Всего точек: {total_elements}, страниц: {total_pages}")

            # Сохраняем сырые данные для кэша
            all_raw_points.extend(content)

            for item in content:
                point = self._parse_pickup_point(item)
                if point:
                    all_points.append(point)

            logger.info(f"Страница {page + 1}/{total_pages}: загружено {len(content)} точек")
            page += 1

            # Задержка между запросами для соблюдения rate limit
            if page < total_pages:
                delay = config.PICKUP_POINTS_REQUEST_DELAY
                logger.debug(f"Задержка {delay} сек. перед следующим запросом...")
                time.sleep(delay)

        # Сохраняем в файловый кэш
        if all_raw_points:
            self._save_to_cache(all_raw_points)

        logger.info(f"Всего загружено точек: {len(all_points)}")
        return all_points

    def _parse_pickup_point(self, item: dict) -> Optional[PickupPoint]:
        """Разбор одной точки выдачи из JSON."""
        try:
            address = item.get("address", {})

            # Парсинг тарифов
            rates = []
            for r in item.get("rate", []):
                rate = Rate(
                    rate_type=r.get("rateType", ""),
                    rate_value_with_vat=float(r.get("rateValueWithVat", 0)),
                    rate_extra_value_with_vat=float(r.get("rateExtraValueWithVat", 0)),
                    zone=str(r.get("zone", "")),
                    currency=r.get("rateCurrency", "RUB"),
                )
                rates.append(rate)

            # Парсинг ограничений ячейки
            cl = item.get("cellLimits", {})
            cell_limits = CellLimits(
                max_width_mm=int(cl.get("maxCellWidth", 0)),
                max_height_mm=int(cl.get("maxCellHeight", 0)),
                max_length_mm=int(cl.get("maxCellLength", 0)),
                max_weight_mg=int(cl.get("maxWeight", 0)),
            )

            # Парсинг рабочих часов
            work_hours = []
            day_order = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
            raw_hours = item.get("workHours", [])
            # Сортируем по порядку дней недели
            raw_hours_sorted = sorted(
                raw_hours, key=lambda wh: day_order.index(wh.get("day", "MON"))
                if wh.get("day") in day_order else 99
            )
            for wh in raw_hours_sorted:
                work_hours.append(WorkHours(
                    day=wh.get("day", ""),
                    opens_at=wh.get("opensAt", ""),
                    closes_at=wh.get("closesAt", ""),
                ))

            point = PickupPoint(
                id=item.get("id", ""),
                name=item.get("name", ""),
                type=item.get("type", ""),
                full_address=item.get("fullAddress", ""),
                city=address.get("city", ""),
                lat=float(address.get("lat", 0)),
                lng=float(address.get("lng", 0)),
                cash_allowed=bool(item.get("cashAllowed", False)),
                card_allowed=bool(item.get("cardAllowed", False)),
                rates=rates,
                cell_limits=cell_limits,
                additional=item.get("additional", ""),
                work_hours=work_hours,
                phone=item.get("phone", ""),
                short_address=item.get("shortAddress", ""),
                partner_name=item.get("partnerName", ""),
                mdm_code=item.get("mdmCode", ""),
            )
            return point

        except (ValueError, TypeError, KeyError) as e:
            logger.warning(f"Ошибка парсинга точки выдачи: {e}")
            return None

    # ======================== Создание заказа ========================

    def create_order(self, order: Order) -> dict:
        """
        Создать заказ в системе 5Post.
        POST /api/v3/orders
        """
        logger.info("=== Создание заказа ===")
        order_data = order.to_api_dict()
        logger.info(f"Номер заказа: {order.sender_order_id}")

        result = self._api_request("POST", "/api/v3/orders", json_data=order_data)

        # Обработка результата
        if isinstance(result, list) and len(result) > 0:
            order_result = result[0]
            if order_result.get("created"):
                logger.info(
                    f"Заказ успешно создан! orderId: {order_result.get('orderId')}, "
                    f"senderOrderId: {order_result.get('senderOrderId')}"
                )
                cargoes = order_result.get("cargoes", [])
                for c in cargoes:
                    logger.info(
                        f"  Грузоместо: cargoId={c.get('cargoId')}, "
                        f"barcode={c.get('barcode')}"
                    )
            else:
                errors = order_result.get("errors", [])
                logger.error(f"Ошибка создания заказа: {errors}")
            return order_result
        else:
            logger.error(f"Неожиданный формат ответа: {result}")
            return {"created": False, "errors": [{"text": f"Неожиданный ответ: {result}"}]}

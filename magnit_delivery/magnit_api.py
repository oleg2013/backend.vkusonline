"""
Клиент API Magnit Post.
Авторизация (OAuth2), склады, ПВЗ, заказы, оценка доставки.
"""

import time
import json
import logging
import requests
from typing import Optional
from geo_utils import safe_headers_for_log, mask_secret

logger = logging.getLogger("magnit_api")


class MagnitAPIError(Exception):
    """Ошибка при работе с API Magnit."""
    def __init__(self, message: str, status_code: int = None, response_body: str = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class MagnitAPI:
    """Клиент для работы с Magnit Post API."""

    def __init__(self, config: dict):
        self.base_url = config["base_url"].rstrip("/")
        self.client_id = config["client_id"]
        self.client_secret = config["client_secret"]
        self.scope = config["scope"]

        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0

        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
        })

    # ── Авторизация ──────────────────────────────────────────────────

    def authenticate(self) -> str:
        """
        Получает OAuth2-токен по client_credentials.
        Кеширует токен и автоматически обновляет при истечении.
        """
        # Если токен ещё действителен — возвращаем кешированный
        if self._access_token and time.time() < self._token_expires_at - 60:
            logger.debug("Используем кешированный токен (истекает через %.0f сек)",
                         self._token_expires_at - time.time())
            return self._access_token

        url = f"{self.base_url}/api/v2/oauth/token"
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": self.scope,
            "grant_type": "client_credentials",
        }

        logger.info("Запрос OAuth-токена: POST %s", url)
        logger.debug("Payload: client_id=%s, scope=%s, grant_type=client_credentials",
                      self.client_id, self.scope)

        start = time.time()
        try:
            resp = self.session.post(
                url,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except requests.RequestException as e:
            logger.error("Ошибка сети при авторизации: %s", e)
            raise MagnitAPIError(f"Ошибка сети при авторизации: {e}")

        elapsed = time.time() - start
        logger.info("Ответ авторизации: %d (%.2f сек)", resp.status_code, elapsed)
        logger.debug("Тело ответа: %s", resp.text[:500])

        if resp.status_code != 200:
            raise MagnitAPIError(
                f"Ошибка авторизации: HTTP {resp.status_code}",
                status_code=resp.status_code,
                response_body=resp.text,
            )

        data = resp.json()
        self._access_token = data.get("access_token")
        expires_in = data.get("expires_in", 3600)
        self._token_expires_at = time.time() + expires_in

        logger.info("Токен получен, действителен %d сек", expires_in)
        return self._access_token

    def _auth_headers(self) -> dict:
        """Возвращает заголовки с Bearer-токеном. Обновляет токен если нужно."""
        token = self.authenticate()
        return {"Authorization": f"Bearer {token}"}

    # ── Общий метод запроса ──────────────────────────────────────────

    def _request(self, method: str, path: str, params: dict = None,
                 json_body: dict = None) -> dict:
        """
        Выполняет HTTP-запрос к API Magnit с логированием.
        """
        url = f"{self.base_url}{path}"
        headers = self._auth_headers()

        # Логируем запрос (маскируем секреты)
        all_headers = {**self.session.headers, **headers}
        logger.info("→ %s %s", method.upper(), url)
        logger.debug("  Params: %s", params)
        if json_body:
            logger.debug("  Body: %s", json.dumps(json_body, ensure_ascii=False, indent=2)[:1000])
        logger.debug("  Headers: %s", safe_headers_for_log(all_headers))

        start = time.time()
        try:
            resp = self.session.request(
                method=method,
                url=url,
                params=params,
                json=json_body,
                headers=headers,
            )
        except requests.RequestException as e:
            logger.error("Ошибка сети: %s %s → %s", method.upper(), url, e)
            raise MagnitAPIError(f"Ошибка сети: {e}")

        elapsed = time.time() - start
        logger.info("← %d %s (%.2f сек)", resp.status_code, url, elapsed)
        logger.debug("  Тело ответа (%d байт): %s", len(resp.content), resp.text[:2000])

        if resp.status_code >= 400:
            error_msg = f"API ошибка: HTTP {resp.status_code} для {method.upper()} {path}"
            logger.error("%s — %s", error_msg, resp.text[:500])
            raise MagnitAPIError(error_msg, resp.status_code, resp.text)

        # Если 204 No Content — возвращаем пустой dict
        if resp.status_code == 204:
            return {}

        return resp.json()

    # ── Склады ───────────────────────────────────────────────────────

    def get_warehouses(self) -> list:
        """
        Получает список складов партнёра.
        GET /api/v1/magnit-post/warehouses
        """
        logger.info("Запрос списка складов...")
        data = self._request("GET", "/api/v1/magnit-post/warehouses")

        # API может вернуть массив напрямую или обёрнутый объект
        if isinstance(data, list):
            warehouses = data
        elif isinstance(data, dict):
            warehouses = data.get("items", data.get("warehouses", [data]))
        else:
            warehouses = []

        logger.info("Получено складов: %d", len(warehouses))
        for wh in warehouses:
            logger.debug("  Склад: %s — %s (%s)",
                         wh.get("warehouse_id", "?"),
                         wh.get("warehouse_name", "?"),
                         wh.get("address", "?"))
        return warehouses

    # ── Пункты выдачи ────────────────────────────────────────────────

    def get_pickup_points(self, city: str = None, region: str = None,
                          page: int = 1, size: int = 1000) -> list:
        """
        Получает список ПВЗ с фильтрацией и пагинацией.
        GET /api/v1/magnit-post/pickup-points
        """
        all_points = []
        current_page = page

        while True:
            params = {"page": current_page, "size": size}
            if city:
                params["city"] = city
            if region:
                params["region"] = region

            logger.info("Запрос ПВЗ: город=%s, страница=%d, размер=%d", city, current_page, size)
            data = self._request("GET", "/api/v1/magnit-post/pickup-points", params=params)

            # Разбираем ответ — может быть массив или объект с пагинацией
            if isinstance(data, list):
                points = data
            elif isinstance(data, dict):
                points = data.get("items", data.get("pickupPoints", data.get("pickup_points", [])))
            else:
                points = []

            all_points.extend(points)
            logger.info("Получено ПВЗ на странице %d: %d", current_page, len(points))

            # Если получили меньше чем size — последняя страница
            if len(points) < size:
                break

            current_page += 1

        logger.info("Всего ПВЗ загружено: %d", len(all_points))
        return all_points

    # ── Оценка доставки ──────────────────────────────────────────────

    def estimate_delivery(self, city_from: str, pickup_point_key: str = None,
                          city_to: str = None, region_to: str = None,
                          parcels_count: int = 1) -> dict:
        """
        Рассчитывает стоимость и сроки доставки.
        POST /api/v2/magnit-post/orders/estimate
        """
        body = {"city_from": city_from}

        if pickup_point_key:
            body["pickup_point_key"] = pickup_point_key
        else:
            if region_to:
                body["region"] = region_to
            if city_to:
                body["city"] = city_to

        if parcels_count > 1:
            body["parcels_count"] = parcels_count

        logger.info("Оценка доставки: из %s, ПВЗ=%s, город=%s",
                     city_from, pickup_point_key, city_to)

        return self._request("POST", "/api/v2/magnit-post/orders/estimate", json_body=body)

    # ── Создание заказа (V2) ─────────────────────────────────────────

    def create_order_v2(self, pickup_point_key: str, warehouse_id: str,
                        customer_order_id: str, recipient: dict,
                        parcels: list, return_type: str = "return",
                        return_warehouse_id: str = None,
                        external_order_id: str = None) -> dict:
        """
        Создаёт заказ на доставку через V2 API.
        POST /api/v2/magnit-post/orders

        Args:
            pickup_point_key: Ключ ПВЗ доставки
            warehouse_id: UUID склада отправления
            customer_order_id: Номер заказа в системе клиента
            recipient: {"phone_number": "+7...", "first_name": "...", "family_name": "..."}
            parcels: [{"declared_value": 1000, "characteristic": {...}, "parcel_payment": {...}}]
            return_type: "return" или "utilization"
            return_warehouse_id: UUID склада возврата (если None — используется warehouse_id)
            external_order_id: Внешний ID заказа (опционально)
        """
        body = {
            "pickup_point": {"key": pickup_point_key},
            "warehouse_id": warehouse_id,
            "customer_order_id": customer_order_id,
            "return_type": return_type,
            "return_warehouse_id": return_warehouse_id or warehouse_id,
            "recipient": recipient,
            "parcels": parcels,
        }

        if external_order_id:
            body["external_order_id"] = external_order_id

        logger.info("Создание заказа: ПВЗ=%s, склад=%s, order_id=%s",
                     pickup_point_key, warehouse_id, customer_order_id)
        logger.debug("Тело заказа: %s", json.dumps(body, ensure_ascii=False, indent=2))

        result = self._request("POST", "/api/v2/magnit-post/orders", json_body=body)

        logger.info("Заказ создан: %s", json.dumps(result, ensure_ascii=False)[:500])
        return result

    # ── Список заказов ──────────────────────────────────────────────

    def get_orders(self, status: str = None, customer_order_id: str = None,
                   external_order_id: str = None,
                   created_from: str = None, created_to: str = None,
                   page: int = 1, size: int = 100,
                   sort_direction: str = "desc") -> dict:
        """
        Получает список заказов с фильтрацией и пагинацией.
        GET /api/v1/magnit-post/orders

        Args:
            status: Фильтр по статусу (NEW, CREATED, DELIVERING_STARTED, ...)
            customer_order_id: Фильтр по номеру заказа клиента
            external_order_id: Фильтр по внешнему ID
            created_from: Дата создания от (RFC3339, напр. 2026-01-01T00:00:00Z)
            created_to: Дата создания до (RFC3339)
            page: Номер страницы (с 1)
            size: Размер страницы (макс 1000)
            sort_direction: "asc" или "desc"

        Returns:
            dict с ключами: items (список заказов), totalCount, page, size и т.д.
        """
        params = {
            "page": page,
            "size": size,
            "sortDirection": sort_direction,
        }

        if status:
            params["status"] = status
        if customer_order_id:
            params["customerOrderId"] = customer_order_id
        if external_order_id:
            params["externalOrderId"] = external_order_id
        if created_from:
            params["createdFrom"] = created_from
        if created_to:
            params["createdTo"] = created_to

        logger.info("Запрос списка заказов: page=%d, size=%d, status=%s",
                     page, size, status or "все")

        return self._request("GET", "/api/v1/magnit-post/orders", params=params)

    # ── Получение информации о заказе ────────────────────────────────

    def get_order(self, order_id: str) -> dict:
        """
        Получает информацию о заказе по UUID.
        GET /api/v2/magnit-post/orders/{order_id}
        """
        return self._request("GET", f"/api/v2/magnit-post/orders/{order_id}")

    # ── Отмена заказа ────────────────────────────────────────────────

    def cancel_order(self, order_id: str) -> dict:
        """
        Отменяет заказ по UUID.
        DELETE /api/v1/magnit-post/orders/{order_id}
        """
        logger.info("Отмена заказа: %s", order_id)
        return self._request("DELETE", f"/api/v1/magnit-post/orders/{order_id}")

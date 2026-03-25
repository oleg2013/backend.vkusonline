from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    app_env: str = "development"
    app_debug: bool = False
    app_secret_key: str = "change-me"
    app_cors_origins: list[str] | None = None  # auto-built from server_name if not set

    # Database
    database_url: str = "postgresql+asyncpg://vkus:vkus_secret@localhost:5432/vkus_online"
    database_echo: bool = False

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # JWT
    jwt_secret_key: str = "change-me-jwt"
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 30
    jwt_algorithm: str = "HS256"

    # Guest sessions
    guest_session_ttl_days: int = 180

    # 5Post
    fivepost_base_url: str = "https://api-omni.x5.ru"
    fivepost_api_key: str = ""
    fivepost_warehouse_id: str = ""
    fivepost_partner_location_id: str = ""
    fivepost_map_version: str = "v1"  # "v1" = client clustering, "v2" = server clustering
    fivepost_map_cluster_detail: int = 4  # grid divisor: higher = more clusters, more detail (1=coarse, 4=like 5Post)
    fivepost_poll_interval_minutes: int = 30  # how often to poll 5Post for status changes
    magnit_poll_interval_minutes: int = 30  # how often to poll Magnit for status changes

    # Magnit
    magnit_base_url: str = "https://b2b-api.magnit.ru"
    magnit_client_id: str = ""
    magnit_client_secret: str = ""
    magnit_warehouse_uuid: str = ""
    magnit_supplier_inn: str = ""
    magnit_supplier_name: str = ""
    magnit_vat_payer: bool = True

    # YooKassa
    yookassa_shop_id: str = ""
    yookassa_secret_key: str = ""
    yookassa_return_url: str = ""  # auto-built from server_name if not set
    yookassa_webhook_secret: str = ""

    # Checkout
    card_payment_discount_percent: float = 5.0
    magnit_flat_delivery_cost_rub: float = 183.0
    free_delivery_threshold_rub: float = 0  # 0 = disabled

    # DaData
    dadata_api_key: str = ""
    dadata_secret_key: str = ""

    # Storage
    storage_type: str = "local"
    storage_local_path: str = "./data/storage"

    # SMTP
    smtp_host: str = "smtp.yandex.ru"
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from_email: str = "shop@coffee-tea.ru"
    smtp_use_tls: bool = True

    # Shop
    server_name: str = "vkus.online"
    shop_name: str = "VKUS Online"
    sale_email: str = ""
    shop_phone: str = "8 (800) 550-73-52"

    # Delivery terms (shown in emails and frontend)
    magnit_delivery_terms: str = "Вы получите СМС с номером заказа и кодом получения.\nПри получении подтверждения личности не требуется.\nПри получении нужно назвать код и номер заказа из СМС.\nЗаказ хранится в ПВЗ 5 дней. Хранение можно продлить на 5 дней через поддержку."
    fivepost_delivery_terms: str = "Вы получите СМС с кодом для получения.\nПри получении подтверждение личности не нужно.\nЕсли у вас нет возможности забрать заказ, его могут получить те, кому вы сообщите код.\nСрок хранения 7 дней, далее можно будет продлить в личном кабинете на два дня бесплатно."

    # Logging
    log_level: str = "INFO"
    log_format: str = "json"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def database_url_sync(self) -> str:
        return self.database_url.replace("+asyncpg", "+psycopg2").replace(
            "postgresql+psycopg2", "postgresql"
        )

    @property
    def site_url(self) -> str:
        """Full site URL derived from server_name."""
        sn = self.server_name
        if sn.startswith("http"):
            return sn.rstrip("/")
        if sn.startswith("localhost") or sn.startswith("127."):
            return f"http://{sn}"
        return f"https://{sn}"

    @property
    def cors_origins(self) -> list[str]:
        """CORS origins: use explicit APP_CORS_ORIGINS if set, otherwise derive from server_name."""
        if self.app_cors_origins is not None:
            return self.app_cors_origins
        origins = ["http://localhost:3000", "http://localhost:5173"]
        url = self.site_url
        if url not in origins:
            origins.append(url)
        return origins

    @property
    def effective_yookassa_return_url(self) -> str:
        """YooKassa return URL: use explicit value if set, otherwise derive from server_name."""
        if self.yookassa_return_url:
            return self.yookassa_return_url
        return f"{self.site_url}/#/orders"


settings = Settings()

"""
Конфигурация для 5Post CLI-утилиты.
Все API-ключи, URL-ы и настройки по умолчанию.
"""

# ===================== API 5Post =====================
FIVEPOST_BASE_URL = "https://api-omni.x5.ru"
FIVEPOST_API_KEY = "f6c7fc81-9d6f-485c-b5c6-72175dfeaeb9"

# ===================== DaData =====================
DADATA_API_KEY = "6edbb2bc2316e22f8c6813515d87a39ae06da954"
DADATA_SECRET_KEY = "41bd3221e238a152db623360c0a4ab6a06d466b1"
DADATA_SUGGEST_URL = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/suggest/address"

# ===================== Yandex Geocoder (резерв) =====================
YANDEX_GEOCODER_KEY = "ca05fe00-c79a-4fe2-812a-11758ed257ba"
YANDEX_GEOCODER_URL = "https://geocode-maps.yandex.ru/1.x/"

# ===================== Настройки по умолчанию =====================
DEFAULT_VAT = 22                    # НДС по умолчанию (%)
DEFAULT_CURRENCY = "RUB"            # Валюта по умолчанию
MIN_PACKAGING_WEIGHT_G = 300        # Минимальный вес упаковки (граммы)
PACKAGING_WEIGHT_PERCENT = 0.20     # Процент веса упаковки от веса товаров
CARGO_WIDTH_MM = 1                  # Ширина грузоместа (мм)
CARGO_HEIGHT_MM = 1                 # Высота грузоместа (мм)
CARGO_LENGTH_MM = 1                 # Длина грузоместа (мм)
NEAREST_POINTS_COUNT = 10           # Количество ближайших точек для показа
OVERWEIGHT_THRESHOLD_KG = 3         # Порог перевеса (кг)

# ===================== Комиссии 5Post =====================
COD_CARD_COMMISSION_PERCENT = 2.5   # Комиссия за перевод картой (%)
COD_CASH_COMMISSION_PERCENT = 1.5   # Комиссия за перевод наличными (%)
INSURANCE_PERCENT = 0.5             # Страховка — приём с объявленной ценности (%)
PICKUP_POINTS_PAGE_SIZE = 1000      # Размер страницы при загрузке точек выдачи
PICKUP_POINTS_REQUEST_DELAY = 0.5   # Задержка между запросами страниц точек (сек.)

# ===================== Кэш точек выдачи =====================
CACHE_DIR = "cache"                           # Директория для кэша
PICKUP_POINTS_CACHE_FILE = "pickup_points.json"  # Файл кэша точек выдачи
PICKUP_POINTS_CACHE_TTL_HOURS = 24            # Время жизни кэша (часы)

# ===================== Логирование =====================
LOG_DIR = "logs"
LOG_FORMAT = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

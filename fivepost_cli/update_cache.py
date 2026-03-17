"""
Обновление кэша пунктов выдачи 5Post.
Отдельный скрипт — запускается независимо от основной программы.
Загружает все точки выдачи из API и сохраняет в cache/pickup_points.json.

Использование:
    python update_cache.py          — обновить кэш (только если устарел)
    python update_cache.py --force  — принудительное обновление
"""

import logging
import os
import sys
from datetime import datetime

import config
from fivepost_api import FivePostAPI


def setup_logging():
    """Настройка логирования."""
    os.makedirs(config.LOG_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(config.LOG_DIR, f"cache_update_{timestamp}.log")

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(config.LOG_FORMAT, config.LOG_DATE_FORMAT))

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))

    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    return log_file


def main():
    log_file = setup_logging()
    force = "--force" in sys.argv

    print("=" * 60)
    print("  Обновление кэша пунктов выдачи 5Post")
    print("=" * 60)
    print(f"  Среда: {config.FIVEPOST_BASE_URL}")
    print(f"  Лог: {log_file}")
    print()

    api = FivePostAPI()

    # Проверяем состояние кэша
    cache_info = api.get_cache_info()

    if cache_info.get("exists"):
        cached_at = cache_info.get("cached_at")
        points_count = cache_info.get("points_count", 0)
        size_mb = cache_info.get("file_size_mb", 0)
        is_expired = cache_info.get("is_expired", True)

        print(f"  Текущий кэш: {points_count} точек, {size_mb:.1f} МБ")
        if cached_at:
            print(f"  Создан: {cached_at.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  Статус: {'УСТАРЕЛ' if is_expired else 'актуален'}")
        print()

        if not is_expired and not force:
            print(f"  Кэш актуален (TTL {config.PICKUP_POINTS_CACHE_TTL_HOURS}ч).")
            print("  Используйте --force для принудительного обновления.")
            return
    else:
        print("  Кэш отсутствует — первая загрузка.")
        print()

    # Подключение к API
    print("Подключение к API 5Post...")
    try:
        api._ensure_token()
        print("  Подключение успешно!")
    except RuntimeError as e:
        print(f"\nОШИБКА: {e}")
        sys.exit(1)

    # Загрузка точек
    print("\nЗагрузка пунктов выдачи из API...")
    print(f"  (лимит: {config.PICKUP_POINTS_PAGE_SIZE} точек/страница, "
          f"задержка: {config.PICKUP_POINTS_REQUEST_DELAY} сек.)")
    print()

    try:
        count = api.update_pickup_points_cache()
    except Exception as e:
        print(f"\nОШИБКА загрузки: {e}")
        logging.exception("Ошибка при обновлении кэша")
        sys.exit(1)

    # Результат
    cache_info = api.get_cache_info()
    print()
    print("=" * 60)
    print(f"  Кэш обновлён: {count} точек")
    if cache_info.get("file_size_mb"):
        print(f"  Размер файла: {cache_info['file_size_mb']:.1f} МБ")
    print(f"  Файл: {os.path.abspath(os.path.join(config.CACHE_DIR, config.PICKUP_POINTS_CACHE_FILE))}")
    print(f"  Следующее обновление через {config.PICKUP_POINTS_CACHE_TTL_HOURS}ч")
    print("=" * 60)


if __name__ == "__main__":
    main()

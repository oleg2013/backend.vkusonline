#!/usr/bin/env python3
"""
VKUS Online — Interactive API Test CLI.

Usage:
    cd backend && python -m scripts.vkus_cli
    python -m scripts.vkus_cli --base-url http://localhost:8000

Features:
    - Interactive menu-driven interface (like the old fivepost_cli / magnit_delivery)
    - Tests ALL API endpoints through our own API (not direct provider calls)
    - Detailed request/response logging to file
    - QA suite for automated full regression
    - Payment testing with local webhook server
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    HAS_RICH = True
except ImportError:
    HAS_RICH = False

# ---------------------------------------------------------------------------
#  Constants
# ---------------------------------------------------------------------------

DEFAULT_BASE_URL = "https://api.vkus.online"
API_PREFIX = "/api/v1"
STATE_FILE = ".vkus_cli_state.json"
LOG_DIR = Path("logs/cli")
DEFAULT_SKU = "701"
WEBHOOK_PORT = 8080
WEBHOOK_TIMEOUT = 300  # 5 min

MENU_CONTEXTS: dict[str, str] = {
    "1": "delivery",
    "2": "orders",
    "3": "payment",
    "4": "auth",
    "5": "admin",
    "6": "qa",
    "7": "settings",
    "8": "subscribers",
    "9": "prices",
}


# ---------------------------------------------------------------------------
#  Simple console helpers (fallback when rich is unavailable)
# ---------------------------------------------------------------------------

if HAS_RICH:
    _console = Console()
else:

    class _FakeConsole:
        def print(self, *args: Any, **kwargs: Any) -> None:
            parts = []
            for a in args:
                parts.append(str(a))
            print(" ".join(parts))

    _console = _FakeConsole()  # type: ignore[assignment]


def cprint(*args: Any, **kw: Any) -> None:
    _console.print(*args, **kw)


def make_table(title: str, columns: list[tuple[str, str]], rows: list[list[str]]) -> None:
    """Print a table.  columns = [(header, justify), ...]."""
    if HAS_RICH:
        t = Table(title=title, show_lines=False, padding=(0, 1))
        for hdr, just in columns:
            t.add_column(hdr, justify=just)  # type: ignore[arg-type]
        for row in rows:
            t.add_row(*row)
        _console.print(t)
    else:
        cprint(f"\n  {title}")
        header_line = " | ".join(h for h, _ in columns)
        cprint(f"  {header_line}")
        cprint(f"  {'-' * len(header_line)}")
        for row in rows:
            cprint(f"  {' | '.join(row)}")


def make_panel(title: str, lines: list[str]) -> None:
    if HAS_RICH:
        body = "\n".join(lines)
        _console.print(Panel(body, title=title, expand=False, border_style="green"))
    else:
        cprint(f"\n  === {title} ===")
        for l in lines:
            cprint(f"  {l}")


# ---------------------------------------------------------------------------
#  State management
# ---------------------------------------------------------------------------


def load_state() -> dict[str, Any]:
    try:
        return json.loads(Path(STATE_FILE).read_text())
    except Exception:
        return {}


def save_state(state: dict[str, Any]) -> None:
    Path(STATE_FILE).write_text(json.dumps(state, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
#  File logger
# ---------------------------------------------------------------------------


class FileLogger:
    """Hierarchical session logger.

    Structure::

        logs/cli/{session_ts}/
            session.log              ← full session (truncated bodies)
            delivery/
                delivery.log         ← per-menu summary (truncated)
                001_{rid8}_{ts}.json ← full request+response (detail mode)
            orders/ ...
    """

    def __init__(self, detail_mode: bool = False) -> None:
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.session_dir = LOG_DIR / ts
        self.session_dir.mkdir(parents=True, exist_ok=True)

        self._detail_mode = detail_mode
        self._context: str | None = None
        self._seq = 0
        self._summary_files: dict[str, Any] = {}  # context → file handle
        self._pending_request: dict[str, Any] = {}

        # Root session log
        self._session_log = open(  # noqa: SIM115
            self.session_dir / "session.log", "a", encoding="utf-8",
        )
        self._write_session(f"=== VKUS CLI session started at {ts} ===")
        self._write_session(f"    detail_server_response: {self._detail_mode}\n")

    # -- properties ----------------------------------------------------------

    @property
    def path(self) -> Path:
        """Session directory (shown in UI)."""
        return self.session_dir

    @property
    def detail_mode(self) -> bool:
        return self._detail_mode

    @detail_mode.setter
    def detail_mode(self, value: bool) -> None:
        self._detail_mode = value
        self.info(f"detail_server_response changed to {value}")

    # -- context switching ---------------------------------------------------

    def set_context(self, context: str) -> None:
        """Activate a menu context.  Creates subfolder + summary log on first use."""
        self._context = context
        if context not in self._summary_files:
            ctx_dir = self.session_dir / context
            ctx_dir.mkdir(exist_ok=True)
            self._summary_files[context] = open(  # noqa: SIM115
                ctx_dir / f"{context}.log", "a", encoding="utf-8",
            )

    def reset_context(self) -> None:
        """Return to main-menu context (no per-menu logging)."""
        self._context = None

    # -- internal helpers ----------------------------------------------------

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _write_session(self, text: str) -> None:
        self._session_log.write(text + "\n")
        self._session_log.flush()

    def _write_summary(self, text: str) -> None:
        if self._context and self._context in self._summary_files:
            f = self._summary_files[self._context]
            f.write(text + "\n")
            f.flush()

    def _write_both(self, text: str) -> None:
        self._write_session(text)
        self._write_summary(text)

    # -- public logging API --------------------------------------------------

    def request(
        self, method: str, url: str, headers: dict[str, str], body: Any,
        params: dict[str, Any] | None = None,
    ) -> None:
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        safe_headers = {
            k: (v[:20] + "..." if k.lower() == "authorization" else v)
            for k, v in headers.items()
        }

        # Build display URL with query params (like httpx would)
        display_url = url
        if params:
            qs = "&".join(f"{k}={v}" for k, v in params.items())
            display_url = f"{url}?{qs}"

        lines = [
            f"[{ts}] {'─' * 50}",
            f"→ {method} {display_url}",
            f"  Headers: {json.dumps(safe_headers, ensure_ascii=False)}",
        ]
        if body:
            lines.append(f"  Body: {json.dumps(body, ensure_ascii=False, default=str)}")
        self._write_both("\n".join(lines))

        # Stash for detail file (will be combined with the response)
        self._pending_request = {
            "method": method,
            "url": display_url,
            "headers": safe_headers,
            "params": params,
            "body": body,
            "timestamp": datetime.now().isoformat(),
        }

    def response(self, status: int, elapsed_ms: int, body: Any, request_id: str | None = None) -> None:
        rid_line = f"  request_id: {request_id}" if request_id else ""

        # --- summary (truncated) ---
        body_str = json.dumps(body, ensure_ascii=False, default=str) if body else ""
        if len(body_str) > 5000:
            body_str = body_str[:5000] + "... (truncated)"
        self._write_both(f"← {status} ({elapsed_ms}ms){rid_line}")
        self._write_both(f"  Body: {body_str}")

        # --- detail JSON file (full, pretty-printed) ---
        if self._detail_mode and self._context:
            seq = self._next_seq()
            rid_short = (request_id or "no-rid")[:8]
            file_ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            filename = f"{seq:03d}_{rid_short}_{file_ts}.json"
            detail_path = self.session_dir / self._context / filename
            detail_data = {
                "seq": seq,
                "request_id": request_id,
                "request": self._pending_request,
                "response": {
                    "status": status,
                    "elapsed_ms": elapsed_ms,
                    "body": body,
                },
            }
            detail_path.write_text(
                json.dumps(detail_data, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )

        self._pending_request = {}

    def info(self, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self._write_both(f"[{ts}] INFO: {msg}")

    def close(self) -> None:
        for f in self._summary_files.values():
            f.close()
        self._session_log.close()


# ---------------------------------------------------------------------------
#  VkusAPI — HTTP client with logging
# ---------------------------------------------------------------------------


class ApiError(Exception):
    def __init__(self, code: str, message: str, status: int, request_id: str = ""):
        self.code = code
        self.message = message
        self.status = status
        self.request_id = request_id
        super().__init__(f"[{code}] {message}")


class VkusAPI:
    def __init__(self, base_url: str, logger: FileLogger) -> None:
        self.base_url = base_url.rstrip("/")
        self.logger = logger
        self.client = httpx.AsyncClient(timeout=30.0)
        self.guest_session_id: str | None = None
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self.admin_secret: str | None = None
        self.last_request_id: str | None = None
        self.last_elapsed_ms: int = 0

    async def call(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        auth: str = "none",
    ) -> Any:
        """Make API call. auth: 'none' | 'guest' | 'user' | 'admin' | 'guest+user'."""
        url = f"{self.base_url}{API_PREFIX}{path}"
        headers: dict[str, str] = {"Content-Type": "application/json"}

        if auth in ("guest", "guest+user"):
            if self.guest_session_id:
                headers["X-Guest-Session-ID"] = self.guest_session_id
        if auth in ("user", "guest+user"):
            if self.access_token:
                headers["Authorization"] = f"Bearer {self.access_token}"
        if auth == "admin":
            if self.admin_secret:
                headers["Authorization"] = f"Bearer {self.admin_secret}"

        self.logger.request(method, url, headers, body, params=params)
        t0 = time.monotonic()

        try:
            resp = await self.client.request(method, url, json=body, params=params, headers=headers)
        except httpx.RequestError as exc:
            self.logger.info(f"NETWORK ERROR: {exc}")
            self.logger.response(0, 0, {"error": str(exc)})
            raise ApiError("NETWORK_ERROR", str(exc), 0)

        elapsed = int((time.monotonic() - t0) * 1000)
        self.last_elapsed_ms = elapsed

        try:
            data = resp.json()
        except Exception:
            self.logger.response(resp.status_code, elapsed, resp.text)
            raise ApiError("PARSE_ERROR", f"HTTP {resp.status_code} — not JSON", resp.status_code)

        request_id = data.get("request_id", "")
        self.last_request_id = request_id
        self.logger.response(resp.status_code, elapsed, data, request_id)

        if not data.get("ok", False):
            err = data.get("error", {})
            raise ApiError(
                err.get("code", "UNKNOWN"),
                err.get("message", f"HTTP {resp.status_code}"),
                resp.status_code,
                request_id,
            )

        return data.get("data")

    async def ensure_guest(self) -> str:
        if not self.guest_session_id:
            self.guest_session_id = str(uuid.uuid4())
        await self.call("POST", "/guest/session/bootstrap", {"guest_session_id": self.guest_session_id})
        return self.guest_session_id

    async def close(self) -> None:
        await self.client.aclose()


# ---------------------------------------------------------------------------
#  Webhook server for payment testing
# ---------------------------------------------------------------------------


async def run_webhook_server(port: int = WEBHOOK_PORT, timeout: int = WEBHOOK_TIMEOUT) -> dict[str, Any] | None:
    """Start a local HTTP server to receive YooKassa webhooks. Returns event payload or None on timeout."""
    from aiohttp import web

    result: dict[str, Any] | None = None
    event_received = asyncio.Event()

    async def handle_webhook(request: web.Request) -> web.Response:
        nonlocal result
        body = await request.json()
        cprint(f"\n  [bold green]Webhook получен![/bold green]" if HAS_RICH else "\n  ✅ Webhook received!")
        cprint(f"  Event: {body.get('event', '?')}")
        result = body
        event_received.set()
        return web.json_response({"status": "ok"})

    app = web.Application()
    app.router.add_post("/webhooks/yookassa", handle_webhook)
    app.router.add_post("/webhook", handle_webhook)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    cprint(f"  Webhook-сервер запущен на http://localhost:{port}/webhooks/yookassa")
    cprint(f"  Ожидание callback (таймаут {timeout}с)...")

    try:
        await asyncio.wait_for(event_received.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        cprint("  [yellow]Таймаут — callback не получен[/yellow]" if HAS_RICH else "  ⚠ Timeout")
    finally:
        await runner.cleanup()

    return result


# ---------------------------------------------------------------------------
#  CLIApp — interactive menu
# ---------------------------------------------------------------------------


class CLIApp:
    def __init__(self, base_url: str) -> None:
        self.state = load_state()
        self.base_url = base_url

        detail = self.state.get("detail_server_response", False)
        self.logger = FileLogger(detail_mode=detail)
        self.api = VkusAPI(base_url, self.logger)

        # Restore state
        self.api.guest_session_id = self.state.get("guest_session_id")
        self.api.access_token = self.state.get("access_token")
        self.api.refresh_token = self.state.get("refresh_token")
        self.api.admin_secret = os.environ.get("VKUS_ADMIN_SECRET", self.state.get("admin_secret", ""))

    def _save(self) -> None:
        self.state["guest_session_id"] = self.api.guest_session_id
        self.state["access_token"] = self.api.access_token
        self.state["refresh_token"] = self.api.refresh_token
        self.state["base_url"] = self.base_url
        self.state["detail_server_response"] = self.logger.detail_mode
        save_state(self.state)

    @staticmethod
    def ask(prompt: str, default: str = "") -> str:
        suffix = f" [{default}]" if default else ""
        val = input(f"  {prompt}{suffix}: ").strip()
        return val or default

    @staticmethod
    def ask_int(prompt: str, default: int = 0) -> int:
        val = input(f"  {prompt} [{default}]: ").strip()
        if not val:
            return default
        try:
            return int(val)
        except ValueError:
            return default

    @staticmethod
    def pause() -> None:
        input("\n  Нажмите Enter для продолжения...")

    def _meta_line(self) -> str:
        parts = []
        if self.api.guest_session_id:
            parts.append(f"guest: {self.api.guest_session_id[:8]}...")
        if self.api.access_token:
            parts.append("user: авторизован")
        parts.append(f"лог: {self.logger.path}")
        return " | ".join(parts)

    def show_menu(self, title: str, items: list[str]) -> str:
        cprint()
        if HAS_RICH:
            lines = [f"  [bold]{title}[/bold]", ""]
            for item in items:
                lines.append(f"  {item}")
            lines.append("")
            lines.append(f"  [dim]{self._meta_line()}[/dim]")
            _console.print(Panel("\n".join(lines), expand=False))
        else:
            cprint(f"  ── {title} ──")
            for item in items:
                cprint(f"  {item}")
            cprint(f"  ({self._meta_line()})")
        return self.ask("Выберите")

    def show_result(self, elapsed: int, request_id: str | None) -> None:
        parts = []
        if request_id:
            parts.append(f"request_id: {request_id}")
        parts.append(f"{elapsed}ms")
        cprint(f"  [dim]{' | '.join(parts)}[/dim]" if HAS_RICH else f"  ({' | '.join(parts)})")

    @staticmethod
    def show_breadcrumb(parts: list[str]) -> None:
        """Print a navigation breadcrumb path at the top of a screen."""
        if HAS_RICH:
            styled = []
            for i, part in enumerate(parts):
                if i == len(parts) - 1:
                    styled.append(f"[bold cyan]{part}[/bold cyan]")
                else:
                    styled.append(f"[yellow]{part}[/yellow]")
            cprint(f"\n  {' > '.join(styled)}")
        else:
            cprint(f"\n  {' > '.join(parts)}")

    # ── MAIN LOOP ──

    async def run(self) -> None:
        cprint()
        if HAS_RICH:
            _console.print(
                Panel(
                    f"[bold]VKUS Online — API Test CLI[/bold]\n{self.base_url}{API_PREFIX}",
                    style="bold cyan",
                    expand=False,
                )
            )
        else:
            cprint(f"  === VKUS Online — API Test CLI ===")
            cprint(f"  {self.base_url}{API_PREFIX}")

        while True:
            choice = self.show_menu(
                "Главное меню",
                [
                    "1. Доставка",
                    "2. Заказы",
                    "3. Оплата",
                    "4. Авторизация",
                    "5. Администрирование",
                    "6. QA — Полный прогон тестов",
                    "7. Настройки",
                    "8. Подписки",
                    "9. Обмен ценами",
                    "0. Выход",
                ],
            )
            if choice in ("0", "q", ""):
                break

            # Set logging context for the selected menu
            context = MENU_CONTEXTS.get(choice)
            if context:
                self.logger.set_context(context)

            try:
                if choice == "1":
                    await self.menu_delivery()
                elif choice == "2":
                    await self.menu_orders()
                elif choice == "3":
                    await self.menu_payment()
                elif choice == "4":
                    await self.menu_auth()
                elif choice == "5":
                    await self.menu_admin()
                elif choice == "6":
                    await self.run_qa()
                elif choice == "7":
                    await self.menu_settings()
                elif choice == "8":
                    await self.menu_subscribers()
                elif choice == "9":
                    await self.menu_prices()
            except ApiError as e:
                cprint(f"\n  [bold red]Ошибка API:[/bold red] [{e.code}] {e.message}" if HAS_RICH else f"\n  ERROR: [{e.code}] {e.message}")
                if e.request_id:
                    cprint(f"  request_id: {e.request_id}")
            except KeyboardInterrupt:
                cprint("\n  Прервано.")
            except Exception as e:
                cprint(f"\n  [bold red]Ошибка:[/bold red] {e}" if HAS_RICH else f"\n  ERROR: {e}")
            finally:
                self.logger.reset_context()

        cprint("  До свидания!")
        self._save()
        await self.api.close()
        self.logger.close()

    # ── DELIVERY ──

    async def menu_delivery(self) -> None:
        while True:
            self.show_breadcrumb(["Доставка"])
            choice = self.show_menu(
                "Доставка",
                [
                    "1. Автокомплит города",
                    "2. Варианты доставки для города",
                    "3. Список ПВЗ (провайдер + город)",
                    "4. Расчёт стоимости для ПВЗ",
                    "5. Города Магнит",
                    "6. Полный сценарий сайта",
                    "0. Назад",
                ],
            )
            if choice in ("0", "q", ""):
                break
            if choice == "1":
                await self._delivery_suggest()
            elif choice == "2":
                await self._delivery_options()
            elif choice == "3":
                await self._delivery_points()
            elif choice == "4":
                await self._delivery_estimate()
            elif choice == "5":
                await self._delivery_cities()
            elif choice == "6":
                await self._delivery_flow()

    async def _delivery_suggest(self) -> list[dict[str, Any]]:
        self.show_breadcrumb(["Доставка", "Автокомплит города"])
        query = self.ask("Введите запрос", "Моск")
        data = await self.api.call("POST", "/geo/city-suggest", {"query": query})
        suggestions = data.get("suggestions", [])
        rows = []
        for i, s in enumerate(suggestions, 1):
            d = s.get("data", {})
            rows.append([
                str(i),
                s.get("value", ""),
                s.get("_clean_name", d.get("city", "")),
                s.get("_geo_lat", d.get("geo_lat", "")),
                s.get("_geo_lon", d.get("geo_lon", "")),
            ])
        make_table(
            f"Подсказки ({len(suggestions)})",
            [("#", "right"), ("Город", "left"), ("clean_name", "left"), ("lat", "right"), ("lon", "right")],
            rows,
        )
        self.show_result(self.api.last_elapsed_ms, self.api.last_request_id)
        return suggestions

    async def _delivery_options(self, city: str | None = None, cart_items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        self.show_breadcrumb(["Доставка", "Варианты доставки"])
        if not city:
            city = self.ask("Город", "Москва")
        if not cart_items:
            sku = self.ask("SKU товара", DEFAULT_SKU)
            qty = self.ask_int("Количество", 1)
            cart_items = [{"sku": sku, "quantity": qty}]

        data = await self.api.call("POST", "/checkout/delivery-options", {"city": city, "cart_items": cart_items})
        providers = data.get("providers", [])
        discount = data.get("card_payment_discount_percent", 0)

        rows = []
        for i, p in enumerate(providers, 1):
            avail = "да" if p.get("available") else "нет"
            rows.append([
                str(i),
                p.get("provider", ""),
                p.get("name", ""),
                avail,
                str(p.get("pickup_points_count", 0)),
                f"{p.get('min_delivery_cost', 0)} руб",
                f"{p.get('estimated_days_min', '?')}-{p.get('estimated_days_max', '?')} дн",
            ])
        make_table(
            f"Доставка в {city} (скидка за карту {discount}%)",
            [("#", "right"), ("ID", "left"), ("Название", "left"), ("Доступен", "center"),
             ("ПВЗ", "right"), ("от Цены", "right"), ("Срок", "right")],
            rows,
        )
        self.show_result(self.api.last_elapsed_ms, self.api.last_request_id)
        return data

    async def _delivery_points(self, provider: str | None = None, city: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        self.show_breadcrumb(["Доставка", "Список ПВЗ"])
        if not provider:
            provider = self.ask("Провайдер (magnit/5post)", "magnit")
        if not city:
            city = self.ask("Город", "Москва")
        if limit is None:
            limit = self.ask_int("Лимит", 20)

        data = await self.api.call("GET", f"/delivery/{provider}/pickup-points", params={"city": city, "limit": limit})
        points = data if isinstance(data, list) else []

        rows = []
        for i, p in enumerate(points, 1):
            rows.append([
                str(i),
                str(p.get("id", "")),
                (p.get("name", "") or "")[:30],
                (p.get("full_address", "") or "")[:35],
                f"{p.get('lat', 0):.4f}",
                f"{p.get('lon', 0):.4f}",
            ])
        make_table(
            f"ПВЗ {provider} в {city} ({len(points)} шт.)",
            [("#", "right"), ("ID", "left"), ("Название", "left"), ("Адрес", "left"), ("lat", "right"), ("lon", "right")],
            rows,
        )
        self.show_result(self.api.last_elapsed_ms, self.api.last_request_id)

        # Detail view
        if points:
            idx = self.ask_int("Детали ПВЗ (номер, 0=пропуск)", 0)
            if 1 <= idx <= len(points):
                pt = points[idx - 1]

                # --- Work schedule formatting ---
                schedule = pt.get("work_schedule") or []
                schedule_lines: list[str] = []
                if schedule:
                    for entry in schedule:
                        day = entry.get("day", "?")
                        opens = entry.get("opens_at", "?")
                        closes = entry.get("closes_at", "?")
                        schedule_lines.append(f"  {day}: {opens} — {closes}")

                lines = [
                    f"ID:          {pt.get('id', '')}",
                    f"Название:    {pt.get('name', '')}",
                    f"Тип:         {pt.get('type', '—')}",
                    f"Город:       {pt.get('city', '')}",
                    f"Адрес:       {pt.get('full_address', '')}",
                    f"Координаты:  {pt.get('lat', 0)}, {pt.get('lon', 0)}",
                    f"Расстояние:  {pt.get('distance_km', 0)} км",
                    f"Наличные:    {'Да' if pt.get('cash_allowed') else 'Нет'}",
                    f"Карта:       {'Да' if pt.get('card_allowed') else 'Нет'}",
                ]

                if schedule_lines:
                    lines.append(f"Расписание:  ({len(schedule)} дн.)")
                    lines.extend(schedule_lines)
                else:
                    lines.append("Расписание:  нет данных")

                make_panel("Детали ПВЗ", lines)

                # --- Raw data from provider ---
                raw = pt.get("raw_data")
                if raw and isinstance(raw, dict):
                    import json as _json
                    raw_text = _json.dumps(raw, ensure_ascii=False, indent=2)
                    # Show truncated if too long
                    if len(raw_text) > 3000:
                        raw_text = raw_text[:3000] + "\n... (обрезано)"
                    make_panel("Raw data (из БД)", [raw_text])
        return points

    async def _delivery_estimate(self, provider: str | None = None, point_id: str | None = None, cart_items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        self.show_breadcrumb(["Доставка", "Расчёт стоимости"])
        if not provider:
            provider = self.ask("Провайдер", "magnit")
        if not point_id:
            point_id = self.ask("ID пункта выдачи")
        if not cart_items:
            sku = self.ask("SKU товара", DEFAULT_SKU)
            cart_items = [{"sku": sku, "quantity": 1}]

        data = await self.api.call("POST", "/checkout/estimate-delivery", {
            "provider": provider,
            "pickup_point_id": point_id,
            "cart_items": cart_items,
        })
        make_panel("Расчёт доставки", [
            f"Провайдер:    {data.get('provider', '')}",
            f"ПВЗ:          {data.get('pickup_point_name', '')}",
            f"Стоимость:    {data.get('delivery_cost', 0)} руб",
            f"Срок:         {data.get('estimated_days_min', '?')}-{data.get('estimated_days_max', '?')} дн",
            f"Наличные:     {'Да' if data.get('cash_allowed') else 'Нет'}",
            f"Карта:        {'Да' if data.get('card_allowed') else 'Нет'}",
        ])
        self.show_result(self.api.last_elapsed_ms, self.api.last_request_id)
        return data

    async def _delivery_cities(self) -> list[dict[str, Any]]:
        self.show_breadcrumb(["Доставка", "Города Магнит"])
        data = await self.api.call("GET", "/delivery/magnit/cities")
        cities = data if isinstance(data, list) else []
        rows = [[str(i), c.get("city", ""), str(c.get("pickup_points_count", 0))] for i, c in enumerate(cities[:50], 1)]
        make_table(f"Города Магнит ({len(cities)} всего, показаны первые 50)", [("#", "right"), ("Город", "left"), ("ПВЗ", "right")], rows)
        self.show_result(self.api.last_elapsed_ms, self.api.last_request_id)
        return cities

    async def _delivery_flow(self) -> dict[str, Any]:
        """Full website scenario: city → provider → PVZ → estimate."""
        self.show_breadcrumb(["Доставка", "Полный сценарий"])
        cprint("\n  === Полный сценарий доставки (как на сайте) ===\n")

        # Step 1: City
        cprint("  [bold]Шаг 1/4: Выбор города[/bold]" if HAS_RICH else "  Шаг 1/4: Выбор города")
        suggestions = await self._delivery_suggest()
        if not suggestions:
            cprint("  Нет подсказок.")
            return {}
        idx = self.ask_int("Выберите город (номер)", 1)
        if idx < 1 or idx > len(suggestions):
            idx = 1
        sel = suggestions[idx - 1]
        city_clean = sel.get("_clean_name", sel.get("data", {}).get("city", sel.get("value", "")))
        cprint(f"  Выбран: {city_clean}\n")

        # Step 2: Provider
        cprint("  [bold]Шаг 2/4: Выбор службы доставки[/bold]" if HAS_RICH else "  Шаг 2/4: Провайдер")
        sku = self.ask("SKU товара", DEFAULT_SKU)
        cart_items = [{"sku": sku, "quantity": 1}]
        opts = await self._delivery_options(city_clean, cart_items)
        providers = opts.get("providers", [])
        available = [p for p in providers if p.get("available")]
        if not available:
            cprint("  Нет доступных провайдеров!")
            return {}
        pidx = self.ask_int("Выберите провайдер (номер)", 1)
        if pidx < 1 or pidx > len(providers):
            pidx = 1
        provider = providers[pidx - 1]
        provider_id = provider.get("provider", "")
        cprint(f"  Выбран: {provider.get('name', provider_id)}\n")

        # Step 3: PVZ
        cprint("  [bold]Шаг 3/4: Выбор ПВЗ[/bold]" if HAS_RICH else "  Шаг 3/4: ПВЗ")
        points = await self._delivery_points(provider_id, city_clean, 20)
        if not points:
            cprint("  Нет пунктов выдачи!")
            return {}
        pvidx = self.ask_int("Выберите ПВЗ (номер)", 1)
        if pvidx < 1 or pvidx > len(points):
            pvidx = 1
        point = points[pvidx - 1]
        cprint(f"  Выбран: {point.get('name', '')} — {point.get('full_address', '')}\n")

        # Step 4: Estimate
        cprint("  [bold]Шаг 4/4: Расчёт стоимости[/bold]" if HAS_RICH else "  Шаг 4/4: Расчёт")
        estimate = await self._delivery_estimate(provider_id, point.get("id", ""), cart_items)

        make_panel("Итог сценария", [
            f"Город:       {city_clean}",
            f"Провайдер:   {provider.get('name', provider_id)}",
            f"ПВЗ:         {point.get('name', '')}",
            f"Адрес:       {point.get('full_address', '')}",
            f"Стоимость:   {estimate.get('delivery_cost', 0)} руб",
            f"Срок:        {estimate.get('estimated_days_min', '?')}-{estimate.get('estimated_days_max', '?')} дн",
        ])
        self.pause()
        return {
            "city": city_clean,
            "provider": provider_id,
            "point": point,
            "estimate": estimate,
            "cart_items": cart_items,
        }

    # ── ORDERS ──

    async def menu_orders(self) -> None:
        while True:
            self.show_breadcrumb(["Заказы"])
            choice = self.show_menu(
                "Заказы",
                [
                    "1. Создать заказ (полный checkout)",
                    "2. Статус заказа",
                    "3. Детали заказа",
                    "4. Отменить заказ",
                    "5. Список заказов (нужен логин)",
                    "0. Назад",
                ],
            )
            if choice in ("0", "q", ""):
                break
            if choice == "1":
                await self._order_create()
            elif choice == "2":
                await self._order_status()
            elif choice == "3":
                await self._order_detail()
            elif choice == "4":
                await self._order_cancel()
            elif choice == "5":
                await self._order_list()

    async def _order_create(self, payment_method: str | None = None) -> dict[str, Any] | None:
        """Full checkout: guest session → delivery flow → customer info → create order."""
        self.show_breadcrumb(["Заказы", "Создание заказа"])
        cprint("\n  === Создание заказа (полный checkout) ===\n")

        # Ensure guest
        await self.api.ensure_guest()
        self._save()
        cprint(f"  Guest session: {self.api.guest_session_id}\n")

        # Delivery flow
        flow = await self._delivery_flow()
        if not flow:
            return None

        # Customer info
        cprint("  [bold]Данные получателя:[/bold]" if HAS_RICH else "  Данные получателя:")
        name = self.ask("Имя", "Тест Тестов")
        phone = self.ask("Телефон", "+79991234567")
        email = self.ask("Email", "test@vkus.online")

        # Payment method
        if payment_method is None:
            pm = self.ask("Способ оплаты (card/cod)", "cod")
            payment_method = pm if pm in ("card", "cod") else "cod"

        point = flow["point"]
        estimate = flow["estimate"]
        cart_items = flow["cart_items"]

        # Confirm
        make_panel("Подтверждение заказа", [
            f"Город:       {flow['city']}",
            f"Провайдер:   {flow['provider']}",
            f"ПВЗ:         {point.get('name', '')}",
            f"Адрес:       {point.get('full_address', '')}",
            f"Доставка:    {estimate.get('delivery_cost', 0)} руб",
            f"Получатель:  {name}, {phone}, {email}",
            f"Оплата:      {payment_method}",
        ])
        confirm = self.ask("Создать заказ? (y/n)", "y")
        if confirm.lower() != "y":
            cprint("  Отменено.")
            return None

        # Create
        data = await self.api.call("POST", "/guest/checkout/create-order", {
            "items": cart_items,
            "delivery_provider": flow["provider"],
            "delivery_city": flow["city"],
            "pickup_point_id": point.get("id", ""),
            "pickup_point_name": point.get("name", ""),
            "delivery_price": estimate.get("delivery_cost", 0),
            "customer_email": email,
            "customer_phone": phone,
            "customer_name": name,
            "payment_method": payment_method,
            "idempotency_key": str(uuid.uuid4()),
        }, auth="guest")

        order_number = data.get("order_number", "")
        self.state["last_order"] = order_number
        self._save()

        make_panel("Заказ создан!", [
            f"Номер:       {order_number}",
            f"Статус:      {data.get('status', '')}",
            f"Сумма:       {data.get('total', '')} руб",
            f"Оплата:      {payment_method}",
        ])
        if data.get("confirmation_url"):
            cprint(f"  Ссылка на оплату: {data['confirmation_url']}")

        self.show_result(self.api.last_elapsed_ms, self.api.last_request_id)
        self.pause()
        return data

    async def _order_status(self) -> None:
        self.show_breadcrumb(["Заказы", "Статус заказа"])
        order = self.ask("Номер заказа", self.state.get("last_order", ""))
        if not order:
            return
        data = await self.api.call("GET", f"/guest/orders/{order}/status", auth="guest")
        make_panel(f"Статус заказа {order}", [
            f"Статус:          {data.get('status', '')}",
            f"Оплата:          {data.get('payment_status', '')}",
            f"Доставка:        {data.get('shipment_status', '')}",
        ])
        self.show_result(self.api.last_elapsed_ms, self.api.last_request_id)

    async def _order_detail(self) -> None:
        self.show_breadcrumb(["Заказы", "Детали заказа"])
        order = self.ask("Номер заказа", self.state.get("last_order", ""))
        if not order:
            return
        data = await self.api.call("GET", f"/guest/orders/{order}", auth="guest")
        lines = [
            f"Номер:       {data.get('order_number', '')}",
            f"Статус:      {data.get('status', '')}",
            f"Клиент:      {data.get('customer_name', '')} | {data.get('customer_email', '')}",
            f"Провайдер:   {data.get('delivery_provider', '')}",
            f"Город:       {data.get('delivery_city', '')}",
            f"ПВЗ:         {data.get('pickup_point_name', '')}",
            f"ПВЗ ID:      {data.get('pickup_point_id', '')}",
            f"Подытог:     {data.get('subtotal', '')} руб",
            f"Скидка:      {data.get('discount_amount', 0)} руб",
            f"Доставка:    {data.get('delivery_price', data.get('customer_delivery_price', ''))} руб",
            f"Итого:       {data.get('total', '')} руб",
            f"Создан:      {data.get('created_at', '')}",
        ]
        items = data.get("items", [])
        if items:
            lines.append("─── Товары ───")
            for it in items:
                lines.append(f"  {it.get('product_sku', '')} × {it.get('quantity', '')} = {it.get('total_price', '')} руб")
        make_panel(f"Заказ {data.get('order_number', order)}", lines)
        self.show_result(self.api.last_elapsed_ms, self.api.last_request_id)

    async def _order_cancel(self) -> None:
        self.show_breadcrumb(["Заказы", "Отмена заказа"])
        order = self.ask("Номер заказа", self.state.get("last_order", ""))
        if not order:
            return
        confirm = self.ask(f"Отменить заказ {order}? (y/n)", "n")
        if confirm.lower() != "y":
            return
        data = await self.api.call("POST", f"/guest/orders/{order}/cancel", auth="guest")
        cprint(f"  Заказ {order}: {data.get('status', 'cancelled')}")
        self.show_result(self.api.last_elapsed_ms, self.api.last_request_id)

    async def _order_list(self) -> None:
        self.show_breadcrumb(["Заказы", "Список заказов"])
        if not self.api.access_token:
            cprint("  Нужна авторизация! Перейдите в меню 4 → Логин.")
            return
        page = self.ask_int("Страница", 1)
        data = await self.api.call("GET", "/me/orders", params={"page": page, "per_page": 10}, auth="user")
        orders = data.get("items", [])
        rows = []
        for o in orders:
            rows.append([
                o.get("order_number", ""),
                o.get("status", ""),
                str(o.get("total", "")),
                o.get("delivery_provider", ""),
                o.get("created_at", "")[:10],
            ])
        make_table(
            f"Заказы (стр. {page}, всего {data.get('total', '?')})",
            [("Номер", "left"), ("Статус", "left"), ("Сумма", "right"), ("Доставка", "left"), ("Дата", "left")],
            rows,
        )
        self.show_result(self.api.last_elapsed_ms, self.api.last_request_id)

    # ── PAYMENT ──

    async def menu_payment(self) -> None:
        while True:
            self.show_breadcrumb(["Оплата"])
            choice = self.show_menu(
                "Оплата",
                [
                    "1. Полный тест (заказ → оплата → webhook)",
                    "2. Создать платёж для заказа",
                    "3. Статус платежа (через статус заказа)",
                    "0. Назад",
                ],
            )
            if choice in ("0", "q", ""):
                break
            if choice == "1":
                await self._payment_full_test()
            elif choice == "2":
                await self._payment_create()
            elif choice == "3":
                await self._order_status()

    async def _payment_create(self, order: str | None = None) -> dict[str, Any] | None:
        self.show_breadcrumb(["Оплата", "Создание платежа"])
        if not order:
            order = self.ask("Номер заказа", self.state.get("last_order", ""))
        if not order:
            return None

        data = await self.api.call(
            "POST",
            f"/guest/orders/{order}/payments/yookassa/create",
            {"idempotency_key": str(uuid.uuid4())},
            auth="guest",
        )
        url = data.get("confirmation_url", "")
        make_panel("Платёж создан", [
            f"Payment ID:  {data.get('payment_id', '')}",
            f"Статус:      {data.get('status', '')}",
            f"URL оплаты:  {url}",
        ])
        self.show_result(self.api.last_elapsed_ms, self.api.last_request_id)

        if url:
            open_browser = self.ask("Открыть в браузере? (y/n)", "y")
            if open_browser.lower() == "y":
                webbrowser.open(url)
        return data

    async def _payment_full_test(self) -> None:
        self.show_breadcrumb(["Оплата", "Полный тест оплаты"])
        cprint("\n  === Полный тест оплаты (E2E) ===\n")

        # Step 1: Create order with card payment
        cprint("  Шаг 1: Создание заказа с оплатой картой...")
        order_data = await self._order_create(payment_method="card")
        if not order_data:
            return

        order_number = order_data.get("order_number", "")

        # Step 2: Create payment (may already be created by create-order)
        confirmation_url = order_data.get("confirmation_url", "")
        if not confirmation_url:
            cprint("  Шаг 2: Создание платежа...")
            pay_data = await self._payment_create(order_number)
            if pay_data:
                confirmation_url = pay_data.get("confirmation_url", "")

        if not confirmation_url:
            cprint("  Нет URL для оплаты!")
            return

        # Step 3: Open browser
        cprint(f"\n  URL оплаты: {confirmation_url}")
        webbrowser.open(confirmation_url)

        # Step 4: Start webhook server
        cprint("\n  Шаг 3: Запуск webhook-сервера...")
        result = await run_webhook_server()

        if result:
            event = result.get("event", "")
            cprint(f"\n  Получено событие: {event}")
            obj = result.get("object", {})
            cprint(f"  Payment ID: {obj.get('id', '')}")
            cprint(f"  Статус: {obj.get('status', '')}")
        else:
            cprint("  Webhook не получен (таймаут)")

        # Step 5: Check order status via API
        cprint("\n  Шаг 4: Проверка статуса заказа через API...")
        await self._order_status()
        self.pause()

    # ── AUTH ──

    async def menu_auth(self) -> None:
        while True:
            self.show_breadcrumb(["Авторизация"])
            status = f"user: {self.api.access_token[:20]}..." if self.api.access_token else "не авторизован"
            choice = self.show_menu(
                f"Авторизация ({status})",
                [
                    "1. Регистрация",
                    "2. Логин",
                    "3. Мой профиль",
                    "4. Выход (logout)",
                    "0. Назад",
                ],
            )
            if choice in ("0", "q", ""):
                break
            if choice == "1":
                await self._auth_register()
            elif choice == "2":
                await self._auth_login()
            elif choice == "3":
                await self._auth_profile()
            elif choice == "4":
                await self._auth_logout()

    async def _auth_register(self, email: str = "", password: str = "", first_name: str = "", last_name: str = "") -> dict[str, Any]:
        self.show_breadcrumb(["Авторизация", "Регистрация"])
        if not email:
            email = self.ask("Email")
        if not password:
            password = self.ask("Пароль (мин. 8 символов)")
        if not first_name:
            first_name = self.ask("Имя", "Тест")
        if not last_name:
            last_name = self.ask("Фамилия", "Тестов")

        data = await self.api.call("POST", "/auth/register", {
            "email": email,
            "password": password,
            "first_name": first_name,
            "last_name": last_name,
        })
        self.api.access_token = data.get("access_token")
        self.api.refresh_token = data.get("refresh_token")
        self._save()
        cprint(f"  Зарегистрирован! Token: {self.api.access_token[:20]}...")
        self.show_result(self.api.last_elapsed_ms, self.api.last_request_id)
        return data

    async def _auth_login(self) -> dict[str, Any]:
        self.show_breadcrumb(["Авторизация", "Вход"])
        email = self.ask("Email")
        password = self.ask("Пароль")
        data = await self.api.call("POST", "/auth/login", {"email": email, "password": password})
        self.api.access_token = data.get("access_token")
        self.api.refresh_token = data.get("refresh_token")
        self._save()
        cprint(f"  Авторизован! Token: {self.api.access_token[:20]}...")
        self.show_result(self.api.last_elapsed_ms, self.api.last_request_id)
        return data

    async def _auth_profile(self) -> None:
        self.show_breadcrumb(["Авторизация", "Профиль"])
        if not self.api.access_token:
            cprint("  Нужна авторизация!")
            return
        data = await self.api.call("GET", "/me", auth="user")
        make_panel("Профиль", [
            f"ID:          {data.get('id', '')}",
            f"Email:       {data.get('email', '')}",
            f"Телефон:     {data.get('phone', '—')}",
            f"Имя:         {data.get('first_name', '')} {data.get('last_name', '')}",
            f"Создан:      {data.get('created_at', '')}",
        ])
        self.show_result(self.api.last_elapsed_ms, self.api.last_request_id)

    async def _auth_logout(self) -> None:
        self.show_breadcrumb(["Авторизация", "Выход"])
        if not self.api.refresh_token:
            cprint("  Нет активной сессии.")
            return
        try:
            await self.api.call("POST", "/auth/logout", {"refresh_token": self.api.refresh_token})
        except ApiError:
            pass
        self.api.access_token = None
        self.api.refresh_token = None
        self._save()
        cprint("  Вы вышли из аккаунта.")

    # ── ADMIN ──

    async def menu_admin(self) -> None:
        if not self.api.admin_secret:
            secret = self.ask("Admin secret (или env VKUS_ADMIN_SECRET)")
            if secret:
                self.api.admin_secret = secret
                self.state["admin_secret"] = secret
                self._save()

        while True:
            self.show_breadcrumb(["Админ"])
            choice = self.show_menu(
                "Администрирование",
                [
                    "1. Детали заказа (admin view)",
                    "2. Статус кэша ПВЗ",
                    "3. Синхронизация 5Post",
                    "4. Синхронизация Магнит",
                    "5. События провайдеров",
                    "6. Список заказов",
                    "7. Управление клиентами",
                    "8. Тест почты",
                    "0. Назад",
                ],
            )
            if choice in ("0", "q", ""):
                break
            if choice == "1":
                order = self.ask("Номер заказа", self.state.get("last_order", ""))
                if order:
                    data = await self.api.call("GET", f"/admin/orders/{order}", auth="admin")
                    cprint(f"  {json.dumps(data, indent=2, ensure_ascii=False)[:3000]}")
                    self.show_result(self.api.last_elapsed_ms, self.api.last_request_id)
            elif choice == "2":
                data = await self.api.call("GET", "/admin/pickup-points/cache-status", auth="admin")
                items = data if isinstance(data, list) else []
                rows = [[c.get("provider", ""), str(c.get("points_count", 0)), c.get("last_synced_at", "")[:19]] for c in items]
                make_table("Кэш ПВЗ", [("Провайдер", "left"), ("Точек", "right"), ("Синхронизировано", "left")], rows)
                self.show_result(self.api.last_elapsed_ms, self.api.last_request_id)
            elif choice == "3":
                data = await self.api.call("POST", "/admin/jobs/sync-5post-points", auth="admin")
                cprint(f"  {data}")
            elif choice == "4":
                data = await self.api.call("POST", "/admin/jobs/sync-magnit-points", auth="admin")
                cprint(f"  {data}")
            elif choice == "5":
                data = await self.api.call("GET", "/admin/provider-events", auth="admin")
                events = data if isinstance(data, list) else []
                for ev in events[:20]:
                    cprint(f"  [{ev.get('created_at', '')[:19]}] {ev.get('provider', '')} | {ev.get('event_type', '')} | {ev.get('order_number', '')}")
                self.show_result(self.api.last_elapsed_ms, self.api.last_request_id)
            elif choice == "6":
                await self.admin_orders_list()
            elif choice == "7":
                await self.admin_clients_list()
            elif choice == "8":
                await self.admin_test_email()

    # ── ADMIN: TEST EMAIL ──

    async def admin_test_email(self) -> None:
        """Send a test email via admin API."""
        self.show_breadcrumb(["Админ", "Тест почты"])
        to = self.ask("Email получателя")
        if not to:
            return
        data = await self.api.call("POST", "/admin/test-email", {"to": to}, auth="admin")
        if data:
            cprint(f"  [green]✓[/green] {data.get('message', 'Queued')}" if HAS_RICH
                   else f"  OK {data.get('message', 'Queued')}")
            cprint(f"  From: {data.get('from', '?')}")
            cprint(f"  SMTP: {data.get('smtp', '?')}")
        self.show_result(self.api.last_elapsed_ms, self.api.last_request_id)

    # ── ADMIN: ORDERS ──

    async def admin_orders_list(self) -> None:
        """Admin order list with pagination, filtering, and order actions."""
        page = 1
        per_page = 15
        status_filter: str | None = None

        while True:
            self.show_breadcrumb(["Админ", "Заказы"])

            params: dict[str, Any] = {"page": page, "per_page": per_page}
            if status_filter:
                params["status"] = status_filter

            try:
                data = await self.api.call("GET", "/admin/orders", params=params, auth="admin")
            except ApiError as e:
                cprint(f"\n  [bold red]Ошибка:[/bold red] {e}" if HAS_RICH else f"\n  ERROR: {e}")
                break

            orders = data.get("orders", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
            total = data.get("total", len(orders)) if isinstance(data, dict) else len(orders)
            total_pages = (total + per_page - 1) // per_page if total else 1

            filter_label = f", фильтр: {status_filter}" if status_filter else ""
            rows = []
            for i, o in enumerate(orders, 1):
                items_count = len(o.get("items", [])) if isinstance(o.get("items"), list) else o.get("items_count", "?")
                total_sum = o.get("total", "")
                created = (o.get("created_at", "") or "")[:16]
                provider = o.get("delivery_provider", "")
                provider_label = {"5post": "5Post", "magnit": "Магнит"}.get(provider, provider)
                rows.append([
                    str(i),
                    str(o.get("order_number", "")),
                    o.get("order_type", o.get("type", "?")),
                    o.get("status_label", o.get("status", "")),
                    provider_label,
                    o.get("customer_name", ""),
                    o.get("customer_email", ""),
                    str(total_sum),
                    str(items_count),
                    created,
                ])
            make_table(
                f"Заказы — стр. {page}/{total_pages} (всего {total}{filter_label})",
                [
                    ("#", "right"), ("Номер", "left"), ("Тип", "left"), ("Статус", "left"),
                    ("Доставка", "left"), ("Клиент", "left"), ("Email", "left"),
                    ("Сумма", "right"), ("Позиций", "right"), ("Дата", "left"),
                ],
                rows,
            )
            self.show_result(self.api.last_elapsed_ms, self.api.last_request_id)

            cprint("  [yellow]N[/yellow]ext  [yellow]P[/yellow]rev  [yellow]F[/yellow]ilter  [yellow]R[/yellow]efresh  [yellow][номер][/yellow]=детали  [yellow]0[/yellow]=назад" if HAS_RICH else "  N-ext  P-rev  F-ilter  R-efresh  [номер]=детали  0=назад")
            choice = self.ask("Действие", "0")

            if choice in ("0", "q", ""):
                break
            elif choice == "r":
                continue  # refresh
            elif choice == "n":
                if page < total_pages:
                    page += 1
            elif choice == "p":
                if page > 1:
                    page -= 1
            elif choice == "f":
                new_filter = self.ask("Статус (pending_payment/paid/pending_confirmation/confirmed_by_client/confirmed/shipped/ready_for_pickup/delivered/cancelled, пусто=сброс)")
                status_filter = new_filter if new_filter else None
                page = 1
            else:
                # Try to select an order by row number
                try:
                    idx = int(choice)
                    if 1 <= idx <= len(orders):
                        order_data = orders[idx - 1]
                        await self._admin_order_detail_actions(order_data)
                        # After returning from detail view, continue to refresh list
                except ValueError:
                    pass

    async def _admin_order_detail_actions(self, order_summary: dict[str, Any]) -> None:
        """Show admin order detail and action menu.

        Returns after user presses "0" or after a mutating action
        (status change, cancel, delete) so the caller can refresh the list.
        """
        order_number = order_summary.get("order_number", "")
        if not order_number:
            cprint("  Нет номера заказа.")
            return

        # Fetch full order details
        try:
            data = await self.api.call("GET", f"/admin/orders/{order_number}", auth="admin")
        except ApiError as e:
            cprint(f"\n  [bold red]Ошибка:[/bold red] {e}" if HAS_RICH else f"\n  ERROR: {e}")
            return

        self.show_breadcrumb(["Админ", "Заказы", order_number])

        token = data.get('public_token', data.get('guest_order_token', ''))
        tracking_url = f"https://vkus.online/#/orders/{token}" if token else ""
        lines = [
            f"Номер:       {data.get('order_number', '')}",
            f"Тип:         {data.get('order_type', '')}",
            f"Статус:      {data.get('status_label', data.get('status', ''))}",
            f"Оплата:      {data.get('payment_method', '')}",
            f"Token:       {token}",
            f"Ссылка:      {tracking_url}",
            f"Клиент:      {data.get('customer_name', '')}",
            f"Email:       {data.get('customer_email', '')}",
            f"Телефон:     {data.get('customer_phone', '')}",
            f"Провайдер:   {data.get('delivery_provider', '')}",
            f"Город:       {data.get('delivery_city', '')}",
            f"ПВЗ:         {data.get('pickup_point_name', '')}",
            f"ПВЗ ID:      {data.get('pickup_point_id', '')}",
            f"Подытог:     {data.get('subtotal', '')} руб",
            f"Доставка:    {data.get('delivery_price', data.get('customer_delivery_price', ''))} руб",
            f"Скидка:      {data.get('discount_amount', 0)} руб",
            f"Итого:       {data.get('total', '')} руб",
            f"Создан:      {data.get('created_at', '')}",
        ]
        items = data.get("items", [])
        if items:
            lines.append("--- Товары ---")
            for it in items:
                name = it.get('product_name', it.get('product_sku', ''))
                sku = it.get('product_sku', '')
                lines.append(f"  {name} [{sku}] x {it.get('quantity', '')} = {it.get('total_price', '')} руб")
        make_panel(f"Заказ {order_number} (admin)", lines)
        self.show_result(self.api.last_elapsed_ms, self.api.last_request_id)

        while True:
            choice = self.show_menu(
                f"Действия с заказом {order_number}",
                [
                    "1. Изменить статус",
                    "2. Отменить заказ",
                    "3. Удалить заказ",
                    "4. Создать отправление (Shipment)",
                    "5. Просмотреть отправление",
                    "0. Назад к списку",
                ],
            )
            if choice in ("0", "q", ""):
                return  # back to list (list loop will refresh)
            elif choice == "1":
                changed = await self._admin_order_set_status(order_number, data.get("status", ""), data.get("allowed_transitions"))
                if changed:
                    return  # back to list with refresh
            elif choice == "4":
                await self._admin_create_shipment(order_number)
            elif choice == "5":
                await self._admin_view_shipment(order_number)
            elif choice == "2":
                confirm = self.ask(f"Отменить заказ {order_number}? (y/n)", "n")
                if confirm.lower() == "y":
                    try:
                        result = await self.api.call("POST", f"/admin/orders/{order_number}/set-status", {"new_status": "cancelled"}, auth="admin")
                        cprint(f"  Заказ {order_number} отменён. Новый статус: {result.get('status', 'cancelled')}")
                        self.show_result(self.api.last_elapsed_ms, self.api.last_request_id)
                    except ApiError as e:
                        cprint(f"  [bold red]Ошибка:[/bold red] {e}" if HAS_RICH else f"  ERROR: {e}")
                return  # back to list with refresh
            elif choice == "3":
                confirm = self.ask(f"УДАЛИТЬ заказ {order_number}? Это необратимо! (yes/no)", "no")
                if confirm.lower() == "yes":
                    try:
                        await self.api.call("DELETE", f"/admin/orders/{order_number}", auth="admin")
                        cprint(f"  Заказ {order_number} удалён.")
                        self.show_result(self.api.last_elapsed_ms, self.api.last_request_id)
                    except ApiError as e:
                        cprint(f"  [bold red]Ошибка:[/bold red] {e}" if HAS_RICH else f"  ERROR: {e}")
                return  # back to list with refresh

    async def _admin_order_set_status(self, order_number: str, current_status: str, allowed_transitions: list[str] | None = None) -> bool:
        """Show allowed status transitions and let user pick a new status.

        Returns True if the status was changed, False otherwise.
        """
        allowed = allowed_transitions or []
        if not allowed:
            cprint(f"  Заказ в статусе '{current_status}' — переходы недоступны.")
            return False

        cprint(f"  Текущий статус: {current_status}")
        cprint(f"  Доступные переходы:")
        for i, s in enumerate(allowed, 1):
            cprint(f"    {i}. {s}")

        choice = self.ask("Новый статус (номер или название)")
        new_status = ""
        try:
            idx = int(choice)
            if 1 <= idx <= len(allowed):
                new_status = allowed[idx - 1]
        except ValueError:
            if choice in allowed:
                new_status = choice

        if not new_status:
            cprint("  Отмена.")
            return False

        try:
            result = await self.api.call("POST", f"/admin/orders/{order_number}/set-status", {"new_status": new_status}, auth="admin")
            cprint(f"  Статус заказа {order_number} изменён: {current_status} -> {result.get('status', new_status)}")
            self.show_result(self.api.last_elapsed_ms, self.api.last_request_id)
            return True
        except ApiError as e:
            cprint(f"  [bold red]Ошибка:[/bold red] {e}" if HAS_RICH else f"  ERROR: {e}")
            return False

    async def _admin_create_shipment(self, order_number: str) -> None:
        """Create a shipment at the delivery provider for an order."""
        confirm = self.ask(f"Создать отправление для заказа {order_number}? (y/n)", "n")
        if confirm.lower() != "y":
            cprint("  Отмена.")
            return

        try:
            result = await self.api.call("POST", f"/admin/orders/{order_number}/create-shipment", auth="admin")
            lines = [
                f"Shipment ID:     {result.get('shipment_id', '')}",
                f"Провайдер:       {result.get('provider', '')}",
                f"Provider ID:     {result.get('provider_shipment_id', '')}",
                f"Provider Order:  {result.get('provider_order_number', '')}",
                f"Статус:          {result.get('status', '')}",
                f"Размер:          {result.get('parcel_size', '')}",
                f"Вес (г):         {result.get('weight_grams', '')}",
            ]
            make_panel("Отправление создано", lines)
            self.show_result(self.api.last_elapsed_ms, self.api.last_request_id)
        except ApiError as e:
            cprint(f"  [bold red]Ошибка:[/bold red] {e}" if HAS_RICH else f"  ERROR: {e}")

    async def _admin_view_shipment(self, order_number: str) -> None:
        """View shipment details for an order."""
        try:
            result = await self.api.call("GET", f"/admin/orders/{order_number}/shipment", auth="admin")
            if result is None:
                cprint("  Отправление не найдено для этого заказа.")
                return
            lines = [
                f"Shipment ID:     {result.get('shipment_id', '')}",
                f"Провайдер:       {result.get('provider', '')}",
                f"Provider ID:     {result.get('provider_shipment_id', '')}",
                f"Provider Order:  {result.get('provider_order_number', '')}",
                f"Статус:          {result.get('status', '')}",
                f"Tracking:        {result.get('tracking_number', '')}",
                f"Размер:          {result.get('parcel_size', '')}",
                f"Вес (г):         {result.get('weight_grams', '')}",
                f"Label URL:       {result.get('label_url', '')}",
                f"Создан:          {result.get('created_at', '')}",
            ]
            make_panel("Отправление", lines)
            self.show_result(self.api.last_elapsed_ms, self.api.last_request_id)
        except ApiError as e:
            cprint(f"  [bold red]Ошибка:[/bold red] {e}" if HAS_RICH else f"  ERROR: {e}")

    # ── ADMIN: CLIENTS ──

    async def admin_clients_list(self) -> None:
        """Admin client list with pagination, search, and client actions."""
        page = 1
        per_page = 15
        search_query: str | None = None

        while True:
            self.show_breadcrumb(["Админ", "Клиенты"])

            params: dict[str, Any] = {"page": page, "per_page": per_page}
            if search_query:
                params["search"] = search_query

            try:
                data = await self.api.call("GET", "/admin/clients", params=params, auth="admin")
            except ApiError as e:
                cprint(f"\n  [bold red]Ошибка:[/bold red] {e}" if HAS_RICH else f"\n  ERROR: {e}")
                break

            clients = data.get("clients", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
            total = data.get("total", len(clients)) if isinstance(data, dict) else len(clients)
            total_pages = (total + per_page - 1) // per_page if total else 1

            search_label = f", поиск: '{search_query}'" if search_query else ""
            rows = []
            for i, c in enumerate(clients, 1):
                has_password = c.get("plain_password") or ("да" if c.get("has_password") else "нет")
                orders_count = c.get("orders_count", c.get("total_orders", "?"))
                total_spent = c.get("total_spent", c.get("orders_sum", "?"))
                created = (c.get("created_at", "") or "")[:10]
                rows.append([
                    str(i),
                    c.get("email", ""),
                    c.get("phone", "") or "",
                    c.get("display_name", c.get("name", c.get("first_name", ""))) or "",
                    has_password,
                    str(orders_count),
                    str(total_spent),
                    created,
                ])
            make_table(
                f"Клиенты — стр. {page}/{total_pages} (всего {total}{search_label})",
                [
                    ("#", "right"), ("Email", "left"), ("Телефон", "left"), ("Имя", "left"),
                    ("Пароль", "center"), ("Заказов", "right"), ("Сумма", "right"), ("Дата рег.", "left"),
                ],
                rows,
            )
            self.show_result(self.api.last_elapsed_ms, self.api.last_request_id)

            cprint("  [yellow]N[/yellow]ext  [yellow]P[/yellow]rev  [yellow]S[/yellow]earch  [yellow]R[/yellow]efresh  [yellow][номер][/yellow]=детали  [yellow]C[/yellow]reate  [yellow]0[/yellow]=назад" if HAS_RICH else "  N-ext  P-rev  S-earch  R-efresh  [номер]=детали  C-reate  0=назад")
            choice = self.ask("Действие", "0")

            if choice in ("0", "q", ""):
                break
            elif choice == "r":
                continue  # refresh
            elif choice == "n":
                if page < total_pages:
                    page += 1
            elif choice == "p":
                if page > 1:
                    page -= 1
            elif choice == "s":
                new_search = self.ask("Поиск (email/телефон/имя, пусто=сброс)")
                search_query = new_search if new_search else None
                page = 1
            elif choice == "c":
                await self._admin_client_create()
            else:
                try:
                    idx = int(choice)
                    if 1 <= idx <= len(clients):
                        client_data = clients[idx - 1]
                        await self._admin_client_detail_actions(client_data)
                        # After returning from detail view, continue to refresh list
                except ValueError:
                    pass

    async def _admin_client_detail_actions(self, client_summary: dict[str, Any]) -> None:
        """Show admin client detail and action menu.

        Returns after user presses "0" or after a mutating action
        (delete) so the caller can refresh the list.
        """
        client_id = client_summary.get("id", "")
        client_email = client_summary.get("email", "")
        if not client_id and not client_email:
            cprint("  Нет данных клиента.")
            return

        self.show_breadcrumb(["Админ", "Клиенты", client_email])

        # Show client info from the summary (or re-fetch if endpoint exists)
        lines = [
            f"ID:          {client_id}",
            f"Email:       {client_email}",
            f"Телефон:     {client_summary.get('phone', '') or '—'}",
            f"Имя:         {client_summary.get('display_name', client_summary.get('name', client_summary.get('first_name', ''))) or '—'}",
            f"Фамилия:     {client_summary.get('last_name', '') or '—'}",
            f"Пароль:      {client_summary.get('plain_password') or ('да' if client_summary.get('has_password') else 'нет')}",
            f"Заказов:     {client_summary.get('orders_count', client_summary.get('total_orders', '?'))}",
            f"Сумма:       {client_summary.get('total_spent', client_summary.get('orders_sum', '?'))} руб",
            f"Создан:      {client_summary.get('created_at', '')}",
        ]
        make_panel(f"Клиент: {client_email}", lines)

        while True:
            choice = self.show_menu(
                f"Действия с клиентом {client_email}",
                [
                    "1. Заказы клиента",
                    "2. Сбросить пароль",
                    "3. Создать клиента",
                    "4. Удалить клиента",
                    "0. Назад к списку",
                ],
            )
            if choice in ("0", "q", ""):
                return  # back to list (list loop will refresh)
            elif choice == "1":
                await self._admin_client_orders(client_id, client_email)
            elif choice == "2":
                await self._admin_client_reset_password(client_id, client_email)
            elif choice == "3":
                await self._admin_client_create()
            elif choice == "4":
                confirm = self.ask(f"УДАЛИТЬ клиента {client_email}? Это необратимо! (yes/no)", "no")
                if confirm.lower() == "yes":
                    try:
                        await self.api.call("DELETE", f"/admin/clients/{client_id}", auth="admin")
                        cprint(f"  Клиент {client_email} удалён.")
                        self.show_result(self.api.last_elapsed_ms, self.api.last_request_id)
                    except ApiError as e:
                        cprint(f"  [bold red]Ошибка:[/bold red] {e}" if HAS_RICH else f"  ERROR: {e}")
                return  # back to list with refresh

    async def _admin_client_orders(self, client_id: str, client_email: str) -> None:
        """Show orders for a specific client."""
        page = 1
        per_page = 15
        while True:
            self.show_breadcrumb(["Админ", "Клиенты", client_email, "Заказы"])

            params: dict[str, Any] = {"page": page, "per_page": per_page, "client_id": client_id}
            try:
                data = await self.api.call("GET", "/admin/orders", params=params, auth="admin")
            except ApiError as e:
                cprint(f"\n  [bold red]Ошибка:[/bold red] {e}" if HAS_RICH else f"\n  ERROR: {e}")
                break

            orders = data.get("orders", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
            total = data.get("total", len(orders)) if isinstance(data, dict) else len(orders)
            total_pages = (total + per_page - 1) // per_page if total else 1

            rows = []
            for i, o in enumerate(orders, 1):
                rows.append([
                    str(i),
                    str(o.get("order_number", "")),
                    o.get("status", ""),
                    str(o.get("total", "")),
                    (o.get("created_at", "") or "")[:16],
                ])
            make_table(
                f"Заказы клиента {client_email} — стр. {page}/{total_pages} (всего {total})",
                [("#", "right"), ("Номер", "left"), ("Статус", "left"), ("Сумма", "right"), ("Дата", "left")],
                rows,
            )
            self.show_result(self.api.last_elapsed_ms, self.api.last_request_id)

            cprint("  [yellow]N[/yellow]ext  [yellow]P[/yellow]rev  [yellow]R[/yellow]efresh  [yellow]0[/yellow]=назад" if HAS_RICH else "  N-ext  P-rev  R-efresh  0=назад")
            choice = self.ask("Действие", "0")
            if choice in ("0", "q", ""):
                break
            elif choice == "r":
                continue  # refresh
            elif choice == "n":
                if page < total_pages:
                    page += 1
            elif choice == "p":
                if page > 1:
                    page -= 1

    async def _admin_client_reset_password(self, client_id: str, client_email: str) -> None:
        """Reset client password via admin API."""
        new_password = self.ask("Новый пароль (мин. 8 символов)")
        if not new_password or len(new_password) < 8:
            cprint("  Пароль должен быть не менее 8 символов. Отмена.")
            return
        confirm = self.ask(f"Сбросить пароль для {client_email}? (y/n)", "n")
        if confirm.lower() != "y":
            return
        try:
            await self.api.call("POST", f"/admin/clients/{client_id}/reset-password", {"password": new_password}, auth="admin")
            cprint(f"  Пароль для {client_email} сброшен.")
            self.show_result(self.api.last_elapsed_ms, self.api.last_request_id)
        except ApiError as e:
            cprint(f"  [bold red]Ошибка:[/bold red] {e}" if HAS_RICH else f"  ERROR: {e}")

    async def _admin_client_create(self) -> None:
        """Create a new client via admin API."""
        cprint("\n  === Создание нового клиента ===\n")
        email = self.ask("Email")
        if not email:
            cprint("  Email обязателен. Отмена.")
            return
        phone = self.ask("Телефон", "")
        first_name = self.ask("Имя", "")
        last_name = self.ask("Фамилия", "")
        password = self.ask("Пароль (пусто = без пароля)", "")

        body: dict[str, Any] = {"email": email}
        if phone:
            body["phone"] = phone
        if first_name:
            body["first_name"] = first_name
        if last_name:
            body["last_name"] = last_name
        if password:
            body["password"] = password

        try:
            data = await self.api.call("POST", "/admin/clients", body, auth="admin")
            cprint(f"  Клиент создан: {data.get('email', email)} (ID: {data.get('id', '?')})")
            self.show_result(self.api.last_elapsed_ms, self.api.last_request_id)
        except ApiError as e:
            cprint(f"  [bold red]Ошибка:[/bold red] {e}" if HAS_RICH else f"  ERROR: {e}")

    # ── SETTINGS ──

    async def menu_settings(self) -> None:
        while True:
            self.show_breadcrumb(["Настройки"])
            detail_str = "ВКЛ" if self.logger.detail_mode else "ВЫКЛ"
            choice = self.show_menu(
                "Настройки",
                [
                    f"  Base URL:          {self.base_url}",
                    f"  Guest ID:          {self.api.guest_session_id or '—'}",
                    f"  User token:        {'да' if self.api.access_token else 'нет'}",
                    f"  Admin secret:      {'да' if self.api.admin_secret else 'нет'}",
                    f"  Лог папка:        {self.logger.path}",
                    f"  Детальные ответы:  {detail_str}",
                    "",
                    "1. Изменить Base URL",
                    "2. Сбросить guest session",
                    "3. Задать admin secret",
                    "4. Детальные ответы сервера (вкл/выкл)",
                    "0. Назад",
                ],
            )
            if choice in ("0", "q", ""):
                break
            if choice == "1":
                new_url = self.ask("Base URL", self.base_url)
                self.base_url = new_url
                self.api.base_url = new_url.rstrip("/")
                self._save()
            elif choice == "2":
                self.api.guest_session_id = None
                self._save()
                cprint("  Guest session сброшен.")
            elif choice == "3":
                secret = self.ask("Admin secret")
                self.api.admin_secret = secret
                self.state["admin_secret"] = secret
                self._save()
            elif choice == "4":
                self.logger.detail_mode = not self.logger.detail_mode
                new_state = "ВКЛ" if self.logger.detail_mode else "ВЫКЛ"
                cprint(f"  Детальные ответы: {new_state}")
                self._save()

    # ── QA SUITE ──

    async def run_qa(self) -> None:
        cprint()
        if HAS_RICH:
            _console.print(Panel("[bold]VKUS Online — QA Suite[/bold]", style="bold cyan", expand=False))
        else:
            cprint("  === VKUS Online — QA Suite ===")

        tests: list[tuple[str, Any]] = [
            ("Health check", self._qa_health),
            ("Bootstrap", self._qa_bootstrap),
            ("Guest session", self._qa_guest),
            ("Catalog: list products", self._qa_catalog_list),
            ("Catalog: product by SKU", self._qa_catalog_by_sku),
            ("Catalog: price check", self._qa_catalog_prices),
            ("City suggest", self._qa_city_suggest),
            ("Delivery options (Москва)", self._qa_delivery_options),
            ("Magnit points (limit=10)", self._qa_magnit_points),
            ("5Post points (limit=10)", self._qa_5post_points),
            ("Magnit points HIGH (limit=2000)", self._qa_magnit_points_high_limit),
            ("5Post points HIGH (limit=2000)", self._qa_5post_points_high_limit),
            ("Estimate delivery", self._qa_estimate),
            ("Checkout quote", self._qa_quote),
            ("Cart (add items)", self._qa_cart),
            ("Create order (COD)", self._qa_create_order),
            ("Checkout: full order flow", self._qa_full_order_flow),
            ("Order status", self._qa_order_status),
            ("Auth register", self._qa_register),
            ("Profile (GET /me)", self._qa_profile),
            ("Admin: list orders", self._qa_admin_list_orders),
            ("Admin: order set status", self._qa_admin_order_status),
            ("Public: order tracking", self._qa_public_tracking),
            ("COD: confirm order", self._qa_cod_confirm),
            ("Admin: list clients", self._qa_admin_list_clients),
        ]

        passed = 0
        failed = 0
        total_time = 0
        qa_state: dict[str, Any] = {}

        for i, (name, fn) in enumerate(tests, 1):
            t0 = time.monotonic()
            try:
                result_msg = await fn(qa_state)
                elapsed = int((time.monotonic() - t0) * 1000)
                total_time += elapsed
                passed += 1
                status = f"[green]OK[/green]" if HAS_RICH else "OK"
                cprint(f"  [{i:2d}/{len(tests)}] {name:.<40s} {status} ({elapsed}ms) {result_msg}")
            except Exception as e:
                elapsed = int((time.monotonic() - t0) * 1000)
                total_time += elapsed
                failed += 1
                err_msg = str(e)[:80]
                status = f"[red]FAIL[/red]" if HAS_RICH else "FAIL"
                cprint(f"  [{i:2d}/{len(tests)}] {name:.<40s} {status} ({elapsed}ms) {err_msg}")

        cprint()
        total = passed + failed
        if failed == 0:
            cprint(f"  РЕЗУЛЬТАТ: {passed}/{total} passed ({total_time}ms)")
        else:
            cprint(f"  РЕЗУЛЬТАТ: {passed}/{total} passed, {failed} failed ({total_time}ms)")
        cprint(f"  Лог: {self.logger.path}")
        self.pause()

    # ── QA individual tests ──

    async def _qa_health(self, st: dict[str, Any]) -> str:
        data = await self.api.call("GET", "/health")
        status = data.get("status", "")
        if status != "healthy":
            raise AssertionError(f"Expected 'healthy', got '{status}'")
        return status

    async def _qa_bootstrap(self, st: dict[str, Any]) -> str:
        data = await self.api.call("GET", "/bootstrap")
        providers = data.get("delivery_providers", [])
        return f"{len(providers)} providers"

    async def _qa_guest(self, st: dict[str, Any]) -> str:
        self.api.guest_session_id = str(uuid.uuid4())
        await self.api.call("POST", "/guest/session/bootstrap", {"guest_session_id": self.api.guest_session_id})
        st["guest_session_id"] = self.api.guest_session_id
        return f"session {self.api.guest_session_id[:8]}..."

    async def _qa_catalog_list(self, st: dict[str, Any]) -> str:
        """Catalog: list products — expect ≥40 items from imported catalog."""
        data = await self.api.call("GET", "/catalog/products")
        products = data if isinstance(data, list) else []
        if len(products) < 40:
            raise AssertionError(f"Expected ≥40 products, got {len(products)}")
        # Check that products have extended fields
        sample = products[0]
        has_type = sample.get("product_type") is not None
        has_images = sample.get("images") is not None
        st["catalog_count"] = len(products)
        return f"{len(products)} products, has_type={has_type}, has_images={has_images}"

    async def _qa_catalog_by_sku(self, st: dict[str, Any]) -> str:
        """Catalog: product by SKU — verify SKU 701 returns correct data."""
        data = await self.api.call("GET", "/catalog/products/701")
        if data.get("sku") != "701":
            raise AssertionError(f"Expected sku='701', got '{data.get('sku')}'")
        if not data.get("is_active"):
            raise AssertionError("Product 701 is not active")
        if not data.get("product_type"):
            raise AssertionError("Product 701 missing product_type")
        if not data.get("images"):
            raise AssertionError("Product 701 missing images")
        return f"sku=701, type={data.get('product_type')}, price={data.get('price')}₽"

    async def _qa_catalog_prices(self, st: dict[str, Any]) -> str:
        """Catalog: price check — verify specific SKU prices match frontend."""
        expected_prices = {"701": 1890, "550075": 736, "550065": 490}
        results = []
        for sku, expected in expected_prices.items():
            data = await self.api.call("GET", f"/catalog/products/{sku}")
            actual = data.get("price")
            if actual != expected:
                raise AssertionError(f"SKU {sku}: expected {expected}₽, got {actual}₽")
            results.append(f"{sku}={actual}₽")
        return ", ".join(results)

    async def _qa_city_suggest(self, st: dict[str, Any]) -> str:
        data = await self.api.call("POST", "/geo/city-suggest", {"query": "Москва"})
        suggestions = data.get("suggestions", [])
        if not suggestions:
            raise AssertionError("No suggestions returned")
        first = suggestions[0]
        st["city_clean"] = first.get("_clean_name", first.get("data", {}).get("city", "Москва"))
        return f"{len(suggestions)} suggestions"

    async def _qa_delivery_options(self, st: dict[str, Any]) -> str:
        city = st.get("city_clean", "Москва")
        cart_items = [{"sku": DEFAULT_SKU, "quantity": 1}]
        st["cart_items"] = cart_items
        data = await self.api.call("POST", "/checkout/delivery-options", {"city": city, "cart_items": cart_items})
        providers = data.get("providers", [])
        parts = []
        for p in providers:
            parts.append(f"{p.get('provider')}: {p.get('pickup_points_count', 0)}pts")
        st["providers"] = providers
        return ", ".join(parts) or "no providers"

    async def _qa_magnit_points(self, st: dict[str, Any]) -> str:
        city = st.get("city_clean", "Москва")
        data = await self.api.call("GET", "/delivery/magnit/pickup-points", params={"city": city, "limit": 10})
        points = data if isinstance(data, list) else []
        if not points:
            raise AssertionError("No points returned")
        with_coords = sum(1 for p in points if p.get("lat") and p.get("lon"))
        st["magnit_point"] = points[0]
        return f"{len(points)} pts, {with_coords} with coords"

    async def _qa_5post_points(self, st: dict[str, Any]) -> str:
        city = st.get("city_clean", "Москва")
        data = await self.api.call("GET", "/delivery/5post/pickup-points", params={"city": city, "limit": 10})
        points = data if isinstance(data, list) else []
        if not points:
            raise AssertionError("No points returned")
        with_coords = sum(1 for p in points if p.get("lat") and p.get("lon"))
        st["fivepost_point"] = points[0]
        return f"{len(points)} pts, {with_coords} with coords"

    async def _qa_magnit_points_high_limit(self, st: dict[str, Any]) -> str:
        """Magnit PVZ — high limit (>200) to verify backend constraint was raised."""
        city = st.get("city_clean", "Москва")
        data = await self.api.call(
            "GET", "/delivery/magnit/pickup-points",
            params={"city": city, "limit": 2000},
        )
        points = data if isinstance(data, list) else []
        if not points:
            raise AssertionError("No points returned")
        if city == "Москва" and len(points) <= 200:
            raise AssertionError(
                f"Expected >200 points for Москва, got {len(points)} — "
                f"backend limit may still be capped at 200"
            )
        with_coords = sum(1 for p in points if p.get("lat") and p.get("lon"))
        return f"{len(points)} pts (limit=2000), {with_coords} with coords"

    async def _qa_5post_points_high_limit(self, st: dict[str, Any]) -> str:
        """5Post PVZ — high limit to verify backend accepts limit>200."""
        city = st.get("city_clean", "Москва")
        data = await self.api.call(
            "GET", "/delivery/5post/pickup-points",
            params={"city": city, "limit": 2000},
        )
        points = data if isinstance(data, list) else []
        if not points:
            raise AssertionError("No points returned")
        with_coords = sum(1 for p in points if p.get("lat") and p.get("lon"))
        return f"{len(points)} pts (limit=2000), {with_coords} with coords"

    async def _qa_estimate(self, st: dict[str, Any]) -> str:
        point = st.get("magnit_point", {})
        cart_items = st.get("cart_items", [{"sku": DEFAULT_SKU, "quantity": 1}])
        data = await self.api.call("POST", "/checkout/estimate-delivery", {
            "provider": "magnit",
            "pickup_point_id": point.get("id", ""),
            "cart_items": cart_items,
        })
        cost = data.get("delivery_cost", 0)
        days = f"{data.get('estimated_days_min', '?')}-{data.get('estimated_days_max', '?')}d"
        st["estimate"] = data
        return f"{cost} rub, {days}"

    async def _qa_quote(self, st: dict[str, Any]) -> str:
        city = st.get("city_clean", "Москва")
        point = st.get("magnit_point", {})
        cart_items = st.get("cart_items", [{"sku": DEFAULT_SKU, "quantity": 1}])
        estimate = st.get("estimate", {})
        data = await self.api.call("POST", "/checkout/quote", {
            "items": cart_items,
            "delivery_provider": "magnit",
            "city": city,
            "pickup_point_id": point.get("id", ""),
            "payment_method": "cod",
            "delivery_price": estimate.get("delivery_cost", 0),
        })
        return f"subtotal={data.get('subtotal', '?')}, total={data.get('total', '?')}"

    async def _qa_cart(self, st: dict[str, Any]) -> str:
        cart_items = st.get("cart_items", [{"sku": DEFAULT_SKU, "quantity": 1}])
        mapped = [{"product_sku": c["sku"], "quantity": c["quantity"]} for c in cart_items]
        data = await self.api.call("PUT", "/guest/cart/items", mapped, auth="guest")
        return f"{data.get('items_count', '?')} items, subtotal={data.get('subtotal', '?')}"

    async def _qa_create_order(self, st: dict[str, Any]) -> str:
        city = st.get("city_clean", "Москва")
        point = st.get("magnit_point", {})
        cart_items = st.get("cart_items", [{"sku": DEFAULT_SKU, "quantity": 1}])
        estimate = st.get("estimate", {})
        ts = int(time.time())
        data = await self.api.call("POST", "/guest/checkout/create-order", {
            "items": cart_items,
            "delivery_provider": "magnit",
            "delivery_city": city,
            "pickup_point_id": point.get("id", ""),
            "pickup_point_name": point.get("name", "QA Test Point"),
            "delivery_price": estimate.get("delivery_cost", 0),
            "customer_email": f"qa-{ts}@test.vkus.online",
            "customer_phone": "+79990001234",
            "customer_name": "QA Тестов",
            "payment_method": "cod",
            "idempotency_key": str(uuid.uuid4()),
        }, auth="guest")
        order_number = data.get("order_number", "")
        public_token = data.get("public_token", data.get("guest_order_token", ""))
        st["order_number"] = order_number
        st["public_token"] = public_token
        self.state["last_order"] = order_number
        return f"{order_number}, {data.get('status', '')}"

    async def _qa_full_order_flow(self, st: dict[str, Any]) -> str:
        """Checkout: full order flow — quote + create-order with real catalog SKU."""
        city = st.get("city_clean", "Москва")
        point = st.get("magnit_point", {})
        # Use two different real products
        cart_items = [{"sku": "701", "quantity": 1}, {"sku": "550075", "quantity": 2}]
        estimate = st.get("estimate", {})

        # Step 1: Quote
        quote = await self.api.call("POST", "/checkout/quote", {
            "items": cart_items,
            "delivery_provider": "magnit",
            "city": city,
            "pickup_point_id": point.get("id", ""),
            "payment_method": "cod",
            "delivery_price": estimate.get("delivery_cost", 0),
        })
        subtotal = quote.get("subtotal", 0)
        if subtotal <= 0:
            raise AssertionError(f"Quote subtotal={subtotal}, expected >0")

        # Step 2: Create order
        ts = int(time.time())
        order = await self.api.call("POST", "/guest/checkout/create-order", {
            "items": cart_items,
            "delivery_provider": "magnit",
            "delivery_city": city,
            "pickup_point_id": point.get("id", ""),
            "pickup_point_name": point.get("name", "QA Full Flow"),
            "delivery_price": estimate.get("delivery_cost", 0),
            "customer_email": f"qa-flow-{ts}@test.vkus.online",
            "customer_phone": "+79990009999",
            "customer_name": "QA FullFlow",
            "payment_method": "cod",
            "idempotency_key": str(uuid.uuid4()),
        }, auth="guest")

        order_number = order.get("order_number", "")
        if not order_number:
            raise AssertionError("No order_number in response")
        return f"quote={subtotal}₽, order={order_number}"

    async def _qa_order_status(self, st: dict[str, Any]) -> str:
        order = st.get("order_number", "")
        if not order:
            raise AssertionError("No order to check")
        data = await self.api.call("GET", f"/guest/orders/{order}/status", auth="guest")
        return data.get("status", "?")

    async def _qa_register(self, st: dict[str, Any]) -> str:
        ts = int(time.time() * 1000)  # ms precision for uniqueness
        email = f"qa-{ts}@test.vkus.online"
        data = await self.api.call("POST", "/auth/register", {
            "email": email,
            "password": "QaTest1234!",
            "first_name": "QA",
            "last_name": "Тестов",
        })
        token = data.get("access_token", "")
        if not token:
            raise AssertionError("No token in response")
        self.api.access_token = token
        self.api.refresh_token = data.get("refresh_token")
        st["qa_email"] = email
        return f"token OK"

    async def _qa_profile(self, st: dict[str, Any]) -> str:
        if not self.api.access_token:
            raise AssertionError("Skipped — no token (register failed)")
        data = await self.api.call("GET", "/me", auth="user")
        email = data.get("email", "")
        expected = st.get("qa_email", "")
        if expected and email != expected:
            raise AssertionError(f"Email mismatch: {email} != {expected}")
        return f"email={email}"

    async def _qa_admin_list_orders(self, st: dict[str, Any]) -> str:
        """Admin: list orders — GET /admin/orders, check response has orders."""
        if not self.api.admin_secret:
            raise AssertionError("Skipped — no admin secret")
        data = await self.api.call("GET", "/admin/orders", params={"page": 1, "per_page": 5}, auth="admin")
        orders = data.get("orders", [])
        total = data.get("total", len(orders))
        if not orders:
            raise AssertionError("No orders returned")
        sample = orders[0]
        if not sample.get("order_number"):
            raise AssertionError("Order missing order_number")
        return f"{total} orders, first={sample.get('order_number')}"

    async def _qa_admin_order_status(self, st: dict[str, Any]) -> str:
        """Admin: order set status — create COD order, then set status to confirmed."""
        if not self.api.admin_secret:
            raise AssertionError("Skipped — no admin secret")
        # Use the order created earlier in QA
        order_number = st.get("order_number", "")
        if not order_number:
            raise AssertionError("No test order available (create_order test must run first)")
        # COD orders go through confirmed_by_client first, then confirmed
        # If the order is in confirmed_by_client, advance to confirmed
        data = await self.api.call(
            "POST", f"/admin/orders/{order_number}/set-status",
            {"new_status": "confirmed"}, auth="admin",
        )
        new_status = data.get("status", "")
        if new_status != "confirmed":
            raise AssertionError(f"Expected status 'confirmed', got '{new_status}'")
        st["confirmed_order"] = order_number
        return f"{order_number} -> confirmed"

    async def _qa_public_tracking(self, st: dict[str, Any]) -> str:
        """Public: order tracking — GET /orders/track/{token}, verify stepper exists."""
        order_number = st.get("order_number", "")
        if not order_number:
            raise AssertionError("No test order available")
        # Use the public_token from order creation
        token = st.get("public_token", "")
        if not token:
            raise AssertionError("No public_token from create_order test")
        data = await self.api.call("GET", f"/orders/track/{token}")
        if not data:
            raise AssertionError("Empty tracking response")
        # Check for stepper/status data
        status = data.get("status", data.get("current_status", ""))
        stepper = data.get("stepper", data.get("steps", data.get("timeline", [])))
        has_stepper = bool(stepper) or bool(status)
        if not has_stepper:
            raise AssertionError("No stepper/status in tracking response")
        return f"status={status}, stepper={'yes' if stepper else 'no'}"

    async def _qa_cod_confirm(self, st: dict[str, Any]) -> str:
        """COD: confirm order — create COD order, POST /orders/{token}/confirm."""
        # Use a fresh COD order
        city = st.get("city_clean", "Москва")
        point = st.get("magnit_point", {})
        cart_items = st.get("cart_items", [{"sku": DEFAULT_SKU, "quantity": 1}])
        estimate = st.get("estimate", {})
        ts = int(time.time())

        order_data = await self.api.call("POST", "/guest/checkout/create-order", {
            "items": cart_items,
            "delivery_provider": "magnit",
            "delivery_city": city,
            "pickup_point_id": point.get("id", ""),
            "pickup_point_name": point.get("name", "QA COD Confirm"),
            "delivery_price": estimate.get("delivery_cost", 0),
            "customer_email": f"qa-cod-{ts}@test.vkus.online",
            "customer_phone": "+79990005555",
            "customer_name": "QA COD",
            "payment_method": "cod",
            "idempotency_key": str(uuid.uuid4()),
        }, auth="guest")

        cod_order = order_data.get("order_number", "")
        token = order_data.get("public_token", order_data.get("guest_order_token", ""))
        if not cod_order or not token:
            raise AssertionError("Failed to create COD order or no public_token")

        # Confirm the COD order via public endpoint
        confirm_data = await self.api.call("POST", f"/orders/{token}/confirm")

        new_status = confirm_data.get("status", "")
        if new_status != "confirmed_by_client":
            raise AssertionError(f"Expected status 'confirmed_by_client', got '{new_status}'")
        return f"{cod_order} -> confirmed_by_client"

    async def _qa_admin_list_clients(self, st: dict[str, Any]) -> str:
        """Admin: list clients — GET /admin/clients, check response."""
        if not self.api.admin_secret:
            raise AssertionError("Skipped — no admin secret")
        data = await self.api.call("GET", "/admin/clients", params={"page": 1, "per_page": 5}, auth="admin")
        clients = data.get("clients", [])
        total = data.get("total", len(clients))
        if not clients:
            raise AssertionError("No clients returned")
        sample = clients[0]
        if not sample.get("email"):
            raise AssertionError("Client missing email field")
        return f"{total} clients, first={sample.get('email')}"

    # ── SUBSCRIBERS MENU ──

    async def menu_subscribers(self) -> None:
        while True:
            self.show_breadcrumb(["Подписки"])
            choice = self.show_menu(
                "Управление подписками",
                [
                    "1. Подписать email",
                    "2. Список подписчиков (БД)",
                    "3. Проверить подписку",
                    "4. Отписать email",
                    "0. Назад",
                ],
            )
            if choice in ("0", "q", ""):
                break
            if choice == "1":
                await self.subscribers_add()
            elif choice == "2":
                await self.subscribers_list()
            elif choice == "3":
                await self.subscribers_check()
            elif choice == "4":
                await self.subscribers_remove()

    async def subscribers_add(self) -> None:
        """Subscribe an email via API."""
        email = self.ask("Email для подписки")
        if not email:
            return
        name = self.ask("Имя (необязательно)", "")
        data = await self.api.call("POST", "/subscribe", body={
            "email": email,
            "name": name or None,
            "source": "cli",
        })
        status = data.get("status", "")
        message = data.get("message", "")
        if status == "subscribed":
            cprint(f"  [bold green]✓ {message}[/bold green]" if HAS_RICH else f"  ✓ {message}")
        elif status == "already_subscribed":
            cprint(f"  [yellow]⚠ {message}[/yellow]" if HAS_RICH else f"  ⚠ {message}")
        elif status == "reactivated":
            cprint(f"  [bold green]✓ {message}[/bold green]" if HAS_RICH else f"  ✓ {message}")
        else:
            cprint(f"  {data}")
        self.show_result(self.api.last_elapsed_ms, self.api.last_request_id)

    async def subscribers_list(self) -> None:
        """List subscribers directly from the database."""
        cprint("  Запрос подписчиков из БД...")
        try:
            import subprocess
            result = subprocess.run(
                ["ssh", "-t", "vkus.com",
                 "docker exec -i vkus-backend-postgres-1 psql -U vkus -d vkus_online -c "
                 "\"SELECT email, is_active, source, created_at::date FROM subscribers ORDER BY created_at DESC LIMIT 50;\""],
                capture_output=True, text=True, timeout=15,
            )
            output = result.stdout.strip()
            if output:
                cprint(f"\n{output}\n")
            else:
                cprint("  (нет данных)")
        except Exception as e:
            cprint(f"  Ошибка: {e}")

    async def subscribers_check(self) -> None:
        """Check if an email is subscribed."""
        email = self.ask("Email для проверки")
        if not email:
            return
        try:
            import subprocess
            result = subprocess.run(
                ["ssh", "-t", "vkus.com",
                 f"docker exec -i vkus-backend-postgres-1 psql -U vkus -d vkus_online -c "
                 f"\"SELECT email, is_active, source, unsubscribe_token, created_at FROM subscribers WHERE email = '{email}';\""],
                capture_output=True, text=True, timeout=15,
            )
            output = result.stdout.strip()
            if output:
                cprint(f"\n{output}\n")
            else:
                cprint("  Подписчик не найден")
        except Exception as e:
            cprint(f"  Ошибка: {e}")

    async def subscribers_remove(self) -> None:
        """Unsubscribe an email by finding its token and calling the API."""
        email = self.ask("Email для отписки")
        if not email:
            return
        try:
            import subprocess
            result = subprocess.run(
                ["ssh", "-t", "vkus.com",
                 f"docker exec -i vkus-backend-postgres-1 psql -U vkus -d vkus_online -t -A -c "
                 f"\"SELECT unsubscribe_token FROM subscribers WHERE email = '{email}' AND is_active = true;\""],
                capture_output=True, text=True, timeout=15,
            )
            token = result.stdout.strip()
            if not token:
                cprint("  Подписчик не найден или уже отписан")
                return
            data = await self.api.call("GET", f"/unsubscribe/{token}")
            cprint(f"  ✓ Отписан: {email}")
            self.show_result(self.api.last_elapsed_ms, self.api.last_request_id)
        except Exception as e:
            cprint(f"  Ошибка: {e}")

    # ── PRICES MENU ──

    async def menu_prices(self) -> None:
        if not self.api.admin_secret:
            secret = self.ask("Admin secret (или env VKUS_ADMIN_SECRET)")
            if secret:
                self.api.admin_secret = secret
                self.state["admin_secret"] = secret
                self._save()

        while True:
            self.show_breadcrumb(["Обмен ценами"])
            choice = self.show_menu(
                "Обмен ценами",
                [
                    "1. Принудительная синхронизация",
                    "2. Журнал сессий",
                    "3. Детали сессии",
                    "4. Цены товара по SKU",
                    "0. Назад",
                ],
            )
            if choice in ("0", "q", ""):
                break
            if choice == "1":
                await self.prices_force_sync()
            elif choice == "2":
                await self.prices_sessions()
            elif choice == "3":
                await self.prices_session_detail()
            elif choice == "4":
                await self.prices_by_sku()

    async def prices_force_sync(self) -> None:
        cprint("  Запуск синхронизации цен с FTP...")
        data = await self.api.call("POST", "/admin/jobs/sync-prices", auth="admin")
        cprint(f"  {data}")
        self.show_result(self.api.last_elapsed_ms, self.api.last_request_id)

    async def prices_sessions(self) -> None:
        data = await self.api.call("GET", "/admin/price-import/sessions", auth="admin")
        sessions = data.get("data", []) if isinstance(data, dict) else data if isinstance(data, list) else []
        if not sessions:
            cprint("  Нет сессий импорта")
            return
        rows = []
        for s in sessions[:20]:
            started = (s.get("started_at") or "")[:19]
            status = s.get("status", "")
            fname = (s.get("file_name") or "")[:30]
            matched = str(s.get("matched", 0))
            updated = str(s.get("updated", 0))
            created = str(s.get("created", 0))
            deleted = str(s.get("deleted", 0))
            sid = (s.get("id") or "")[:8]
            rows.append([sid, started, status, fname, matched, updated, created, deleted])
        make_table("Сессии импорта цен", [
            ("ID", "left"), ("Начало", "left"), ("Статус", "left"), ("Файл", "left"),
            ("Совп.", "right"), ("Обнов.", "right"), ("Созд.", "right"), ("Удал.", "right"),
        ], rows)
        self.show_result(self.api.last_elapsed_ms, self.api.last_request_id)

    async def prices_session_detail(self) -> None:
        sid = self.ask("ID сессии (первые 8 символов)")
        if not sid:
            return
        # Try to find full ID from sessions list
        sessions_data = await self.api.call("GET", "/admin/price-import/sessions", auth="admin")
        sessions = sessions_data.get("data", []) if isinstance(sessions_data, dict) else []
        full_id = None
        for s in sessions:
            if s.get("id", "").startswith(sid):
                full_id = s["id"]
                break
        if not full_id:
            cprint(f"  Сессия {sid} не найдена")
            return
        data = await self.api.call("GET", f"/admin/price-import/sessions/{full_id}", auth="admin")
        detail = data.get("data", data) if isinstance(data, dict) else data
        session_info = detail.get("session", {})
        logs = detail.get("logs", [])
        cprint(f"\n  Сессия: {session_info.get('id', '')[:8]}")
        cprint(f"  Файл: {session_info.get('file_name', '')}")
        cprint(f"  Статус: {session_info.get('status', '')}")
        cprint(f"  Товаров: {session_info.get('total_goods', 0)}, совпадений: {session_info.get('matched', 0)}")
        cprint(f"  Обновлено: {session_info.get('updated', 0)}, создано: {session_info.get('created', 0)}, удалено: {session_info.get('deleted', 0)}")
        if logs:
            rows = []
            for l in logs[:30]:
                rows.append([l.get("sku", ""), l.get("price_type", ""), l.get("action", ""),
                             str(l.get("old_price") or "-"), str(l.get("new_price") or "-")])
            make_table("Журнал изменений", [
                ("SKU", "left"), ("Тип", "left"), ("Действие", "left"),
                ("Старая", "right"), ("Новая", "right"),
            ], rows)
        self.show_result(self.api.last_elapsed_ms, self.api.last_request_id)

    async def prices_by_sku(self) -> None:
        sku = self.ask("SKU товара", self.state.get("default_sku", DEFAULT_SKU))
        if not sku:
            return
        data = await self.api.call("GET", f"/catalog/products/{sku}/prices")
        prices = data.get("prices", []) if isinstance(data, dict) else data if isinstance(data, list) else []
        if not prices:
            cprint(f"  Нет цен для SKU {sku}")
            return
        rows = []
        for p in prices:
            rows.append([p.get("price_type", ""), p.get("price_type_label", ""),
                         str(p.get("price", 0)), f"{p.get('price_rub', 0):.2f} руб",
                         (p.get("updated_at") or "")[:19]])
        make_table(f"Цены товара {sku}", [
            ("Код", "left"), ("Тип", "left"), ("Копейки", "right"),
            ("Рубли", "right"), ("Обновлено", "left"),
        ], rows)
        self.show_result(self.api.last_elapsed_ms, self.api.last_request_id)


# ---------------------------------------------------------------------------
#  Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="VKUS Online — Interactive API Test CLI")
    parser.add_argument("--base-url", default=os.environ.get("VKUS_API_URL", DEFAULT_BASE_URL), help="API base URL")
    args = parser.parse_args()

    app = CLIApp(args.base_url)
    try:
        asyncio.run(app.run())
    except KeyboardInterrupt:
        cprint("\n  Прервано. До свидания!")


if __name__ == "__main__":
    main()

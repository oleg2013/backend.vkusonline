#!/usr/bin/env python3
"""
Delivery Emulator — Interactive CLI.

Manages emulated 5Post & Magnit orders via HTTP API.
Works from any machine — connects to the emulator server.

Usage:
    python cli.py
    python cli.py --url https://5post-emul-api.vkus.online
"""

from __future__ import annotations

import argparse
import sys
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
#  Console helpers
# ---------------------------------------------------------------------------

if HAS_RICH:
    con = Console()
else:
    class _Fake:
        def print(self, *a: Any, **kw: Any) -> None:
            parts = []
            for x in a:
                parts.append(str(x))
            print(" ".join(parts))

        def rule(self, title: str = "", **kw: Any) -> None:
            print(f"\n{'-' * 60}")
            if title:
                print(f"  {title}")
                print(f"{'-' * 60}")

    con = _Fake()  # type: ignore[assignment]


def _input(prompt: str = "> ") -> str:
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return ""


# ---------------------------------------------------------------------------
#  HTTP client
# ---------------------------------------------------------------------------

BASE_URL = "https://5post-emul-api.vkus.online"
client: httpx.Client


def api(method: str, path: str, json: dict | None = None) -> dict | list | None:
    try:
        r = client.request(method, path, json=json, timeout=10)
        if r.status_code == 204:
            return {"ok": True}
        return r.json()
    except Exception as e:
        con.print(f"[red]Error: {e}[/red]" if HAS_RICH else f"Error: {e}")
        return None


# ---------------------------------------------------------------------------
#  Display helpers
# ---------------------------------------------------------------------------

def show_table(title: str, headers: list[str], rows: list[list[str]]) -> None:
    if HAS_RICH:
        t = Table(title=title, show_lines=False, pad_edge=False)
        for h in headers:
            t.add_column(h, style="cyan" if h in ("Status", "ExecStatus", "Статус") else None)
        for row in rows:
            t.add_row(*row)
        con.print(t)
    else:
        print(f"\n  {title}")
        widths = [max(len(h), max((len(r[i]) for r in rows), default=0)) for i, h in enumerate(headers)]
        fmt = "  ".join(f"{{:<{w}}}" for w in widths)
        print("  " + fmt.format(*headers))
        print("  " + "  ".join("-" * w for w in widths))
        for row in rows:
            padded = row + [""] * (len(headers) - len(row))
            print("  " + fmt.format(*padded))


def show_detail(data: dict, title: str) -> None:
    if HAS_RICH:
        lines = []
        for k, v in data.items():
            if k == "history":
                continue
            lines.append(f"[cyan]{k}:[/cyan] {v}")
        con.print(Panel("\n".join(lines), title=title, border_style="green"))
    else:
        print(f"\n  ── {title} ──")
        for k, v in data.items():
            if k == "history":
                continue
            print(f"  {k}: {v}")


def show_lifecycle(data: dict, title: str) -> None:
    if HAS_RICH:
        con.rule(title)
    else:
        print(f"\n{'=' * 50}")
        print(f"  {title}")
        print(f"{'=' * 50}")


# ---------------------------------------------------------------------------
#  5Post menu
# ---------------------------------------------------------------------------

def menu_5post() -> None:
    while True:
        con.print("\n[bold green]=== 5Post ===[/bold green]" if HAS_RICH else "\n=== 5Post ===")
        print("  1. Список заказов")
        print("  2. Детали заказа")
        print("  3. Продвинуть статус (next)")
        print("  4. Продвинуть ВСЕ заказы")
        print("  5. Установить статус")
        print("  6. Ветка «не забрали»")
        print("  7. Lifecycle")
        print("  0. Назад")

        choice = _input("\n5Post > ")
        if choice == "0" or not choice:
            return

        if choice == "1":
            data = api("GET", "/admin/5post/orders")
            if not data or not isinstance(data, list):
                con.print("  Нет заказов." if not data else f"  {data}")
                continue
            rows = [
                [str(o["db_id"]), o["order_id"][:8] + "..", o["sender_order_id"],
                 o["status"], o["execution_status"], o["mile_type"] or "-",
                 o["created_at"][:16]]
                for o in data
            ]
            show_table("5Post Orders", ["#", "OrderID", "SenderOrderID", "Status", "ExecStatus", "Mile", "Created"], rows)

        elif choice == "2":
            oid = _input("  Order # (db_id): ")
            if not oid.isdigit():
                continue
            data = api("GET", f"/admin/5post/orders/{oid}")
            if not data or "error" in data:
                con.print(f"  {data}")
                continue
            show_detail(data, f"5Post Order #{oid}")
            history = data.get("history", [])
            if history:
                rows = [[h["status"], h["execution_status"], h["mile_type"] or "-", h["change_date"][:19], h.get("error_desc") or ""]
                        for h in history]
                show_table("История статусов", ["Status", "ExecStatus", "Mile", "Date", "Error"], rows)

        elif choice == "3":
            oid = _input("  Order # (db_id): ")
            if not oid.isdigit():
                continue
            data = api("POST", f"/admin/5post/orders/{oid}/advance")
            if data and data.get("ok"):
                con.print(f"  [green]OK[/green] {data['old']} → {data['new']} ({data.get('mile_type') or '-'})" if HAS_RICH
                          else f"  OK {data['old']} → {data['new']} ({data.get('mile_type') or '-'})")
            else:
                con.print(f"  {data}")

        elif choice == "4":
            data = api("POST", "/admin/5post/advance-all")
            if data and data.get("ok"):
                con.print(f"  [green]OK[/green] Продвинуто {data['advanced']} из {data['total_active']} активных" if HAS_RICH
                          else f"  OK Продвинуто {data['advanced']} из {data['total_active']} активных")
            else:
                con.print(f"  {data}")

        elif choice == "5":
            oid = _input("  Order # (db_id): ")
            if not oid.isdigit():
                continue
            status = _input("  Status (NEW/APPROVED/IN_PROCESS/DONE/CANCELLED/REJECTED): ").upper()
            exec_st = _input("  Execution status (CREATED/APPROVED/PLACED_IN_POSTAMAT/PICKED_UP/...): ").upper()
            mile = _input("  Mile type (FIRST_MILE/LAST_MILE/... или пусто): ").upper() or None
            data = api("POST", f"/admin/5post/orders/{oid}/set-status",
                       {"status": status, "execution_status": exec_st, "mile_type": mile})
            if data and data.get("ok"):
                con.print(f"  [green]OK[/green] {data['old']} → {data['new']}" if HAS_RICH
                          else f"  OK {data['old']} → {data['new']}")
            else:
                con.print(f"  {data}")

        elif choice == "6":
            oid = _input("  Order # (db_id): ")
            if not oid.isdigit():
                continue
            data = api("POST", f"/admin/5post/orders/{oid}/advance-unclaimed")
            if data and data.get("ok"):
                con.print(f"  [green]OK[/green] {data['old']} → {data['new']} (UNCLAIMED)" if HAS_RICH
                          else f"  OK {data['old']} → {data['new']} (UNCLAIMED)")
            else:
                con.print(f"  {data}")

        elif choice == "7":
            data = api("GET", "/admin/5post/lifecycle")
            if not data:
                continue
            show_lifecycle(data, "5Post Lifecycle")
            print("\n  Happy path:")
            for s in data.get("happy_path", []):
                print(f"    {s['step']:2d}. {s['status']}/{s['execution_status']} ({s['mile_type'] or '-'})")
            print("\n  Unclaimed branch (от PLACED_IN_POSTAMAT):")
            for s in data.get("unclaimed_branch", []):
                print(f"    U{s['step']}. {s['status']}/{s['execution_status']} ({s['mile_type'] or '-'})")


# ---------------------------------------------------------------------------
#  Magnit menu
# ---------------------------------------------------------------------------

def menu_magnit() -> None:
    while True:
        con.print("\n[bold blue]=== Magnit ===[/bold blue]" if HAS_RICH else "\n=== Magnit ===")
        print("  1. Список заказов")
        print("  2. Детали заказа")
        print("  3. Продвинуть статус (next)")
        print("  4. Продвинуть ВСЕ заказы")
        print("  5. Установить статус")
        print("  6. Ветка «возврат»")
        print("  7. Lifecycle")
        print("  0. Назад")

        choice = _input("\nMagnit > ")
        if choice == "0" or not choice:
            return

        if choice == "1":
            data = api("GET", "/admin/magnit/orders")
            if not data or not isinstance(data, list):
                con.print("  Нет заказов." if not data else f"  {data}")
                continue
            rows = [
                [str(o["db_id"]), o["tracking_number"][:8] + "..", o["customer_order_id"],
                 o["recipient_name"] or "-", o["status"], o["created_at"][:16]]
                for o in data
            ]
            show_table("Magnit Orders", ["#", "Tracking", "CustomerOrderID", "Recipient", "Статус", "Created"], rows)

        elif choice == "2":
            oid = _input("  Order # (db_id): ")
            if not oid.isdigit():
                continue
            data = api("GET", f"/admin/magnit/orders/{oid}")
            if not data or "error" in data:
                con.print(f"  {data}")
                continue
            show_detail(data, f"Magnit Order #{oid}")
            history = data.get("history", [])
            if history:
                rows = [[h["status"], h["timestamp"][:19]] for h in history]
                show_table("История статусов", ["Статус", "Timestamp"], rows)

        elif choice == "3":
            oid = _input("  Order # (db_id): ")
            if not oid.isdigit():
                continue
            data = api("POST", f"/admin/magnit/orders/{oid}/advance")
            if data and data.get("ok"):
                con.print(f"  [green]OK[/green] {data['old']} → {data['new']}" if HAS_RICH
                          else f"  OK {data['old']} → {data['new']}")
            else:
                con.print(f"  {data}")

        elif choice == "4":
            data = api("POST", "/admin/magnit/advance-all")
            if data and data.get("ok"):
                con.print(f"  [green]OK[/green] Продвинуто {data['advanced']} из {data['total_active']} активных" if HAS_RICH
                          else f"  OK Продвинуто {data['advanced']} из {data['total_active']} активных")
            else:
                con.print(f"  {data}")

        elif choice == "5":
            oid = _input("  Order # (db_id): ")
            if not oid.isdigit():
                continue
            status = _input("  Status (NEW/CREATED/DELIVERING_STARTED/ACCEPTED_AT_POINT/ISSUED/...): ").upper()
            data = api("POST", f"/admin/magnit/orders/{oid}/set-status", {"status": status})
            if data and data.get("ok"):
                con.print(f"  [green]OK[/green] {data['old']} → {data['new']}" if HAS_RICH
                          else f"  OK {data['old']} → {data['new']}")
            else:
                con.print(f"  {data}")

        elif choice == "6":
            oid = _input("  Order # (db_id): ")
            if not oid.isdigit():
                continue
            data = api("POST", f"/admin/magnit/orders/{oid}/advance-return")
            if data and data.get("ok"):
                con.print(f"  [green]OK[/green] {data['old']} → {data['new']} (RETURN)" if HAS_RICH
                          else f"  OK {data['old']} → {data['new']} (RETURN)")
            else:
                con.print(f"  {data}")

        elif choice == "7":
            data = api("GET", "/admin/magnit/lifecycle")
            if not data:
                continue
            show_lifecycle(data, "Magnit Lifecycle")
            print("\n  Happy path:")
            for i, s in enumerate(data.get("happy_path", []), 1):
                print(f"    {i}. {s}")
            print("\n  Return branch (от ACCEPTED_AT_POINT):")
            for i, s in enumerate(data.get("return_branch", []), 1):
                print(f"    R{i}. {s}")


# ---------------------------------------------------------------------------
#  Main menu
# ---------------------------------------------------------------------------

def main_menu() -> None:
    stats = api("GET", "/admin/stats")
    fp_count = stats.get("fivepost_orders", 0) if stats else "?"
    mg_count = stats.get("magnit_orders", 0) if stats else "?"

    if HAS_RICH:
        con.print(Panel(
            f"[bold]Delivery Emulator CLI[/bold]\n"
            f"Server: [cyan]{BASE_URL}[/cyan]\n"
            f"5Post: [green]{fp_count}[/green] orders  |  Magnit: [blue]{mg_count}[/blue] orders",
            border_style="bright_white",
        ))
    else:
        print(f"\n{'=' * 50}")
        print(f"  Delivery Emulator CLI")
        print(f"  Server: {BASE_URL}")
        print(f"  5Post: {fp_count} orders  |  Magnit: {mg_count} orders")
        print(f"{'=' * 50}")

    while True:
        print("\n  1. 5Post")
        print("  2. Magnit")
        print("  3. Статистика")
        print("  0. Выход")

        choice = _input("\n> ")
        if choice == "0" or not choice:
            print("  Bye!")
            break
        elif choice == "1":
            menu_5post()
        elif choice == "2":
            menu_magnit()
        elif choice == "3":
            stats = api("GET", "/admin/stats")
            if stats:
                con.print(f"  5Post: {stats['fivepost_orders']} заказов")
                con.print(f"  Magnit: {stats['magnit_orders']} заказов")


# ---------------------------------------------------------------------------
#  Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    global BASE_URL, client

    parser = argparse.ArgumentParser(description="Delivery Emulator CLI")
    parser.add_argument("--url", default="https://5post-emul-api.vkus.online",
                        help="Emulator base URL (default: https://5post-emul-api.vkus.online)")
    args = parser.parse_args()

    BASE_URL = args.url.rstrip("/")
    client = httpx.Client(base_url=BASE_URL, timeout=10)

    # Check connectivity
    try:
        r = client.get("/health")
        if r.status_code != 200:
            print(f"Error: emulator not responding at {BASE_URL}")
            sys.exit(1)
    except Exception as e:
        print(f"Error: cannot connect to {BASE_URL}: {e}")
        sys.exit(1)

    try:
        main_menu()
    except KeyboardInterrupt:
        print("\n  Bye!")
    finally:
        client.close()


if __name__ == "__main__":
    main()

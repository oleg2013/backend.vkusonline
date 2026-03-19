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


def breadcrumb(parts: list[str]) -> None:
    """Print a navigation breadcrumb path."""
    if HAS_RICH:
        styled = []
        for i, part in enumerate(parts):
            if i == len(parts) - 1:
                styled.append(f"[bold cyan]{part}[/bold cyan]")
            else:
                styled.append(f"[yellow]{part}[/yellow]")
        con.print(f"\n  {' > '.join(styled)}")
    else:
        print(f"\n  {' > '.join(parts)}")


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
            t.add_column(h, style="cyan" if h in ("Status", "ExecStatus") else None)
        for row in rows:
            t.add_row(*row)
        con.print(t)
    else:
        print(f"\n  {title}")
        if not rows:
            print("  (no data)")
            return
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
        print(f"\n  -- {title} --")
        for k, v in data.items():
            if k == "history":
                continue
            print(f"  {k}: {v}")


def show_result(data: Any) -> None:
    if data and isinstance(data, dict) and data.get("ok"):
        old = data.get("old", "")
        new = data.get("new", "")
        mile = data.get("mile_type") or ""
        suffix = f" ({mile})" if mile else ""
        con.print(f"  [green]OK[/green] {old} -> {new}{suffix}" if HAS_RICH
                  else f"  OK {old} -> {new}{suffix}")
    else:
        con.print(f"  {data}")


# ---------------------------------------------------------------------------
#  5Post menu
# ---------------------------------------------------------------------------

def menu_5post() -> None:
    while True:
        breadcrumb(["5Post"])
        print("  1. Список заказов")
        print("  2. Детали заказа")
        print("  3. Продвинуть статус (next)")
        print("  4. Продвинуть ВСЕ заказы")
        print("  5. Установить статус")
        print("  6. Ветка <<не забрали>>")
        print("  7. Lifecycle")
        print("  0. Назад")

        choice = _input("\n5Post > ")
        if choice == "0" or not choice:
            return

        if choice == "1":
            fivepost_orders_list()
        elif choice == "2":
            breadcrumb(["5Post", "Детали заказа"])
            oid = _input("  Order # (db_id): ")
            if oid.isdigit():
                fivepost_order_detail(int(oid))
        elif choice == "3":
            breadcrumb(["5Post", "Продвинуть статус"])
            oid = _input("  Order # (db_id): ")
            if oid.isdigit():
                show_result(api("POST", f"/admin/5post/orders/{oid}/advance"))
        elif choice == "4":
            breadcrumb(["5Post", "Продвинуть ВСЕ"])
            data = api("POST", "/admin/5post/advance-all")
            if data and data.get("ok"):
                con.print(f"  [green]OK[/green] Продвинуто {data['advanced']} из {data['total_active']} активных" if HAS_RICH
                          else f"  OK Продвинуто {data['advanced']} из {data['total_active']} активных")
            else:
                con.print(f"  {data}")
        elif choice == "5":
            breadcrumb(["5Post", "Установить статус"])
            oid = _input("  Order # (db_id): ")
            if oid.isdigit():
                status = _input("  Status (NEW/APPROVED/IN_PROCESS/DONE/CANCELLED/REJECTED): ").upper()
                exec_st = _input("  Execution status (CREATED/APPROVED/PLACED_IN_POSTAMAT/PICKED_UP/...): ").upper()
                mile = _input("  Mile type (FIRST_MILE/LAST_MILE/... или пусто): ").upper() or None
                show_result(api("POST", f"/admin/5post/orders/{oid}/set-status",
                                {"status": status, "execution_status": exec_st, "mile_type": mile}))
        elif choice == "6":
            breadcrumb(["5Post", "Ветка <<не забрали>>"])
            oid = _input("  Order # (db_id): ")
            if oid.isdigit():
                show_result(api("POST", f"/admin/5post/orders/{oid}/advance-unclaimed"))
        elif choice == "7":
            breadcrumb(["5Post", "Lifecycle"])
            data = api("GET", "/admin/5post/lifecycle")
            if data:
                print("\n  Happy path:")
                for s in data.get("happy_path", []):
                    print(f"    {s['step']:2d}. {s['status']}/{s['execution_status']} ({s['mile_type'] or '-'})")
                print("\n  Unclaimed branch (от PLACED_IN_POSTAMAT):")
                for s in data.get("unclaimed_branch", []):
                    print(f"    U{s['step']}. {s['status']}/{s['execution_status']} ({s['mile_type'] or '-'})")


def fivepost_orders_list() -> None:
    """5Post orders list with select-by-number."""
    while True:
        breadcrumb(["5Post", "Заказы"])
        data = api("GET", "/admin/5post/orders")
        if not data or not isinstance(data, list):
            con.print("  Нет заказов." if not data else f"  {data}")
            return

        orders = data
        rows = [
            [str(i + 1), str(o["db_id"]), o["sender_order_id"],
             o["status"], o["execution_status"], o["mile_type"] or "-",
             o["created_at"][:16]]
            for i, o in enumerate(orders)
        ]
        show_table(f"5Post Orders ({len(orders)})",
                   ["#", "DB ID", "SenderOrderID", "Status", "ExecStatus", "Mile", "Created"], rows)

        print()
        con.print("  [yellow][номер][/yellow]=детали+действия  [yellow]R[/yellow]efresh  [yellow]0[/yellow]=назад" if HAS_RICH
                  else "  [номер]=детали+действия  R-efresh  0=назад")
        choice = _input("  > ")
        if choice in ("0", "q", ""):
            return
        if choice == "r":
            continue  # refresh
        try:
            idx = int(choice)
            if 1 <= idx <= len(orders):
                fivepost_order_actions(orders[idx - 1])
        except ValueError:
            pass


def fivepost_order_detail(db_id: int) -> None:
    """Show 5Post order details + history."""
    data = api("GET", f"/admin/5post/orders/{db_id}")
    if not data or "error" in data:
        con.print(f"  {data}")
        return
    show_detail(data, f"5Post Order #{db_id}")
    history = data.get("history", [])
    if history:
        rows = [[h["status"], h["execution_status"], h["mile_type"] or "-", h["change_date"][:19], h.get("error_desc") or ""]
                for h in history]
        show_table("История статусов", ["Status", "ExecStatus", "Mile", "Date", "Error"], rows)


def fivepost_order_actions(order: dict) -> None:
    """Detail view + action menu for a 5Post order. Returns to list after action."""
    db_id = order["db_id"]
    sender = order["sender_order_id"]

    breadcrumb(["5Post", "Заказы", sender])
    detail = api("GET", f"/admin/5post/orders/{db_id}")
    if not detail or "error" in detail:
        con.print(f"  {detail}")
        return

    show_detail(detail, f"5Post Order #{db_id}")
    history = detail.get("history", [])
    if history:
        rows = [[h["status"], h["execution_status"], h["mile_type"] or "-", h["change_date"][:19], h.get("error_desc") or ""]
                for h in history]
        show_table("История статусов", ["Status", "ExecStatus", "Mile", "Date", "Error"], rows)

    # Show available transitions
    transitions = detail.get("available_transitions", [])
    print()
    if transitions:
        con.print("  [bold]Доступные переходы:[/bold]" if HAS_RICH else "  Доступные переходы:")
        for i, t in enumerate(transitions, 1):
            con.print(f"    [green]{i}[/green]. {t['label']}  [dim]({t['action']})[/dim]" if HAS_RICH
                      else f"    {i}. {t['label']}  ({t['action']})")
    else:
        con.print("  [dim]Нет доступных переходов (терминальный статус)[/dim]" if HAS_RICH
                  else "  Нет доступных переходов (терминальный статус)")

    print()
    print("  S. Установить произвольный статус")
    print("  0. Назад к списку")

    choice = _input(f"  {sender} > ")
    if choice in ("0", "q", ""):
        return

    if choice.lower() == "s":
        status = _input("  Status: ").upper()
        exec_st = _input("  Execution status: ").upper()
        mile = _input("  Mile type (или пусто): ").upper() or None
        show_result(api("POST", f"/admin/5post/orders/{db_id}/set-status",
                        {"status": status, "execution_status": exec_st, "mile_type": mile}))
        return

    try:
        idx = int(choice)
        if 1 <= idx <= len(transitions):
            t = transitions[idx - 1]
            action = t["action"]
            if action == "next":
                show_result(api("POST", f"/admin/5post/orders/{db_id}/advance"))
            elif action == "unclaimed":
                show_result(api("POST", f"/admin/5post/orders/{db_id}/advance-unclaimed"))
            elif action == "cancel":
                show_result(api("POST", f"/admin/5post/orders/{db_id}/set-status",
                                {"status": "CANCELLED", "execution_status": "CANCELLED", "mile_type": None}))
            elif action == "reject":
                show_result(api("POST", f"/admin/5post/orders/{db_id}/set-status",
                                {"status": "REJECTED", "execution_status": "REJECTED", "mile_type": None}))
    except ValueError:
        pass


# ---------------------------------------------------------------------------
#  Magnit menu
# ---------------------------------------------------------------------------

def menu_magnit() -> None:
    while True:
        breadcrumb(["Magnit"])
        print("  1. Список заказов")
        print("  2. Детали заказа")
        print("  3. Продвинуть статус (next)")
        print("  4. Продвинуть ВСЕ заказы")
        print("  5. Установить статус")
        print("  6. Ветка <<возврат>>")
        print("  7. Lifecycle")
        print("  0. Назад")

        choice = _input("\nMagnit > ")
        if choice == "0" or not choice:
            return

        if choice == "1":
            magnit_orders_list()
        elif choice == "2":
            breadcrumb(["Magnit", "Детали заказа"])
            oid = _input("  Order # (db_id): ")
            if oid.isdigit():
                magnit_order_detail(int(oid))
        elif choice == "3":
            breadcrumb(["Magnit", "Продвинуть статус"])
            oid = _input("  Order # (db_id): ")
            if oid.isdigit():
                show_result(api("POST", f"/admin/magnit/orders/{oid}/advance"))
        elif choice == "4":
            breadcrumb(["Magnit", "Продвинуть ВСЕ"])
            data = api("POST", "/admin/magnit/advance-all")
            if data and data.get("ok"):
                con.print(f"  [green]OK[/green] Продвинуто {data['advanced']} из {data['total_active']} активных" if HAS_RICH
                          else f"  OK Продвинуто {data['advanced']} из {data['total_active']} активных")
            else:
                con.print(f"  {data}")
        elif choice == "5":
            breadcrumb(["Magnit", "Установить статус"])
            oid = _input("  Order # (db_id): ")
            if oid.isdigit():
                status = _input("  Status (NEW/CREATED/DELIVERING_STARTED/ACCEPTED_AT_POINT/ISSUED/...): ").upper()
                show_result(api("POST", f"/admin/magnit/orders/{oid}/set-status", {"status": status}))
        elif choice == "6":
            breadcrumb(["Magnit", "Ветка <<возврат>>"])
            oid = _input("  Order # (db_id): ")
            if oid.isdigit():
                show_result(api("POST", f"/admin/magnit/orders/{oid}/advance-return"))
        elif choice == "7":
            breadcrumb(["Magnit", "Lifecycle"])
            data = api("GET", "/admin/magnit/lifecycle")
            if data:
                print("\n  Happy path:")
                for i, s in enumerate(data.get("happy_path", []), 1):
                    print(f"    {i}. {s}")
                print("\n  Return branch (от ACCEPTED_AT_POINT):")
                for i, s in enumerate(data.get("return_branch", []), 1):
                    print(f"    R{i}. {s}")


def magnit_orders_list() -> None:
    """Magnit orders list with select-by-number."""
    while True:
        breadcrumb(["Magnit", "Заказы"])
        data = api("GET", "/admin/magnit/orders")
        if not data or not isinstance(data, list):
            con.print("  Нет заказов." if not data else f"  {data}")
            return

        orders = data
        rows = [
            [str(i + 1), str(o["db_id"]), o["customer_order_id"],
             o["recipient_name"] or "-", o["status"], o["created_at"][:16]]
            for i, o in enumerate(orders)
        ]
        show_table(f"Magnit Orders ({len(orders)})",
                   ["#", "DB ID", "CustomerOrderID", "Recipient", "Status", "Created"], rows)

        print()
        con.print("  [yellow][номер][/yellow]=детали+действия  [yellow]R[/yellow]efresh  [yellow]0[/yellow]=назад" if HAS_RICH
                  else "  [номер]=детали+действия  R-efresh  0=назад")
        choice = _input("  > ")
        if choice in ("0", "q", ""):
            return
        if choice == "r":
            continue  # refresh
        try:
            idx = int(choice)
            if 1 <= idx <= len(orders):
                magnit_order_actions(orders[idx - 1])
        except ValueError:
            pass


def magnit_order_detail(db_id: int) -> None:
    """Show Magnit order details + history."""
    data = api("GET", f"/admin/magnit/orders/{db_id}")
    if not data or "error" in data:
        con.print(f"  {data}")
        return
    show_detail(data, f"Magnit Order #{db_id}")
    history = data.get("history", [])
    if history:
        rows = [[h["status"], h["timestamp"][:19]] for h in history]
        show_table("История статусов", ["Status", "Timestamp"], rows)


def magnit_order_actions(order: dict) -> None:
    """Detail view + action menu for a Magnit order. Returns to list after action."""
    db_id = order["db_id"]
    customer_id = order["customer_order_id"]

    breadcrumb(["Magnit", "Заказы", customer_id])
    detail = api("GET", f"/admin/magnit/orders/{db_id}")
    if not detail or "error" in detail:
        con.print(f"  {detail}")
        return

    show_detail(detail, f"Magnit Order #{db_id}")
    history = detail.get("history", [])
    if history:
        rows = [[h["status"], h["timestamp"][:19]] for h in history]
        show_table("История статусов", ["Status", "Timestamp"], rows)

    # Show available transitions
    transitions = detail.get("available_transitions", [])
    print()
    if transitions:
        con.print("  [bold]Доступные переходы:[/bold]" if HAS_RICH else "  Доступные переходы:")
        for i, t in enumerate(transitions, 1):
            con.print(f"    [green]{i}[/green]. {t['label']}  [dim]({t['action']})[/dim]" if HAS_RICH
                      else f"    {i}. {t['label']}  ({t['action']})")
    else:
        con.print("  [dim]Нет доступных переходов (терминальный статус)[/dim]" if HAS_RICH
                  else "  Нет доступных переходов (терминальный статус)")

    print()
    print("  S. Установить произвольный статус")
    print("  0. Назад к списку")

    choice = _input(f"  {customer_id} > ")
    if choice in ("0", "q", ""):
        return

    if choice.lower() == "s":
        status = _input("  Status: ").upper()
        show_result(api("POST", f"/admin/magnit/orders/{db_id}/set-status", {"status": status}))
        return

    try:
        idx = int(choice)
        if 1 <= idx <= len(transitions):
            t = transitions[idx - 1]
            action = t["action"]
            if action == "next":
                show_result(api("POST", f"/admin/magnit/orders/{db_id}/advance"))
            elif action == "return":
                show_result(api("POST", f"/admin/magnit/orders/{db_id}/advance-return"))
            elif action == "cancel":
                show_result(api("POST", f"/admin/magnit/orders/{db_id}/set-status", {"status": "CANCELED_BY_PROVIDER"}))
    except ValueError:
        pass


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
        breadcrumb(["Emulator"])
        print("  1. 5Post")
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
            breadcrumb(["Emulator", "Статистика"])
            stats = api("GET", "/admin/stats")
            if stats:
                con.print(f"  5Post:  {stats['fivepost_orders']} заказов")
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

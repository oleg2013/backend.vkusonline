"""File-based email template engine with @@-header parsing and #PLACEHOLDER# substitution."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# Day name mapping for work schedule formatting
_DAY_ORDER = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
_DAY_LABELS = {
    "MON": "Пн", "TUE": "Вт", "WED": "Ср", "THU": "Чт",
    "FRI": "Пт", "SAT": "Сб", "SUN": "Вс",
}
_DELIVERY_COMPANY_MAP = {
    "5post": "5Post",
    "magnit": "Магнит Пост",
}

# Template header markers (use @@ to avoid conflicts with email addresses)
HEADER_RE = re.compile(r"^@@(\w+):\s*(.+)$", re.MULTILINE)
BODY_MARKER = "@@BODY:"
PLACEHOLDER_RE = re.compile(r"#([A-Z_]+)#")

# Cached HTML layout
_layout_html: str | None = None


def _get_layout(templates_root: str) -> str | None:
    """Load _layout.html from templates root (cached)."""
    global _layout_html
    if _layout_html is not None:
        return _layout_html
    layout_path = os.path.join(templates_root, "_layout.html")
    if os.path.isfile(layout_path):
        with open(layout_path, encoding="utf-8") as f:
            _layout_html = f.read()
        return _layout_html
    return None


@dataclass
class EmailTemplate:
    from_addr: str  # may contain placeholders like #SYS_SHOP_EMAIL#
    to_expr: str    # may contain placeholders like #EMAIL# or #SALE_EMAIL#
    subject: str    # may contain placeholders
    body: str       # may contain placeholders (HTML content)
    enabled: bool = True
    file_path: str = ""


@dataclass
class RenderedEmail:
    from_addr: str
    to: str
    subject: str
    body: str
    content_type: str = "text/html"


def load_template(file_path: str) -> EmailTemplate:
    """Load a .template file and parse @@FROM, @@TO, @@SUBJECT, @@BODY headers."""
    with open(file_path, encoding="utf-8") as f:
        content = f.read()

    # Extract headers before @@BODY
    body_idx = content.find(BODY_MARKER)
    if body_idx == -1:
        raise ValueError(f"Template {file_path} missing @@BODY: marker")

    header_section = content[:body_idx]
    body = content[body_idx + len(BODY_MARKER):].strip()

    headers: dict[str, str] = {}
    for match in HEADER_RE.finditer(header_section):
        headers[match.group(1).upper()] = match.group(2).strip()

    from_addr = headers.get("FROM", "#SYS_SHOP_EMAIL#")
    to_expr = headers.get("TO", "#EMAIL#")
    subject = headers.get("SUBJECT", "")
    enabled_raw = headers.get("ENABLED", "true").lower()
    enabled = enabled_raw not in ("false", "0", "no")

    return EmailTemplate(
        from_addr=from_addr,
        to_expr=to_expr,
        subject=subject,
        body=body,
        enabled=enabled,
        file_path=file_path,
    )


def render_template(
    template: EmailTemplate,
    context: dict[str, str],
    templates_root: str = "templates/email",
) -> RenderedEmail:
    """Substitute #PLACEHOLDER# tokens and wrap in HTML layout."""
    def substitute(text: str) -> str:
        def replacer(match: re.Match) -> str:
            key = match.group(1)
            return context.get(key, match.group(0))
        return PLACEHOLDER_RE.sub(replacer, text)

    subject = substitute(template.subject)
    body = substitute(template.body)

    # Wrap body in HTML layout
    layout = _get_layout(templates_root)
    if layout:
        full_html = layout.replace("#EMAIL_CONTENT#", body).replace("#EMAIL_SUBJECT#", subject)
        # Substitute remaining placeholders in layout (SHOP_NAME, SALE_EMAIL, etc.)
        body = substitute(full_html)

    return RenderedEmail(
        from_addr=substitute(template.from_addr),
        to=substitute(template.to_expr),
        subject=subject,
        body=body,
    )


def find_templates(templates_root: str, order_type: str, event_name: str) -> list[EmailTemplate]:
    """Find all .template files for a given order_type and event.

    Looks in: {templates_root}/{ORDER_TYPE}/{EVENT_NAME}/*.template
    """
    event_dir = os.path.join(templates_root, order_type.upper(), event_name.upper())
    if not os.path.isdir(event_dir):
        logger.debug("no_template_dir", path=event_dir)
        return []

    templates = []
    for fname in sorted(os.listdir(event_dir)):
        if fname.endswith(".template"):
            fpath = os.path.join(event_dir, fname)
            try:
                tmpl = load_template(fpath)
                if not tmpl.enabled:
                    logger.debug("template_disabled", path=fpath)
                    continue
                templates.append(tmpl)
            except Exception as exc:
                logger.error("template_load_error", path=fpath, error=str(exc))

    return templates


async def fetch_pvz_details(provider: str, pvz_external_id: str) -> dict[str, Any] | None:
    """Fetch pickup point details from cache by provider + external_id."""
    from packages.core.db import async_session_factory
    from sqlalchemy import select
    from packages.models.pickup_point import PickupPointCache

    async with async_session_factory() as db:
        stmt = select(PickupPointCache).where(
            PickupPointCache.provider == provider,
            PickupPointCache.external_id == pvz_external_id,
        )
        row = (await db.execute(stmt)).scalar_one_or_none()
        if not row:
            return None
        raw = row.raw_data or {}
        return {
            "provider": provider,
            "name": row.name,
            "full_address": row.full_address,
            "phone": raw.get("phone"),
            "additional": raw.get("additional"),
            "work_hours": raw.get("work_hours") or raw.get("work_schedule") or [],
        }


def _format_work_hours(hours_list: list[dict]) -> str:
    """Format work_hours list into compact human-readable string.

    Groups consecutive days with the same schedule.
    Example: "Пн-Пт: 10:00-21:00, Сб-Вс: 10:00-20:00"
    """
    if not hours_list:
        return ""

    # Sort by day order and normalize time format (strip trailing :00 seconds)
    schedule: list[tuple[str, str]] = []
    for entry in sorted(hours_list, key=lambda e: _DAY_ORDER.index(e["day"]) if e["day"] in _DAY_ORDER else 99):
        day = entry.get("day", "")
        opens = (entry.get("opens_at") or "")[:5]   # "10:00:00" → "10:00"
        closes = (entry.get("closes_at") or "")[:5]
        if day in _DAY_LABELS and opens and closes:
            schedule.append((day, f"{opens}\u2013{closes}"))

    if not schedule:
        return ""

    # Group consecutive days with the same hours
    groups: list[tuple[list[str], str]] = []
    for day, hours in schedule:
        if groups and groups[-1][1] == hours:
            groups[-1][0].append(day)
        else:
            groups.append(([day], hours))

    parts = []
    for days, hours in groups:
        if len(days) == 1:
            label = _DAY_LABELS[days[0]]
        else:
            label = f"{_DAY_LABELS[days[0]]}\u2013{_DAY_LABELS[days[-1]]}"
        parts.append(f"{label}: {hours}")

    return ", ".join(parts)


def _build_pvz_details_html(provider: str, pvz_data: dict[str, Any]) -> str:
    """Build styled HTML card with pickup point details."""
    company = _DELIVERY_COMPANY_MAP.get(provider, provider)
    name = pvz_data.get("name", "")
    address = pvz_data.get("full_address", "")
    phone = pvz_data.get("phone") or ""
    additional = pvz_data.get("additional") or ""
    work_hours = _format_work_hours(pvz_data.get("work_hours", []))

    rows = []
    if address:
        rows.append(
            f'<tr><td style="padding:5px 0;font-size:13px;color:#888;width:100px;vertical-align:top;">Адрес</td>'
            f'<td style="padding:5px 0;font-size:14px;color:#333;">{address}</td></tr>'
        )
    if work_hours:
        rows.append(
            f'<tr><td style="padding:5px 0;font-size:13px;color:#888;vertical-align:top;">Режим работы</td>'
            f'<td style="padding:5px 0;font-size:14px;color:#333;">{work_hours}</td></tr>'
        )
    if phone:
        # Format phone for display
        ph_display = phone
        if phone.isdigit() and len(phone) == 11:
            ph_display = f"{phone[0]} ({phone[1:4]}) {phone[4:7]}-{phone[7:9]}-{phone[9:11]}"
        rows.append(
            f'<tr><td style="padding:5px 0;font-size:13px;color:#888;vertical-align:top;">Телефон</td>'
            f'<td style="padding:5px 0;font-size:14px;color:#333;">{ph_display}</td></tr>'
        )
    if additional:
        rows.append(
            f'<tr><td style="padding:5px 0;font-size:13px;color:#888;vertical-align:top;">Примечание</td>'
            f'<td style="padding:5px 0;font-size:14px;color:#555;">{additional}</td></tr>'
        )

    rows_html = "".join(rows)

    return (
        f'<div style="margin:16px 0;padding:16px 20px;background-color:#FAF6F0;border-radius:10px;'
        f'border-left:4px solid #C8860A;">'
        f'<p style="margin:0 0 10px;font-size:15px;font-weight:600;color:#333;">'
        f'{company} — {name}</p>'
        f'<table cellpadding="0" cellspacing="0" border="0" width="100%">'
        f'{rows_html}'
        f'</table>'
        f'</div>'
    )


def _build_pvz_details_text(provider: str, pvz_data: dict[str, Any]) -> str:
    """Build plain text version of PVZ details."""
    company = _DELIVERY_COMPANY_MAP.get(provider, provider)
    name = pvz_data.get("name", "")
    address = pvz_data.get("full_address", "")
    phone = pvz_data.get("phone") or ""
    additional = pvz_data.get("additional") or ""
    work_hours = _format_work_hours(pvz_data.get("work_hours", []))

    lines = [f"{company} — {name}"]
    if address:
        lines.append(f"  Адрес: {address}")
    if work_hours:
        lines.append(f"  Режим работы: {work_hours}")
    if phone:
        lines.append(f"  Телефон: {phone}")
    if additional:
        lines.append(f"  Примечание: {additional}")
    return "\n".join(lines)


def build_order_context(order, extra: dict[str, str] | None = None, pvz_data: dict[str, Any] | None = None) -> dict[str, str]:
    """Build substitution context dict from an Order object."""
    from packages.core.config import settings

    items_lines = []
    if hasattr(order, "items") and order.items:
        for item in order.items:
            line = f"  {item.product_sku} — {item.product_name} x{item.quantity} = {item.total_price / 100:.2f} руб."
            items_lines.append(line)

    # Summary block: subtotal, delivery, discount, total
    summary_lines = []
    subtotal = getattr(order, "subtotal", 0) or 0
    delivery_price = getattr(order, "customer_delivery_price", 0) or 0
    discount = getattr(order, "discount_amount", 0) or 0
    total = getattr(order, "total", 0) or 0
    provider = getattr(order, "delivery_provider", "") or ""
    city = getattr(order, "delivery_city", "") or ""
    pvz_name = getattr(order, "pickup_point_name", "") or ""
    pay_method = getattr(order, "payment_method", "") or ""

    summary_lines.append("")
    summary_lines.append(f"  Товары: {subtotal / 100:.2f} руб.")
    summary_lines.append(f"  Доставка ({provider}, {city}): {delivery_price / 100:.2f} руб.")
    if pvz_name:
        summary_lines.append(f"  Пункт выдачи: {pvz_name}")
    if discount > 0:
        summary_lines.append(f"  Скидка: -{discount / 100:.2f} руб.")
    pay_label = "Картой" if pay_method == "card" else "Наложенный платёж" if pay_method == "cod" else pay_method
    summary_lines.append(f"  Оплата: {pay_label}")
    summary_lines.append(f"  ИТОГО: {total / 100:.2f} руб.")

    order_list_text = "\n".join(items_lines) if items_lines else "(нет товаров)"
    order_list_text += "\n" + "\n".join(summary_lines)

    # Plain text order list without prices
    no_price_lines = []
    if hasattr(order, "items") and order.items:
        for item in order.items:
            no_price_lines.append(f"  {item.product_sku} — {item.product_name} x{item.quantity}")
    order_list_no_price_text = "\n".join(no_price_lines) if no_price_lines else "(нет товаров)"

    # HTML version of order list (for HTML templates)
    items_html_rows = []
    items_no_price_html_rows = []
    if hasattr(order, "items") and order.items:
        for item in order.items:
            items_html_rows.append(
                f'<tr>'
                f'<td style="padding:8px 0;border-bottom:1px solid #F0E6D6;color:#333;font-size:14px;">'
                f'{item.product_name}</td>'
                f'<td style="padding:8px 12px;border-bottom:1px solid #F0E6D6;color:#888;font-size:14px;text-align:center;">'
                f'{item.quantity} шт.</td>'
                f'<td style="padding:8px 0;border-bottom:1px solid #F0E6D6;color:#333;font-size:14px;text-align:right;white-space:nowrap;">'
                f'{item.total_price / 100:.2f} &#8381;</td>'
                f'</tr>'
            )
            items_no_price_html_rows.append(
                f'<tr>'
                f'<td style="padding:8px 0;border-bottom:1px solid #F0E6D6;color:#333;font-size:14px;">'
                f'{item.product_name}</td>'
                f'<td style="padding:8px 12px;border-bottom:1px solid #F0E6D6;color:#888;font-size:14px;text-align:center;">'
                f'{item.quantity} шт.</td>'
                f'</tr>'
            )
    items_table = "".join(items_html_rows) if items_html_rows else (
        '<tr><td colspan="3" style="padding:8px 0;color:#999;">нет товаров</td></tr>'
    )
    items_no_price_table = "".join(items_no_price_html_rows) if items_no_price_html_rows else (
        '<tr><td colspan="2" style="padding:8px 0;color:#999;">нет товаров</td></tr>'
    )

    summary_html = (
        f'<tr><td colspan="2" style="padding:6px 0;color:#888;font-size:13px;">Товары</td>'
        f'<td style="padding:6px 0;text-align:right;color:#333;font-size:13px;">{subtotal / 100:.2f} &#8381;</td></tr>'
        f'<tr><td colspan="2" style="padding:6px 0;color:#888;font-size:13px;">Доставка</td>'
        f'<td style="padding:6px 0;text-align:right;color:#333;font-size:13px;">{delivery_price / 100:.2f} &#8381;</td></tr>'
    )
    if discount > 0:
        summary_html += (
            f'<tr><td colspan="2" style="padding:6px 0;color:#C8860A;font-size:13px;">Скидка</td>'
            f'<td style="padding:6px 0;text-align:right;color:#C8860A;font-size:13px;">-{discount / 100:.2f} &#8381;</td></tr>'
        )
    summary_html += (
        f'<tr><td colspan="2" style="padding:10px 0 0;font-size:16px;font-weight:600;color:#333;">Итого</td>'
        f'<td style="padding:10px 0 0;text-align:right;font-size:16px;font-weight:600;color:#C8860A;">{total / 100:.2f} &#8381;</td></tr>'
    )

    order_list_html = (
        f'<table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:16px 0;">'
        f'{items_table}'
        f'<tr><td colspan="3" style="padding:12px 0 8px;border-top:2px solid #F0E6D6;"></td></tr>'
        f'{summary_html}'
        f'</table>'
    )

    order_list_no_price_html = (
        f'<table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:16px 0;">'
        f'{items_no_price_table}'
        f'</table>'
    )

    # Delivery company human-readable name
    delivery_company = _DELIVERY_COMPANY_MAP.get(provider, provider)

    pvz_id = getattr(order, "pickup_point_id", "") or ""

    # PVZ details block (HTML + text)
    pvz_details_html = ""
    pvz_details_text = ""
    if pvz_data and provider:
        pvz_details_html = _build_pvz_details_html(provider, pvz_data)
        pvz_details_text = _build_pvz_details_text(provider, pvz_data)

    ctx = {
        "EMAIL": order.customer_email or "",
        "ORDER_USER": order.customer_name or "",
        "PHONE": order.customer_phone or "",
        "ORDER_ID": order.order_number or "",
        "ORDER_DATE": order.created_at.strftime("%d.%m.%Y %H:%M") if order.created_at else "",
        "ORDER_LIST": order_list_text,
        "ORDER_LIST_HTML": order_list_html,
        "ORDER_LIST_WITHOUT_PRICE": order_list_no_price_text,
        "ORDER_LIST_WITHOUT_PRICE_HTML": order_list_no_price_html,
        "PRICE": f"{total / 100:.2f} руб." if total else "0",
        "UNIQUE_ORDER_ID": order.guest_order_token or "",
        "DELIVERCOMPANY": delivery_company,
        "PVZNAME": pvz_name,
        "PVZID": pvz_id,
        "PVZDETAILS": pvz_details_text,
        "PVZDETAILS_HTML": pvz_details_html,
        "SERVER_NAME": settings.server_name,
        "SHOP_NAME": settings.shop_name,
        "SALE_EMAIL": settings.sale_email,
        "SYS_SHOP_EMAIL": settings.smtp_from_email,
    }
    if extra:
        ctx.update(extra)
    return ctx

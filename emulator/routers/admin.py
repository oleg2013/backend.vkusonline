"""Admin API for the Delivery Emulator.

Provides endpoints for the CLI tool to manage emulated orders:
- List orders (5Post / Magnit)
- View order details
- Advance order status (next step in lifecycle)
- Advance ALL orders
- Set arbitrary status
- Show lifecycle definitions
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import (
    EmulFivePostOrder,
    EmulFivePostStatusHistory,
    EmulMagnitOrder,
    EmulMagnitStatusHistory,
    get_db,
)
from lifecycle import (
    FIVEPOST_EXECUTION_STATUSES,
    FIVEPOST_HAPPY_PATH,
    FIVEPOST_STATUSES,
    FIVEPOST_UNCLAIMED_PATH,
    MAGNIT_ALL_STATUSES,
    MAGNIT_HAPPY_PATH,
    MAGNIT_RETURN_PATH,
    FivePostState,
    fivepost_branch_unclaimed,
    fivepost_next_step,
    magnit_branch_return,
    magnit_next_step,
)

router = APIRouter(prefix="/admin", tags=["Admin"])
log = logging.getLogger("emulator.admin")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str:
    return dt.isoformat() if dt else ""


# ── Stats ───────────────────────────────────────────────────────────

@router.get("/stats")
async def stats(db: AsyncSession = Depends(get_db)):
    fp = (await db.execute(select(func.count(EmulFivePostOrder.id)))).scalar()
    mg = (await db.execute(select(func.count(EmulMagnitOrder.id)))).scalar()
    return {"fivepost_orders": fp, "magnit_orders": mg}


# ── 5Post ───────────────────────────────────────────────────────────

@router.get("/5post/orders")
async def fivepost_list(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(EmulFivePostOrder).order_by(EmulFivePostOrder.created_at.desc())
    )
    orders = result.scalars().all()
    return [
        {
            "db_id": o.id,
            "order_id": str(o.order_id),
            "sender_order_id": o.sender_order_id,
            "client_name": o.client_name,
            "status": o.status,
            "execution_status": o.execution_status,
            "mile_type": o.mile_type,
            "payment_value": o.payment_value,
            "created_at": _iso(o.created_at),
        }
        for o in orders
    ]


@router.get("/5post/orders/{db_id}")
async def fivepost_detail(db_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(EmulFivePostOrder).where(EmulFivePostOrder.id == db_id)
    )
    order = result.scalar_one_or_none()
    if not order:
        return {"error": f"Order #{db_id} not found"}

    hist = await db.execute(
        select(EmulFivePostStatusHistory)
        .where(EmulFivePostStatusHistory.order_id == order.order_id)
        .order_by(EmulFivePostStatusHistory.change_date)
    )
    history = [
        {
            "status": h.status,
            "execution_status": h.execution_status,
            "mile_type": h.mile_type,
            "change_date": _iso(h.change_date),
            "error_desc": h.error_desc,
        }
        for h in hist.scalars().all()
    ]

    return {
        "db_id": order.id,
        "order_id": str(order.order_id),
        "sender_order_id": order.sender_order_id,
        "client_name": order.client_name,
        "client_phone": order.client_phone,
        "client_email": order.client_email,
        "receiver_location": order.receiver_location,
        "status": order.status,
        "execution_status": order.execution_status,
        "mile_type": order.mile_type,
        "payment_value": order.payment_value,
        "payment_type": order.payment_type,
        "barcode": order.barcode,
        "created_at": _iso(order.created_at),
        "updated_at": _iso(order.updated_at),
        "history": history,
    }


@router.post("/5post/orders/{db_id}/advance")
async def fivepost_advance(db_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(EmulFivePostOrder).where(EmulFivePostOrder.id == db_id)
    )
    order = result.scalar_one_or_none()
    if not order:
        return {"error": f"Order #{db_id} not found"}

    current = FivePostState(order.status, order.execution_status, order.mile_type)
    next_state = fivepost_next_step(current)

    if not next_state:
        branch = fivepost_branch_unclaimed(current)
        if branch:
            return {
                "error": "happy_path_complete",
                "message": f"At {current.execution_status}. Use /advance-unclaimed to branch.",
                "current": {"status": current.status, "execution_status": current.execution_status},
            }
        return {"error": "terminal", "message": f"Terminal state: {order.status}/{order.execution_status}"}

    now = _utcnow()
    old = f"{order.status}/{order.execution_status}"
    order.status = next_state.status
    order.execution_status = next_state.execution_status
    order.mile_type = next_state.mile_type
    order.updated_at = now

    db.add(EmulFivePostStatusHistory(
        order_id=order.order_id, status=next_state.status,
        execution_status=next_state.execution_status,
        mile_type=next_state.mile_type, change_date=now,
    ))
    await db.commit()

    log.info("[ADMIN] 5Post advance #%d: %s -> %s/%s (%s)",
             db_id, old, next_state.status, next_state.execution_status, next_state.mile_type or "-")

    return {
        "ok": True,
        "old": old,
        "new": f"{next_state.status}/{next_state.execution_status}",
        "mile_type": next_state.mile_type,
    }


@router.post("/5post/orders/{db_id}/advance-unclaimed")
async def fivepost_advance_unclaimed(db_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(EmulFivePostOrder).where(EmulFivePostOrder.id == db_id)
    )
    order = result.scalar_one_or_none()
    if not order:
        return {"error": f"Order #{db_id} not found"}

    current = FivePostState(order.status, order.execution_status, order.mile_type)
    branch = fivepost_branch_unclaimed(current)
    if not branch:
        return {"error": "not_available", "message": f"Unclaimed branch only from PLACED_IN_POSTAMAT, current: {current.execution_status}"}

    now = _utcnow()
    old = f"{order.status}/{order.execution_status}"
    order.status = branch.status
    order.execution_status = branch.execution_status
    order.mile_type = branch.mile_type
    order.updated_at = now

    db.add(EmulFivePostStatusHistory(
        order_id=order.order_id, status=branch.status,
        execution_status=branch.execution_status,
        mile_type=branch.mile_type, change_date=now,
    ))
    await db.commit()

    log.info("[ADMIN] 5Post unclaimed #%d: %s -> %s/%s", db_id, old, branch.status, branch.execution_status)
    return {"ok": True, "old": old, "new": f"{branch.status}/{branch.execution_status}", "mile_type": branch.mile_type}


@router.post("/5post/orders/{db_id}/set-status")
async def fivepost_set_status(db_id: int, body: dict, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(EmulFivePostOrder).where(EmulFivePostOrder.id == db_id)
    )
    order = result.scalar_one_or_none()
    if not order:
        return {"error": f"Order #{db_id} not found"}

    status = body.get("status", "").upper()
    exec_status = body.get("execution_status", "").upper()
    mile_type = body.get("mile_type", "").upper() or None

    if status not in FIVEPOST_STATUSES:
        return {"error": f"Invalid status: {status}", "valid": FIVEPOST_STATUSES}
    if exec_status not in FIVEPOST_EXECUTION_STATUSES:
        return {"error": f"Invalid execution_status: {exec_status}", "valid": FIVEPOST_EXECUTION_STATUSES}

    now = _utcnow()
    old = f"{order.status}/{order.execution_status}"
    order.status = status
    order.execution_status = exec_status
    order.mile_type = mile_type
    order.updated_at = now

    db.add(EmulFivePostStatusHistory(
        order_id=order.order_id, status=status,
        execution_status=exec_status, mile_type=mile_type, change_date=now,
    ))
    await db.commit()

    log.info("[ADMIN] 5Post set #%d: %s -> %s/%s (%s)", db_id, old, status, exec_status, mile_type or "-")
    return {"ok": True, "old": old, "new": f"{status}/{exec_status}", "mile_type": mile_type}


@router.post("/5post/advance-all")
async def fivepost_advance_all(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(EmulFivePostOrder).where(
            EmulFivePostOrder.status.notin_(["DONE", "CANCELLED", "REJECTED"])
        )
    )
    orders = result.scalars().all()
    advanced = 0
    for order in orders:
        current = FivePostState(order.status, order.execution_status, order.mile_type)
        ns = fivepost_next_step(current)
        if not ns:
            continue
        now = _utcnow()
        order.status = ns.status
        order.execution_status = ns.execution_status
        order.mile_type = ns.mile_type
        order.updated_at = now
        db.add(EmulFivePostStatusHistory(
            order_id=order.order_id, status=ns.status,
            execution_status=ns.execution_status, mile_type=ns.mile_type, change_date=now,
        ))
        advanced += 1
    await db.commit()
    log.info("[ADMIN] 5Post advance-all: %d/%d", advanced, len(orders))
    return {"ok": True, "advanced": advanced, "total_active": len(orders)}


@router.get("/5post/lifecycle")
async def fivepost_lifecycle():
    return {
        "happy_path": [
            {"step": i + 1, "status": s.status, "execution_status": s.execution_status, "mile_type": s.mile_type}
            for i, s in enumerate(FIVEPOST_HAPPY_PATH)
        ],
        "unclaimed_branch": [
            {"step": i + 1, "status": s.status, "execution_status": s.execution_status, "mile_type": s.mile_type}
            for i, s in enumerate(FIVEPOST_UNCLAIMED_PATH)
        ],
    }


# ── Magnit ──────────────────────────────────────────────────────────

@router.get("/magnit/orders")
async def magnit_list(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(EmulMagnitOrder).order_by(EmulMagnitOrder.created_at.desc())
    )
    orders = result.scalars().all()
    return [
        {
            "db_id": o.id,
            "tracking_number": str(o.tracking_number),
            "customer_order_id": o.customer_order_id,
            "recipient_name": o.recipient_name,
            "status": o.status,
            "created_at": _iso(o.created_at),
        }
        for o in orders
    ]


@router.get("/magnit/orders/{db_id}")
async def magnit_detail(db_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(EmulMagnitOrder).where(EmulMagnitOrder.id == db_id)
    )
    order = result.scalar_one_or_none()
    if not order:
        return {"error": f"Order #{db_id} not found"}

    hist = await db.execute(
        select(EmulMagnitStatusHistory)
        .where(EmulMagnitStatusHistory.tracking_number == order.tracking_number)
        .order_by(EmulMagnitStatusHistory.timestamp)
    )
    history = [
        {"status": h.status, "timestamp": _iso(h.timestamp)}
        for h in hist.scalars().all()
    ]

    return {
        "db_id": order.id,
        "tracking_number": str(order.tracking_number),
        "customer_order_id": order.customer_order_id,
        "external_order_id": order.external_order_id,
        "recipient_name": order.recipient_name,
        "recipient_phone": order.recipient_phone,
        "pickup_point_key": order.pickup_point_key,
        "status": order.status,
        "created_at": _iso(order.created_at),
        "updated_at": _iso(order.updated_at),
        "history": history,
    }


@router.post("/magnit/orders/{db_id}/advance")
async def magnit_advance(db_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(EmulMagnitOrder).where(EmulMagnitOrder.id == db_id)
    )
    order = result.scalar_one_or_none()
    if not order:
        return {"error": f"Order #{db_id} not found"}

    ns = magnit_next_step(order.status)
    if not ns:
        branch = magnit_branch_return(order.status)
        if branch:
            return {
                "error": "happy_path_complete",
                "message": f"At {order.status}. Use /advance-return to branch.",
                "current_status": order.status,
            }
        return {"error": "terminal", "message": f"Terminal state: {order.status}"}

    now = _utcnow()
    old = order.status
    order.status = ns
    order.updated_at = now

    db.add(EmulMagnitStatusHistory(tracking_number=order.tracking_number, status=ns, timestamp=now))
    await db.commit()

    log.info("[ADMIN] Magnit advance #%d: %s -> %s", db_id, old, ns)
    return {"ok": True, "old": old, "new": ns}


@router.post("/magnit/orders/{db_id}/advance-return")
async def magnit_advance_return(db_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(EmulMagnitOrder).where(EmulMagnitOrder.id == db_id)
    )
    order = result.scalar_one_or_none()
    if not order:
        return {"error": f"Order #{db_id} not found"}

    branch = magnit_branch_return(order.status)
    if not branch:
        return {"error": "not_available", "message": f"Return branch only from ACCEPTED_AT_POINT, current: {order.status}"}

    now = _utcnow()
    old = order.status
    order.status = branch
    order.updated_at = now

    db.add(EmulMagnitStatusHistory(tracking_number=order.tracking_number, status=branch, timestamp=now))
    await db.commit()

    log.info("[ADMIN] Magnit return #%d: %s -> %s", db_id, old, branch)
    return {"ok": True, "old": old, "new": branch}


@router.post("/magnit/orders/{db_id}/set-status")
async def magnit_set_status(db_id: int, body: dict, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(EmulMagnitOrder).where(EmulMagnitOrder.id == db_id)
    )
    order = result.scalar_one_or_none()
    if not order:
        return {"error": f"Order #{db_id} not found"}

    status = body.get("status", "").upper()
    if status not in MAGNIT_ALL_STATUSES:
        return {"error": f"Invalid status: {status}", "valid": MAGNIT_ALL_STATUSES}

    now = _utcnow()
    old = order.status
    order.status = status
    order.updated_at = now

    db.add(EmulMagnitStatusHistory(tracking_number=order.tracking_number, status=status, timestamp=now))
    await db.commit()

    log.info("[ADMIN] Magnit set #%d: %s -> %s", db_id, old, status)
    return {"ok": True, "old": old, "new": status}


@router.post("/magnit/advance-all")
async def magnit_advance_all(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(EmulMagnitOrder).where(
            EmulMagnitOrder.status.notin_(["ISSUED", "RETURNED_TO_PROVIDER", "CANCELED_BY_PROVIDER", "DESTROYED", "REMOVED"])
        )
    )
    orders = result.scalars().all()
    advanced = 0
    for order in orders:
        ns = magnit_next_step(order.status)
        if not ns:
            continue
        now = _utcnow()
        order.status = ns
        order.updated_at = now
        db.add(EmulMagnitStatusHistory(tracking_number=order.tracking_number, status=ns, timestamp=now))
        advanced += 1
    await db.commit()
    log.info("[ADMIN] Magnit advance-all: %d/%d", advanced, len(orders))
    return {"ok": True, "advanced": advanced, "total_active": len(orders)}


@router.get("/magnit/lifecycle")
async def magnit_lifecycle():
    return {
        "happy_path": MAGNIT_HAPPY_PATH,
        "return_branch": MAGNIT_RETURN_PATH,
    }

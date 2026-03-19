"""Order state machine — transition validation and stepper for PREPAID/CODFLOW orders."""

from __future__ import annotations

from packages.core.exceptions import ConflictError
from packages.enums import OrderStatus, OrderType

# ---------------------------------------------------------------------------
# Transition maps
# ---------------------------------------------------------------------------

PREPAID_TRANSITIONS: dict[str, set[str]] = {
    OrderStatus.DRAFT: {OrderStatus.PENDING_PAYMENT, OrderStatus.CANCELLED},
    OrderStatus.PENDING_PAYMENT: {OrderStatus.PAID, OrderStatus.CANCELLED},
    OrderStatus.PAID: {OrderStatus.CONFIRMED, OrderStatus.CANCELLED},
    OrderStatus.CONFIRMED: {OrderStatus.SHIPPED},
    OrderStatus.SHIPPED: {OrderStatus.READY_FOR_PICKUP, OrderStatus.RETURNED_TO_SUPPLIER},
    OrderStatus.READY_FOR_PICKUP: {OrderStatus.DELIVERED, OrderStatus.CLIENT_DONT_PICKUP, OrderStatus.RETURNED_TO_SUPPLIER},
    OrderStatus.CLIENT_DONT_PICKUP: {OrderStatus.RETURNED_TO_SUPPLIER, OrderStatus.REFUNDED},
    OrderStatus.DELIVERED: set(),
    OrderStatus.CANCELLED: set(),
    OrderStatus.RETURNED_TO_SUPPLIER: {OrderStatus.REFUNDED},
    OrderStatus.REFUNDED: set(),
}

CODFLOW_TRANSITIONS: dict[str, set[str]] = {
    OrderStatus.DRAFT: {OrderStatus.PENDING_CONFIRMATION, OrderStatus.CANCELLED},
    OrderStatus.PENDING_CONFIRMATION: {OrderStatus.CONFIRMED, OrderStatus.CANCELLED},
    OrderStatus.CONFIRMED: {OrderStatus.SHIPPED, OrderStatus.CANCELLED},
    OrderStatus.SHIPPED: {OrderStatus.READY_FOR_PICKUP, OrderStatus.RETURNED_TO_SUPPLIER},
    OrderStatus.READY_FOR_PICKUP: {OrderStatus.DELIVERED, OrderStatus.CLIENT_DONT_PICKUP},
    OrderStatus.CLIENT_DONT_PICKUP: {OrderStatus.RETURNED_TO_SUPPLIER},
    OrderStatus.DELIVERED: set(),
    OrderStatus.CANCELLED: set(),
    OrderStatus.RETURNED_TO_SUPPLIER: set(),
}

TRANSITION_MAP: dict[str, dict[str, set[str]]] = {
    OrderType.PREPAID: PREPAID_TRANSITIONS,
    OrderType.CODFLOW: CODFLOW_TRANSITIONS,
}

# ---------------------------------------------------------------------------
# Human-readable status labels
# ---------------------------------------------------------------------------

STATUS_LABELS: dict[str, str] = {
    OrderStatus.DRAFT: "Черновик",
    OrderStatus.PENDING_PAYMENT: "Ожидает оплаты",
    OrderStatus.PAID: "Оплачен",
    OrderStatus.PENDING_CONFIRMATION: "Ожидает подтверждения клиента",
    OrderStatus.CONFIRMED: "Подтвержден",
    OrderStatus.SHIPPED: "Отправлен",
    OrderStatus.READY_FOR_PICKUP: "Ожидает в пункте выдачи",
    OrderStatus.DELIVERED: "Доставлен",
    OrderStatus.CANCELLED: "Отменён",
    OrderStatus.CLIENT_DONT_PICKUP: "Клиент не забрал посылку",
    OrderStatus.RETURNED_TO_SUPPLIER: "Возвращен в магазин",
    OrderStatus.REFUNDED: "Возврат средств",
}

# ---------------------------------------------------------------------------
# Stepper step sequences (happy path only)
# ---------------------------------------------------------------------------

PREPAID_STEPPER_STEPS: list[str] = [
    OrderStatus.PENDING_PAYMENT,
    OrderStatus.PAID,
    OrderStatus.CONFIRMED,
    OrderStatus.SHIPPED,
    OrderStatus.READY_FOR_PICKUP,
    OrderStatus.DELIVERED,
]

CODFLOW_STEPPER_STEPS: list[str] = [
    OrderStatus.PENDING_CONFIRMATION,
    OrderStatus.CONFIRMED,
    OrderStatus.SHIPPED,
    OrderStatus.READY_FOR_PICKUP,
    OrderStatus.DELIVERED,
]

STEPPER_MAP: dict[str, list[str]] = {
    OrderType.PREPAID: PREPAID_STEPPER_STEPS,
    OrderType.CODFLOW: CODFLOW_STEPPER_STEPS,
}

# Terminal statuses shown as special badges, not stepper steps
TERMINAL_STATUSES: set[str] = {
    OrderStatus.CANCELLED,
    OrderStatus.CLIENT_DONT_PICKUP,
    OrderStatus.RETURNED_TO_SUPPLIER,
    OrderStatus.REFUNDED,
}

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_transition(order_type: str, current_status: str, new_status: str) -> bool:
    """Return True if the transition is valid."""
    transitions = TRANSITION_MAP.get(order_type, {})
    allowed = transitions.get(current_status, set())
    return new_status in allowed


def require_valid_transition(order_type: str, current_status: str, new_status: str) -> None:
    """Raise ConflictError if the transition is invalid."""
    if not validate_transition(order_type, current_status, new_status):
        allowed = get_allowed_transitions(order_type, current_status)
        allowed_labels = ", ".join(allowed) if allowed else "нет доступных"
        raise ConflictError(
            f"Невозможно перевести заказ ({order_type}) из '{current_status}' "
            f"в '{new_status}'. Допустимые: {allowed_labels}"
        )


def get_allowed_transitions(order_type: str, current_status: str) -> set[str]:
    """Return set of statuses reachable from current_status."""
    transitions = TRANSITION_MAP.get(order_type, {})
    return transitions.get(current_status, set())


def get_status_label(status: str) -> str:
    """Return human-readable label for a status."""
    return STATUS_LABELS.get(status, status)


def build_stepper(order_type: str, current_status: str) -> list[dict]:
    """Build ordered list of stepper steps with state flags.

    Each step: {"key": "...", "label": "...", "state": "completed"|"active"|"pending"}

    If the order is in a terminal status (cancelled, returned, etc.) — the stepper
    shows the last completed step and the terminal status as the final active step.
    """
    steps_sequence = STEPPER_MAP.get(order_type, [])
    if not steps_sequence:
        return []

    # Check if current status is terminal
    is_terminal = current_status in TERMINAL_STATUSES

    # Find the index of the current status in the happy-path sequence
    try:
        current_idx = steps_sequence.index(current_status)
    except ValueError:
        # Current status is not in the happy path (terminal or unknown)
        # Find the last step that was completed before the terminal status
        current_idx = -1
        if is_terminal:
            # Walk back through stepper to find where we branched off
            for i, step in enumerate(steps_sequence):
                transitions = TRANSITION_MAP.get(order_type, {})
                if current_status in transitions.get(step, set()):
                    current_idx = i
                    break

    result = []
    for i, step_key in enumerate(steps_sequence):
        if i < current_idx:
            state = "completed"
        elif i == current_idx and not is_terminal:
            state = "active"
        elif i == current_idx and is_terminal:
            state = "completed"
        else:
            state = "pending"

        result.append({
            "key": step_key,
            "label": get_status_label(step_key),
            "state": state,
        })

    # Append terminal status as last step if applicable
    if is_terminal:
        result.append({
            "key": current_status,
            "label": get_status_label(current_status),
            "state": "active",
        })

    return result

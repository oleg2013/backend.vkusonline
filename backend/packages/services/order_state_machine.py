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
    OrderStatus.PENDING_CONFIRMATION: {OrderStatus.CONFIRMED_BY_CLIENT, OrderStatus.CANCELLED},
    OrderStatus.CONFIRMED_BY_CLIENT: {OrderStatus.CONFIRMED, OrderStatus.CANCELLED},
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
    OrderStatus.CONFIRMED_BY_CLIENT: "Подтверждён клиентом",
    OrderStatus.CONFIRMED: "Подтверждён магазином",
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
    OrderStatus.PAID,
    OrderStatus.CONFIRMED,
    OrderStatus.SHIPPED,
    OrderStatus.READY_FOR_PICKUP,
    OrderStatus.DELIVERED,
]

CODFLOW_STEPPER_STEPS: list[str] = [
    OrderStatus.CONFIRMED_BY_CLIENT,
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

    # Map pre-step statuses to the first stepper step
    effective_status = current_status
    pending_confirmation_active = False
    pending_payment_active = False
    if current_status == OrderStatus.PENDING_CONFIRMATION and order_type == OrderType.CODFLOW:
        effective_status = OrderStatus.CONFIRMED_BY_CLIENT
        pending_confirmation_active = True
    elif current_status == OrderStatus.PENDING_PAYMENT and order_type == OrderType.PREPAID:
        effective_status = OrderStatus.PAID
        pending_payment_active = True

    # Find the index of the current status in the happy-path sequence
    try:
        current_idx = steps_sequence.index(effective_status)
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

        step = {
            "key": step_key,
            "label": get_status_label(step_key),
            "state": state,
        }

        # Override label for pre-step statuses
        if pending_confirmation_active and step_key == OrderStatus.CONFIRMED_BY_CLIENT:
            step["label"] = get_status_label(OrderStatus.PENDING_CONFIRMATION)
        if pending_payment_active and step_key == OrderStatus.PAID:
            step["label"] = get_status_label(OrderStatus.PENDING_PAYMENT)

        result.append(step)

    # Handle terminal statuses: replace "Доставлен" with the terminal step
    if is_terminal:
        # Remove the last step if it's "delivered" and pending (replace it with terminal)
        if result and result[-1]["key"] == OrderStatus.DELIVERED and result[-1]["state"] == "pending":
            result.pop()

        # For returned_to_supplier/refunded: chain through client_dont_pickup
        # Show client_dont_pickup as completed (red) then returned as active (blue)
        if current_status in {OrderStatus.RETURNED_TO_SUPPLIER, OrderStatus.REFUNDED}:
            # Remove delivered if still there
            if result and result[-1]["key"] == OrderStatus.DELIVERED and result[-1]["state"] == "pending":
                result.pop()
            result.append({
                "key": OrderStatus.CLIENT_DONT_PICKUP,
                "label": get_status_label(OrderStatus.CLIENT_DONT_PICKUP),
                "state": "completed",
                "color": "red",
            })
            color = "blue" if current_status == OrderStatus.RETURNED_TO_SUPPLIER else "red"
            result.append({
                "key": current_status,
                "label": get_status_label(current_status),
                "state": "active",
                "color": color,
            })
        else:
            # client_dont_pickup, cancelled — replace delivered with this terminal
            color = "red" if current_status in {OrderStatus.CLIENT_DONT_PICKUP, OrderStatus.CANCELLED} else "green"
            result.append({
                "key": current_status,
                "label": get_status_label(current_status),
                "state": "active",
                "color": color,
            })

    return result

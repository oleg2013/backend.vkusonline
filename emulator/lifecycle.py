"""Status lifecycle definitions for 5Post and Magnit emulators.

Each step is a tuple of (status, execution_status, mile_type) for 5Post
or just a status string for Magnit.
"""

from __future__ import annotations

from dataclasses import dataclass


# ── 5Post ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FivePostState:
    status: str
    execution_status: str
    mile_type: str | None = None


FIVEPOST_HAPPY_PATH: list[FivePostState] = [
    FivePostState("NEW", "CREATED", None),
    FivePostState("APPROVED", "APPROVED", None),
    FivePostState("IN_PROCESS", "RECEIVED_IN_WAREHOUSE_IN_DETAILS", "FIRST_MILE"),
    FivePostState("IN_PROCESS", "SORTED_IN_WAREHOUSE", "FIRST_MILE"),
    FivePostState("IN_PROCESS", "COMPLECTED_IN_WAREHOUSE", "FIRST_MILE"),
    FivePostState("IN_PROCESS", "READY_TO_BE_SHIPPED_FROM_WAREHOUSE", "FIRST_MILE"),
    FivePostState("IN_PROCESS", "SHIPPED", "LAST_MILE"),
    FivePostState("IN_PROCESS", "RECEIVED_IN_STORE", "LAST_MILE"),
    FivePostState("IN_PROCESS", "PLACED_IN_POSTAMAT", "LAST_MILE"),
    FivePostState("DONE", "PICKED_UP", "LAST_MILE"),
]

FIVEPOST_UNCLAIMED_PATH: list[FivePostState] = [
    # Starts after PLACED_IN_POSTAMAT
    FivePostState("UNCLAIMED", "READY_FOR_WITHDRAW_FROM_PICKUP_POINT", "REVERSE_LAST_MILE"),
    FivePostState("UNCLAIMED", "WITHDRAWN_FROM_PICKUP_POINT", "REVERSE_LAST_MILE"),
    FivePostState("UNCLAIMED", "RETURNED_TO_PARTNER", "REVERSE_FIRST_MILE"),
]

FIVEPOST_TERMINAL = {"DONE", "CANCELLED", "REJECTED"}

# All valid 5Post statuses
FIVEPOST_STATUSES = [
    "NEW", "APPROVED", "REJECTED", "IN_PROCESS", "DONE",
    "INTERRUPTED", "CANCELLED", "UNCLAIMED", "PROBLEM",
]

FIVEPOST_EXECUTION_STATUSES = [
    "CREATED", "APPROVED", "REJECTED", "PROBLEM",
    "RECEIVED_IN_WAREHOUSE_BY_PLACES", "PRESORTED",
    "RECEIVED_IN_WAREHOUSE_IN_DETAILS", "RECEIVED_IN_TRANSIT_WAREHOUSE",
    "SORTED_IN_WAREHOUSE", "PLACED_IN_CONSOLIDATION_CELL_IN_WAREHOUSE",
    "COMPLECTED_IN_WAREHOUSE", "READY_TO_BE_SHIPPED_FROM_WAREHOUSE",
    "SHIPPED", "RECEIVED_IN_STORE", "PLACED_IN_POSTAMAT",
    "PICKED_UP", "READY_FOR_WITHDRAW_FROM_PICKUP_POINT",
    "WITHDRAWN_FROM_PICKUP_POINT", "WAITING_FOR_REPICKUP",
    "READY_FOR_RETURN", "LOST", "READY_FOR_UTILIZE", "UTILIZED",
    "CANCELLED", "RETURNED_TO_PARTNER", "RECEIVED_IN_DROP",
]

FIVEPOST_MILE_TYPES = [
    "FIRST_MILE", "MIDDLE_MILE", "LAST_MILE",
    "REVERSE_LAST_MILE", "REVERSE_MIDDLE_MILE", "REVERSE_FIRST_MILE",
]


def fivepost_next_step(current: FivePostState) -> FivePostState | None:
    """Return the next state in the happy path, or None if terminal/not found."""
    for i, step in enumerate(FIVEPOST_HAPPY_PATH):
        if step.status == current.status and step.execution_status == current.execution_status:
            if i + 1 < len(FIVEPOST_HAPPY_PATH):
                return FIVEPOST_HAPPY_PATH[i + 1]
            return None

    # Check unclaimed path
    for i, step in enumerate(FIVEPOST_UNCLAIMED_PATH):
        if step.status == current.status and step.execution_status == current.execution_status:
            if i + 1 < len(FIVEPOST_UNCLAIMED_PATH):
                return FIVEPOST_UNCLAIMED_PATH[i + 1]
            return None

    return None


def fivepost_branch_unclaimed(current: FivePostState) -> FivePostState | None:
    """Branch to unclaimed path (only from PLACED_IN_POSTAMAT)."""
    if current.execution_status == "PLACED_IN_POSTAMAT":
        return FIVEPOST_UNCLAIMED_PATH[0]
    return None


# ── Magnit ───────────────────────────────────────────────────────────

MAGNIT_HAPPY_PATH: list[str] = [
    "NEW",
    "CREATED",
    "DELIVERING_STARTED",
    "ACCEPTED_AT_POINT",
    "ISSUED",
]

MAGNIT_RETURN_PATH: list[str] = [
    # Starts after ACCEPTED_AT_POINT
    "WAITING_RETURN",
    "RETURN_INITIATED",
    "RETURN_SEND_TO_WAREHOUSE",
    "RETURN_ACCEPTED_AT_WAREHOUSE",
    "RETURNED_TO_PROVIDER",
]

MAGNIT_TERMINAL = {"ISSUED", "RETURNED_TO_PROVIDER", "CANCELED_BY_PROVIDER", "DESTROYED", "REMOVED"}

MAGNIT_ALL_STATUSES = [
    "NEW", "CREATED", "DELIVERING_STARTED", "ACCEPTED_AT_POINT",
    "IN_COURIER_DELIVERY", "ISSUED", "DESTROYED",
    "ACCEPTED_AT_WAREHOUSE", "REMOVED", "WAITING_RETURN",
    "RETURN_INITIATED", "RETURN_SEND_TO_WAREHOUSE",
    "POSSIBLY_DEFECTED", "DEFECTED", "RETURN_ACCEPTED_AT_WAREHOUSE",
    "RETURNED_TO_PROVIDER", "CANCELED_BY_PROVIDER", "ACCEPTED_AT_CUSTOMS",
]


def magnit_next_step(current_status: str) -> str | None:
    """Return the next status in the happy path, or None if terminal/not found."""
    for i, s in enumerate(MAGNIT_HAPPY_PATH):
        if s == current_status:
            if i + 1 < len(MAGNIT_HAPPY_PATH):
                return MAGNIT_HAPPY_PATH[i + 1]
            return None

    # Check return path
    for i, s in enumerate(MAGNIT_RETURN_PATH):
        if s == current_status:
            if i + 1 < len(MAGNIT_RETURN_PATH):
                return MAGNIT_RETURN_PATH[i + 1]
            return None

    return None


def magnit_branch_return(current_status: str) -> str | None:
    """Branch to return path (only from ACCEPTED_AT_POINT)."""
    if current_status == "ACCEPTED_AT_POINT":
        return MAGNIT_RETURN_PATH[0]
    return None


# ── Available transitions ────────────────────────────────────────────

def fivepost_available_transitions(current: FivePostState) -> list[dict]:
    """Return list of available transitions from current state."""
    result = []
    ns = fivepost_next_step(current)
    if ns:
        result.append({"action": "next", "label": f"{ns.status}/{ns.execution_status} ({ns.mile_type or '-'})"})
    branch = fivepost_branch_unclaimed(current)
    if branch:
        result.append({"action": "unclaimed", "label": f"{branch.status}/{branch.execution_status} (UNCLAIMED)"})
    if current.status not in FIVEPOST_TERMINAL:
        result.append({"action": "cancel", "label": "CANCELLED/CANCELLED"})
    if current.status == "NEW":
        result.append({"action": "reject", "label": "REJECTED/REJECTED"})
    return result


def magnit_available_transitions(current_status: str) -> list[dict]:
    """Return list of available transitions from current status."""
    result = []
    ns = magnit_next_step(current_status)
    if ns:
        result.append({"action": "next", "label": ns})
    branch = magnit_branch_return(current_status)
    if branch:
        result.append({"action": "return", "label": branch + " (RETURN)"})
    if current_status not in MAGNIT_TERMINAL and current_status in ("NEW", "CREATED"):
        result.append({"action": "cancel", "label": "CANCELED_BY_PROVIDER"})
    return result

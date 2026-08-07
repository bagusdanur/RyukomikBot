"""Domain enums — single source of truth for status values."""

from enum import Enum


class AssignmentStatus(str, Enum):
    OPEN = "open"
    CLAIMED = "claimed"
    SUBMITTED = "submitted"
    REVISION = "revision"
    APPROVED = "approved"
    PAID = "paid"
    CANCELLED = "cancelled"


class PayoutStatus(str, Enum):
    ISSUED = "issued"
    PAID = "paid"
    REJECTED = "rejected"


class PayoutType(str, Enum):
    SCHEDULED = "scheduled"
    INSTANT = "instant"


class BonusStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class PaymentMethodType(str, Enum):
    BANK = "bank"
    EWALLET = "ewallet"
    QRIS = "qris"


class InvoiceStatus(str, Enum):
    DRAFT = "draft"
    FINAL = "final"
    CORRECTED = "corrected"
    VOID = "void"


class EventType(str, Enum):
    CREATED = "created"
    CLAIMED = "claimed"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REVISION = "revision"
    REJECTED = "rejected"
    PAID = "paid"
    REASSIGNED = "reassigned"


class PairState(str, Enum):
    WAITING_TL = "waiting_tl"
    READY_FOR_TS = "ready_for_ts"
    TS_REVISION = "ts_revision"
    FINAL_REVIEW = "final_review"
    COMPLETED = "completed"

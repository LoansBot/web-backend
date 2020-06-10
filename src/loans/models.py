"""Contains the response and request models for loans"""
from pydantic import BaseModel
import typing


class BasicLoanResponse(BaseModel):
    lender: str
    borrower: str
    currency_code: str
    currency_symbol: str
    currency_symbol_on_left: bool
    currency_exponent: int
    principal_minor: int
    principal_repayment_minor: int
    created_at: float
    last_repaid_at: float = None
    repaid_at: float = None
    unpaid_at: float = None
    deleted_at: float = None


class LoanEvent(BaseModel):
    event_type: str
    occurred_at: float


class AdminLoanEvent(LoanEvent):
    admin: str = None
    reason: str = None
    old_principal_minor: int
    new_principal_minor: int
    old_principal_repayment_minor: int
    new_principal_repayment_minor: int
    old_created_at: float
    new_created_at: float
    old_repaid_at: float = None
    new_repaid_at: float = None
    old_unpaid_at: float = None
    new_unpaid_at: float = None
    old_deleted_at: float = None
    new_deleted_at: float = None


class CreationLoanEvent(LoanEvent):
    creation_type: int
    creation_permalink: str


class UnpaidLoanEvent(LoanEvent):
    unpaid: bool


class RepaymentLoanEvent(LoanEvent):
    repayment_minor: int


class DetailedLoanResponse(BaseModel):
    events: typing.List[LoanEvent]
    basic: BasicLoanResponse


class LoansResponse(BaseModel):
    loans: typing.List[int]
    next_id: int
    previous_id: int

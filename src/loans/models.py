"""Contains the response and request models for loans"""
from pydantic import BaseModel
from datetime import datetime
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
    created_at: datetime
    last_repaid_at: datetime = None
    repaid_at: datetime = None
    unpaid_at: datetime = None
    deleted_at: datetime = None


class LoanEvent(BaseModel):
    event_type: str
    occurred_at: datetime


class AdminLoanEvent(LoanEvent):
    admin: str = None
    reason: str = None
    old_principal_minor: int
    new_principal_minor: int
    old_principal_repayment_minor: int
    new_principal_repayment_minor: int
    old_created_at: datetime
    new_created_at: datetime
    old_repaid_at: datetime
    new_repaid_at: datetime
    old_unpaid_at: datetime
    new_unpaid_at: datetime
    old_deleted_at: datetime
    new_deleted_at: datetime


class CreationLoanEvent(LoanEvent):
    creation_type: int
    creation_permalink: str


class UnpaidLoanEvent(LoanEvent):
    unpaid: bool


class RepaymentLoanEvent(LoanEvent):
    repayment_minor: int


class DetailedLoanResponse(BaseModel):
    events: typing.List[LoanEvent]
    lender: str
    borrower: str
    currency_code: str
    currency_symbol: str
    currency_symbol_on_left: bool
    currency_exponent: int
    principal_minor: int
    principal_repayment_minor: int
    created_at: datetime
    last_repaid_at: datetime = None
    repaid_at: datetime = None
    unpaid_at: datetime = None
    deleted_at: datetime = None


class LoansResponse(BaseModel):
    loans: typing.List[int]
    next_id: int
    previous_id: int

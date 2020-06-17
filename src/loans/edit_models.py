"""Contains the response and request models for editing loans"""
from pydantic import BaseModel, validator
import time
import re


VALID_USERNAME_REGEX = r'\A[A-Za-z0-9_\-]{3-20}\Z'


class LoanBasicFields(BaseModel):
    principal_minor: int = None
    principal_repayment_minor: int = None
    unpaid: bool = None
    created_at: float = None
    deleted: bool = None
    reason: str

    @validator('principal_minor')
    def principal_minor_must_be_positive(cls, v):
        if v is not None and v <= 0:
            raise ValueError('must be positive')
        return v

    @validator('principal_repayment_minor')
    def principal_repayment_minor_must_be_nonnegative(cls, v):
        if v is not None and v < 0:
            raise ValueError('must be non-negative')
        return v

    @validator('principal_repayment_minor')
    def principal_repayment_must_be_leq_principal(cls, v, values):
        if (
                v is not None
                and values.get('principal_minor') is not None
                and values['principal_minor'] < v):
            raise ValueError('must be less than or equal to principal_minor')
        return v

    @validator('created_at')
    def created_at_must_not_far_in_future(cls, v):
        if v is not None and v > time.time() * 10:
            return ValueError('must be reasonable; is this is MS instead of seconds?')
        return v

    @validator('reason')
    def reason_must_be_atleast_5_chars(cls, v):
        stripped = v.strip()
        if len(stripped) < 5:
            raise ValueError('must be at least 5 characters stripped')
        return stripped


class ChangeLoanUsers(BaseModel):
    lender_name: str
    borrower_name: str
    reason: str

    @validator('reason')
    def reason_must_be_atleast_5_chars(cls, v):
        stripped = v.strip()
        if len(stripped) < 5:
            raise ValueError('must be at least 5 characters stripped')
        return stripped

    @validator('lender_name', 'borrower_name')
    def lender_name_must_be_stripped(cls, v):
        if not re.match(VALID_USERNAME_REGEX, v):
            raise ValueError(f'must match regex {VALID_USERNAME_REGEX}')
        return v


class ChangeLoanCurrency(BaseModel):
    currency_code: str
    principal_minor: int
    principal_repayment_minor: int
    reason: str

    @validator('principal_minor')
    def principal_minor_must_be_positive(cls, v):
        if v is not None and v <= 0:
            raise ValueError('must be positive')
        return v

    @validator('principal_repayment_minor')
    def principal_repayment_minor_must_be_nonnegative(cls, v):
        if v is not None and v < 0:
            raise ValueError('must be non-negative')
        return v

    @validator('principal_repayment_minor')
    def principal_repayment_must_be_leq_principal(cls, v, values):
        if (
                v is not None
                and values.get('principal_minor') is not None
                and values['principal_minor'] < v):
            raise ValueError('must be less than or equal to principal_minor')
        return v

    @validator('reason')
    def reason_must_be_atleast_5_chars(cls, v):
        stripped = v.strip()
        if len(stripped) < 5:
            raise ValueError('must be at least 5 characters stripped')
        return stripped


class SingleLoanResponse(BaseModel):
    loan_id: int

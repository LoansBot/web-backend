"""The router for loans-related legacy endpoints"""
from fastapi import APIRouter
import legacy.loans.get_creation_info_php
import legacy.loans.get_dump_csv_php
import legacy.loans.get_loans_by_thread_php
import legacy.loans.get_request_thread_php
import legacy.loans.loans_php


router = APIRouter()
router.include_router(legacy.loans.get_creation_info_php.router)
router.include_router(legacy.loans.get_dump_csv_php.router)
router.include_router(legacy.loans.get_loans_by_thread_php.router)
router.include_router(legacy.loans.get_request_thread_php.router)
router.include_router(legacy.loans.loans_php.router)

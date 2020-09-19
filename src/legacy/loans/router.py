"""The router for loans-related legacy endpoints"""
from fastapi import APIRouter
import legacy.loans.get_creation_info_php
import legacy.loans.get_dump_csv_php


router = APIRouter()
router.include_router(legacy.loans.get_creation_info_php.router)
router.include_router(legacy.loans.get_dump_csv_php.router)

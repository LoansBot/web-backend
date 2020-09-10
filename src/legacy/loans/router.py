"""The router for loans-related legacy endpoints"""
from fastapi import APIRouter
import legacy.loans.get_creation_info_php


router = APIRouter()
router.include_router(legacy.loans.get_creation_info_php.router)

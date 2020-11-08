"""The router for trusts-related legacy endpoints"""
from fastapi import APIRouter
import legacy.trusts.get_promotion_blacklist_php


router = APIRouter()
router.include_router(legacy.trusts.get_promotion_blacklist_php.router)

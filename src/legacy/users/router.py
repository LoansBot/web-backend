"""The router for users-related legacy endpoints"""
from fastapi import APIRouter
import legacy.users.login_php


router = APIRouter()
router.include_router(legacy.users.login_php.router)

from fastapi import APIRouter

from app import store
from app.models import AppSettings, AppSettingsUpdate

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=AppSettings)
def get_settings():
    return store.get_app_settings()


@router.put("", response_model=AppSettings)
def update_settings(payload: AppSettingsUpdate):
    return store.update_app_settings(payload)

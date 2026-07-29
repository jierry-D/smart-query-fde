"""导入 API — Excel 上传"""

import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File

from ...core.deps import get_current_user, require_admin
from ...database import DatabaseConnector

router = APIRouter(prefix="/api/import", tags=["导入"])


@router.post("")
async def import_excel(file: UploadFile = File(...),
                       user: dict = Depends(get_current_user)):
    """上传 Excel 文件导入数据 (需 admin 或 leader)"""
    if user.get("role") not in ("admin", "leader"):
        raise HTTPException(403, "您没有导入权限 (需 admin 或 leader 角色)")

    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(400, "仅支持 .xlsx 文件")

    db = DatabaseConnector()

    # 保存到临时文件
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        # 使用 MVP 的导入逻辑
        from ...onboarding.importer import import_excel as do_import
        result = do_import(tmp_path, db, user)
        return result
    except Exception as e:
        raise HTTPException(500, f"导入失败: {str(e)}")
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

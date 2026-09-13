import os
from pathlib import Path

os.environ.setdefault("DATA_ENCRYPTION_KEY", "test-key-for-sheet-blaster")

from app.services.sheet_blaster import SheetBlaster


def test_sheet_blaster_stays_disabled_without_write_endpoint():
    worker = SheetBlaster()
    worker.url = ""
    worker.secret = ""
    worker.start()
    assert worker.task is None


def test_apps_script_uses_sheet_job_quota_and_keeps_internal_ids():
    source = (Path(__file__).parents[1] / "google_apps_script" / "Code.gs").read_text()
    assert "'Kuota per job', 'ID'" in source
    assert "const limit = quota_(sheet);" in source
    assert "row.splice(4, 3, id, now, 'Diproses')" in source
    assert "Math.min(500" not in source

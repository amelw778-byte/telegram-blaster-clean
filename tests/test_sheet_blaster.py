import os

os.environ.setdefault("DATA_ENCRYPTION_KEY", "test-key-for-sheet-blaster")

from app.services.sheet_blaster import SheetBlaster


def test_sheet_blaster_stays_disabled_without_write_endpoint():
    worker = SheetBlaster()
    worker.url = ""
    worker.secret = ""
    worker.start()
    assert worker.task is None

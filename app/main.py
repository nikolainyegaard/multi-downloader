import os

from app.config import migrate_from_legacy

migrate_from_legacy()

if os.getenv("ADMIN_MODE") == "1":
    from app.admin import app  # noqa: F401
else:
    from app.public import app  # noqa: F401

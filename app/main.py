from app.config import migrate_from_legacy

migrate_from_legacy()

from app.public import app  # noqa: F401, E402

import os

if os.getenv("ADMIN_MODE") == "1":
    from app.admin import app  # noqa: F401
else:
    from app.public import app  # noqa: F401

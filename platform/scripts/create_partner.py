"""Create a partner and print its API key ONCE.   python scripts/create_partner.py "Acme"
Run from the platform/ directory."""
import sys

sys.path.insert(0, ".")

from app.admin import create_partner, ensure_default_policy  # noqa: E402
from app.config import Settings  # noqa: E402
from app.db import (  # noqa: E402
    assert_schema_current,
    make_engine,
    make_session_factory,
    upgrade_to_head,
)

if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "Dev Partner"
    settings = Settings()
    if settings.env == "dev" and settings.auto_migrate:
        upgrade_to_head(settings.database_url)  # dev convenience; no-op if already up to date
    engine = make_engine(settings.database_url)
    assert_schema_current(engine)  # other environments must be migrated explicitly first
    with make_session_factory(engine)() as db:
        ensure_default_policy(db)
        db.commit()
        partner, key = create_partner(db, name)
    print(f"partner_id: {partner.id}\napi_key:    {key}\n(store the key now; it cannot be shown again)")

"""Create a partner and print its API key ONCE.   python scripts/create_partner.py "Acme"
Run from the platform/ directory."""
import sys

sys.path.insert(0, ".")

from app.admin import create_partner, ensure_default_policy  # noqa: E402
from app.config import Settings  # noqa: E402
from app.db import make_engine, make_session_factory  # noqa: E402
from app.models import Base  # noqa: E402

if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "Dev Partner"
    settings = Settings()
    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)
    with make_session_factory(engine)() as db:
        ensure_default_policy(db)
        db.commit()
        partner, key = create_partner(db, name)
    print(f"partner_id: {partner.id}\napi_key:    {key}\n(store the key now; it cannot be shown again)")

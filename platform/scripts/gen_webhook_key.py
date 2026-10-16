"""Print a new key for encrypting webhook signing secrets. Put it in .env, never in git.
    python scripts/gen_webhook_key.py   ->   CERTIVO_WEBHOOK_SECRET_KEY=<this value>"""
from cryptography.fernet import Fernet

print(Fernet.generate_key().decode())

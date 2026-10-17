"""Print a new attestation signing seed (base64url). Put it in .env, never in git."""
import base64
import os

print(base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode())

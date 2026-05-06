#!/usr/bin/env python3
"""
Generate MFA secret and QR code for admin user
"""

import pyotp
import qrcode
import sys


def generate_mfa_setup(username: str, issuer: str = "Certivo"):
    """Generate MFA secret and QR code"""
    
    # Generate secret
    secret = pyotp.random_base32()
    
    # Create TOTP URI
    totp = pyotp.TOTP(secret)
    uri = totp.provisioning_uri(name=username, issuer_name=issuer)
    
    # Generate QR code
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(uri)
    qr.make(fit=True)
    
    # Print to console (ASCII)
    qr.print_ascii()
    
    print(f"\nMFA Setup for {username}")
    print(f"=" * 50)
    print(f"Secret: {secret}")
    print(f"URI: {uri}")
    print(f"\nCurrent TOTP: {totp.now()}")
    print(f"\nScan QR code with authenticator app or enter secret manually")
    
    # Generate backup codes
    import secrets
    backup_codes = []
    for _ in range(10):
        code = secrets.token_hex(4).upper()
        backup_codes.append(code)
    
    print(f"\nBackup Codes (save securely):")
    print("-" * 50)
    for i, code in enumerate(backup_codes, 1):
        print(f"{i:2d}. {code}")
    
    return secret, backup_codes


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python generate_mfa_secret.py <username>")
        sys.exit(1)
    
    username = sys.argv[1]
    generate_mfa_setup(username)
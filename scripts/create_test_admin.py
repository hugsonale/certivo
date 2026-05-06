#!/usr/bin/env python3
"""
Create test admin user for CI/CD testing
"""

import asyncio
import asyncpg
import bcrypt
import pyotp
import os


async def create_test_admin():
    """Create test admin user with MFA"""
    
    postgres_url = os.getenv(
        "POSTGRES_URL",
        "postgresql://certivo:certivo@localhost:5432/certivo"
    )
    
    pool = await asyncpg.create_pool(postgres_url)
    
    # Generate password hash
    password = "SecurePassword123!"
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    
    # Generate MFA secret
    mfa_secret = pyotp.random_base32()
    
    async with pool.acquire() as conn:
        # Create test admin user
        await conn.execute(
            """
            INSERT INTO admin_users
            (user_id, username, email, password_hash, mfa_enabled, mfa_secret, active)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (username) DO UPDATE
            SET password_hash = $4, mfa_secret = $6
            """,
            "test_admin_001",
            "test_admin",
            "test_admin@certivo.local",
            password_hash,
            True,
            mfa_secret,
            True
        )
        
        # Assign super admin role
        await conn.execute(
            """
            INSERT INTO user_roles (user_id, role, assigned_by)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id) DO UPDATE SET role = $2
            """,
            "test_admin_001",
            "super_admin",
            "system"
        )
        
        # Create viewer role user
        await conn.execute(
            """
            INSERT INTO admin_users
            (user_id, username, email, password_hash, mfa_enabled, mfa_secret, active)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (username) DO UPDATE
            SET password_hash = $4
            """,
            "test_viewer_001",
            "test_viewer",
            "test_viewer@certivo.local",
            password_hash,
            False,
            None,
            True
        )
        
        await conn.execute(
            """
            INSERT INTO user_roles (user_id, role, assigned_by)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id) DO UPDATE SET role = $2
            """,
            "test_viewer_001",
            "viewer",
            "system"
        )
        
        # Create analyst role user
        await conn.execute(
            """
            INSERT INTO admin_users
            (user_id, username, email, password_hash, mfa_enabled, mfa_secret, active)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (username) DO UPDATE
            SET password_hash = $4
            """,
            "test_analyst_001",
            "test_analyst",
            "test_analyst@certivo.local",
            password_hash,
            False,
            None,
            True
        )
        
        await conn.execute(
            """
            INSERT INTO user_roles (user_id, role, assigned_by)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id) DO UPDATE SET role = $2
            """,
            "test_analyst_001",
            "analyst",
            "system"
        )
    
    await pool.close()
    
    print("✅ Test admin users created:")
    print(f"   - test_admin (super_admin) - Password: {password}")
    print(f"   - MFA Secret: {mfa_secret}")
    print(f"   - TOTP: {pyotp.TOTP(mfa_secret).now()}")
    print(f"   - test_viewer (viewer)")
    print(f"   - test_analyst (analyst)")


if __name__ == "__main__":
    asyncio.run(create_test_admin())
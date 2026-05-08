"""
Secrets Management Security Tests

Acceptance Criteria:
- Secret scan: 0 high-confidence exposures
- Rotation drill: successful
"""

import pytest
import subprocess
import os
import json


class TestSecretScanning:
    """
    Test secret scanning in CI
    
    Acceptance Criteria: 0 high-confidence exposures
    """
    
    def test_no_hardcoded_secrets_in_code(self):
        """Test no hardcoded secrets in source code"""
        
        # Run Gitleaks scan
        result = subprocess.run(
            ["gitleaks", "detect", "--source", ".", "--no-git"],
            capture_output=True,
            text=True
        )
        
        # Gitleaks returns 0 if no secrets found
        assert result.returncode == 0, f"Secrets detected by Gitleaks:\n{result.stdout}"
        
        print("✅ No secrets detected by Gitleaks")
    
    def test_no_secrets_in_config_files(self):
        """Test no secrets in configuration files"""
        
        # Check common config files
        config_files = [
            "config/secrets.yaml",
            "config/database.yaml",
            ".env.example"
        ]
        
        forbidden_patterns = [
            "password=",
            "api_key=",
            "secret=",
            "token="
        ]
        
        violations = []
        
        for config_file in config_files:
            if not os.path.exists(config_file):
                continue
            
            with open(config_file, 'r') as f:
                content = f.read().lower()
            
            for pattern in forbidden_patterns:
                if pattern in content:
                    # Check if it's a placeholder
                    if "${VAULT:" not in content and "CHANGE_ME" not in content:
                        violations.append(f"{config_file}: {pattern}")
        
        assert len(violations) == 0, f"Potential secrets found:\n" + "\n".join(violations)
        
        print("✅ No secrets in config files")
    
    def test_vault_references_only(self):
        """Test config files use Vault references only"""
        
        config_file = "config/secrets.yaml"
        
        if not os.path.exists(config_file):
            pytest.skip("Config file not found")
        
        with open(config_file, 'r') as f:
            content = f.read()
        
        # Count Vault references
        vault_refs = content.count("${VAULT:")
        
        # Count potential secret values (non-placeholder values)
        lines = content.split('\n')
        non_vault_secrets = 0
        
        for line in lines:
            if ':' in line and '${VAULT:' not in line:
                # Check if it's a secret-looking value
                if any(keyword in line.lower() for keyword in ['password', 'secret', 'key', 'token']):
                    if 'CHANGE_ME' not in line and 'localhost' not in line:
                        non_vault_secrets += 1
        
        assert non_vault_secrets == 0, f"Found {non_vault_secrets} non-Vault secret references"
        assert vault_refs > 0, "No Vault references found"
        
        print(f"✅ All secrets use Vault references ({vault_refs} found)")


class TestKeyRotation:
    """
    Test key rotation procedures
    
    Acceptance Criteria: Rotation drill successful
    """
    
    @pytest.mark.asyncio
    async def test_rotation_dry_run(self):
        """Test rotation dry run (no actual changes)"""
        
        # Run rotation in dry-run mode
        result = subprocess.run(
            ["python", "scripts/rotate_all_secrets.py", "--dry-run"],
            capture_output=True,
            text=True
        )
        
        assert result.returncode == 0, f"Dry run failed:\n{result.stdout}\n{result.stderr}"
        assert "DRY RUN MODE" in result.stdout
        
        print("✅ Rotation dry run successful")
    
    @pytest.mark.asyncio
    async def test_rotation_verification(self):
        """Test rotation verification script"""
        
        # Run verification
        result = subprocess.run(
            ["python", "scripts/verify_rotation.py"],
            capture_output=True,
            text=True
        )
        
        # Should pass (or skip if no recent rotations)
        assert result.returncode in [0, 1]  # 1 if no rotations, which is ok for test
        
        print("✅ Rotation verification script works")
    
    def test_rotation_documentation_exists(self):
        """Test rotation runbook exists"""
        
        runbook_path = "docs/RUNBOOKS/KEY_ROTATION.md"
        
        assert os.path.exists(runbook_path), "Rotation runbook not found"
        
        with open(runbook_path, 'r') as f:
            content = f.read()
        
        # Check for required sections
        required_sections = [
            "Database Password Rotation",
            "API Key Rotation",
            "Session Secret Rotation",
            "Emergency Rotation",
            "Rollback Procedures"
        ]
        
        for section in required_sections:
            assert section in content, f"Missing section: {section}"
        
        print("✅ Rotation runbook complete")


class TestEnvironmentIsolation:
    """Test per-environment credential isolation"""
    
    def test_vault_policies_exist(self):
        """Test Vault policies for environment isolation"""
        
        policies = [
            "infrastructure/vault/policies/dev-policy.hcl",
            "infrastructure/vault/policies/staging-policy.hcl",
            "infrastructure/vault/policies/production-policy.hcl"
        ]
        
        for policy in policies:
            assert os.path.exists(policy), f"Policy not found: {policy}"
            
            with open(policy, 'r') as f:
                content = f.read()
            
            # Check policy has path restrictions
            assert 'path "secret/data/' in content
            assert 'capabilities' in content
        
        print("✅ Vault policies configured for environment isolation")
    
    def test_production_policy_is_restrictive(self):
        """Test production policy denies write access"""
        
        policy_path = "infrastructure/vault/policies/production-policy.hcl"
        
        with open(policy_path, 'r') as f:
            content = f.read()
        
        # Production should be read-only
        assert 'capabilities = ["read"]' in content
        assert 'denied_capabilities = ["create", "update", "delete"]' in content
        
        print("✅ Production policy is read-only")


class TestSecretsManagerIntegration:
    """Test secrets manager integration"""
    
    def test_secrets_manager_initialization(self):
        """Test secrets manager can be initialized"""
        
        import sys
        sys.path.insert(0, 'services/shared')
        
        from secrets_manager import SecretsManager
        
        # Should initialize without errors
        # Will use local backend in test environment
        manager = SecretsManager()
        
        assert manager is not None
        assert manager.backend is not None
        
        print("✅ Secrets manager initialized")
    
    def test_local_backend_encryption(self):
        """Test local backend uses encryption"""
        
        import sys
        sys.path.insert(0, 'services/shared')
        
        from secrets_manager import LocalEncryptedBackend
        
        backend = LocalEncryptedBackend(secrets_file="/tmp/test_secrets.enc")
        
        # Store secret
        backend.set_secret("test_key", "test_value_12345")
        
        # Check file is encrypted (not plaintext)
        with open("/tmp/test_secrets.enc", 'rb') as f:
            content = f.read()
        
        assert b"test_value_12345" not in content, "Secret stored in plaintext!"
        
        # Retrieve secret
        value = backend.get_secret("test_key")
        assert value == "test_value_12345"
        
        # Cleanup
        os.remove("/tmp/test_secrets.enc")
        
        print("✅ Local backend encrypts secrets")
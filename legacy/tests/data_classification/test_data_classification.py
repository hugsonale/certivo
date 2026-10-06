"""
Data Classification Tests

Acceptance Criteria:
1. All fields labeled with classification level
2. Data inventory maintained with owner and retention
"""

import pytest
import asyncio
import asyncpg
import sys
import os

sys.path.insert(0, 'services/shared')
sys.path.insert(0, 'config')

from data_classification import (
    DataClassification,
    RetentionPolicy,
    registry
)
from data_classifications import initialize_certivo_data_classifications


class TestDataClassification:
    """Test data classification system"""
    
    def test_initialize_classifications(self):
        """Test initialization of Certivo data classifications"""
        
        print("\n" + "="*60)
        print("TEST: Data Classification Initialization")
        print("="*60)
        
        # Initialize classifications
        initialize_certivo_data_classifications()
        
        # Verify registry populated
        report = registry.generate_inventory_report()
        
        print(f"\n✓ Data Inventory Initialized:")
        print(f"  Tables: {report['summary']['total_tables']}")
        print(f"  Fields: {report['summary']['total_fields']}")
        print(f"  PII Tables: {report['summary']['pii_tables']}")
        print(f"  Biometric-Adjacent Tables: {report['summary']['biometric_adjacent_tables']}")
        
        assert report['summary']['total_tables'] > 0
        assert report['summary']['total_fields'] > 0
        
        print("\n✅ Classification initialization test passed")
    
    def test_field_classifications(self):
        """
        ACCEPTANCE CRITERIA 1: All fields labeled
        
        Verify every field has a classification
        """
        
        print("\n" + "="*60)
        print("ACCEPTANCE TEST: All Fields Labeled")
        print("="*60)
        
        initialize_certivo_data_classifications()
        
        # Check each table
        unlabeled_fields = []
        
        for table_name, entry in registry.inventory.items():
            for field in entry.fields:
                if not field.classification:
                    unlabeled_fields.append(f"{table_name}.{field.field_name}")
        
        print(f"\n✓ Total Tables: {len(registry.inventory)}")
        print(f"✓ Total Fields Checked: {sum(len(e.fields) for e in registry.inventory.values())}")
        print(f"✓ Unlabeled Fields: {len(unlabeled_fields)}")
        
        if unlabeled_fields:
            print("\n⚠️  Unlabeled fields found:")
            for field in unlabeled_fields:
                print(f"  - {field}")
        
        assert len(unlabeled_fields) == 0, \
            f"Found {len(unlabeled_fields)} unlabeled fields"
        
        print("\n" + "="*60)
        print("✅ ACCEPTANCE CRITERIA MET: All Fields Labeled")
        print("="*60)
    
    def test_data_inventory_completeness(self):
        """
        ACCEPTANCE CRITERIA 2: Data inventory maintained
        
        Verify inventory has owner and retention for all tables
        """
        
        print("\n" + "="*60)
        print("ACCEPTANCE TEST: Data Inventory Complete")
        print("="*60)
        
        initialize_certivo_data_classifications()
        
        missing_metadata = []
        
        for table_name, entry in registry.inventory.items():
            issues = []
            
            # Check required metadata
            if not entry.data_owner:
                issues.append("missing data_owner")
            
            if not entry.technical_owner:
                issues.append("missing technical_owner")
            
            if not entry.default_retention_policy:
                issues.append("missing retention_policy")
            
            if not entry.purpose:
                issues.append("missing purpose")
            
            if issues:
                missing_metadata.append({
                    "table": table_name,
                    "issues": issues
                })
        
        print(f"\n✓ Total Tables: {len(registry.inventory)}")
        print(f"✓ Tables with Complete Metadata: {len(registry.inventory) - len(missing_metadata)}")
        print(f"✓ Tables with Missing Metadata: {len(missing_metadata)}")
        
        if missing_metadata:
            print("\n⚠️  Tables with missing metadata:")
            for item in missing_metadata:
                print(f"  - {item['table']}: {', '.join(item['issues'])}")
        
        assert len(missing_metadata) == 0, \
            f"Found {len(missing_metadata)} tables with incomplete metadata"
        
        print("\n" + "="*60)
        print("✅ ACCEPTANCE CRITERIA MET: Data Inventory Complete")
        print("="*60)
    
    def test_classification_levels(self):
        """Test classification level distribution"""
        
        print("\n" + "="*60)
        print("TEST: Classification Level Distribution")
        print("="*60)
        
        initialize_certivo_data_classifications()
        
        # Get tables by classification
        public_tables = registry.get_tables_by_classification(DataClassification.PUBLIC)
        internal_tables = registry.get_tables_by_classification(DataClassification.INTERNAL)
        sensitive_tables = registry.get_tables_by_classification(DataClassification.SENSITIVE)
        biometric_tables = registry.get_tables_by_classification(DataClassification.BIOMETRIC_ADJACENT)
        
        print(f"\n✓ Classification Breakdown:")
        print(f"  PUBLIC: {len(public_tables)} tables")
        print(f"  INTERNAL: {len(internal_tables)} tables")
        print(f"  SENSITIVE: {len(sensitive_tables)} tables")
        print(f"  BIOMETRIC_ADJACENT: {len(biometric_tables)} tables")
        
        # Verify biometric-adjacent tables exist
        assert len(biometric_tables) > 0, "No biometric-adjacent tables found"
        
        print("\n✅ Classification level test passed")
    
    def test_retention_policies(self):
        """Test retention policy distribution"""
        
        print("\n" + "="*60)
        print("TEST: Retention Policy Distribution")
        print("="*60)
        
        initialize_certivo_data_classifications()
        
        # Get tables by retention
        short_term = registry.get_tables_by_retention(RetentionPolicy.SHORT_TERM)
        medium_term = registry.get_tables_by_retention(RetentionPolicy.MEDIUM_TERM)
        long_term = registry.get_tables_by_retention(RetentionPolicy.LONG_TERM)
        indefinite = registry.get_tables_by_retention(RetentionPolicy.INDEFINITE)
        
        print(f"\n✓ Retention Policy Breakdown:")
        print(f"  SHORT_TERM (7 days): {len(short_term)} tables")
        print(f"  MEDIUM_TERM (90 days): {len(medium_term)} tables")
        print(f"  LONG_TERM (7 years): {len(long_term)} tables")
        print(f"  INDEFINITE: {len(indefinite)} tables")
        
        # Verify explainability has long-term retention
        explainability_tables = [
            t for t in long_term 
            if 'explainability' in t.table_name.lower()
        ]
        
        assert len(explainability_tables) > 0, \
            "Explainability records should have long-term retention"
        
        print("\n✅ Retention policy test passed")
    
    def test_pii_identification(self):
        """Test PII field identification"""
        
        print("\n" + "="*60)
        print("TEST: PII Field Identification")
        print("="*60)
        
        initialize_certivo_data_classifications()
        
        pii_tables = registry.get_pii_tables()
        
        print(f"\n✓ Tables containing PII: {len(pii_tables)}")
        
        for entry in pii_tables:
            pii_fields = entry.get_pii_fields()
            print(f"\n  {entry.table_name}:")
            for field in pii_fields:
                print(f"    - {field.field_name} ({field.classification.value})")
        
        assert len(pii_tables) > 0, "No PII tables identified"
        
        print("\n✅ PII identification test passed")
    
    def test_biometric_adjacent_identification(self):
        """Test biometric-adjacent field identification"""
        
        print("\n" + "="*60)
        print("TEST: Biometric-Adjacent Field Identification")
        print("="*60)
        
        initialize_certivo_data_classifications()
        
        biometric_tables = registry.get_biometric_adjacent_tables()
        
        print(f"\n✓ Tables with biometric-adjacent data: {len(biometric_tables)}")
        
        for entry in biometric_tables:
            biometric_fields = entry.get_biometric_adjacent_fields()
            print(f"\n  {entry.table_name}:")
            for field in biometric_fields:
                print(f"    - {field.field_name}: {field.description}")
        
        assert len(biometric_tables) > 0, "No biometric-adjacent tables identified"
        
        # Verify liveness scores are classified as biometric-adjacent
        liveness_fields = []
        for entry in biometric_tables:
            for field in entry.get_biometric_adjacent_fields():
                if 'liveness' in field.field_name.lower() or 'score' in field.field_name.lower():
                    liveness_fields.append(field)
        
        assert len(liveness_fields) > 0, \
            "Liveness scores should be classified as biometric-adjacent"
        
        print("\n✅ Biometric-adjacent identification test passed")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
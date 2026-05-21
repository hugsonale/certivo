"""
Data Classification System
Classify and track all data fields with ownership and retention
"""

from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import json
import logging

logger = logging.getLogger(__name__)


class DataClassification(str, Enum):
    """
    Data classification levels
    
    Based on sensitivity and regulatory requirements
    """
    PUBLIC = "public"                          # Publicly available data
    INTERNAL = "internal"                      # Internal business data
    SENSITIVE = "sensitive"                    # Personally identifiable information
    BIOMETRIC_ADJACENT = "biometric_adjacent"  # Near-biometric data requiring special handling


class RetentionPolicy(str, Enum):
    """Data retention policies"""
    SHORT_TERM = "short_term"      # 7 days
    MEDIUM_TERM = "medium_term"    # 90 days
    LONG_TERM = "long_term"        # 7 years
    INDEFINITE = "indefinite"      # No automatic deletion


@dataclass
class FieldClassification:
    """Classification for a single data field"""
    field_name: str
    table_name: str
    classification: DataClassification
    
    # Metadata
    description: str
    data_type: str
    
    # Ownership
    owner: str
    business_unit: str
    
    # Retention
    retention_policy: RetentionPolicy
    retention_days: Optional[int] = None
    
    # Regulatory
    pii: bool = False  # Personally Identifiable Information
    phi: bool = False  # Protected Health Information
    gdpr_applicable: bool = False
    ccpa_applicable: bool = False
    
    # Security
    encryption_required: bool = False
    encryption_at_rest: bool = False
    encryption_in_transit: bool = False
    access_logging_required: bool = False
    
    # Usage
    purpose: str = ""
    legal_basis: Optional[str] = None
    
    # Audit
    last_reviewed: datetime = field(default_factory=datetime.utcnow)
    reviewed_by: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "field_name": self.field_name,
            "table_name": self.table_name,
            "classification": self.classification.value,
            "description": self.description,
            "data_type": self.data_type,
            "owner": self.owner,
            "business_unit": self.business_unit,
            "retention_policy": self.retention_policy.value,
            "retention_days": self.retention_days,
            "pii": self.pii,
            "phi": self.phi,
            "gdpr_applicable": self.gdpr_applicable,
            "ccpa_applicable": self.ccpa_applicable,
            "encryption_required": self.encryption_required,
            "encryption_at_rest": self.encryption_at_rest,
            "encryption_in_transit": self.encryption_in_transit,
            "access_logging_required": self.access_logging_required,
            "purpose": self.purpose,
            "legal_basis": self.legal_basis,
            "last_reviewed": self.last_reviewed.isoformat(),
            "reviewed_by": self.reviewed_by
        }


@dataclass
class DataInventoryEntry:
    """Complete data inventory entry for a table"""
    table_name: str
    database_name: str
    schema_name: str
    
    # Classification
    fields: List[FieldClassification]
    
    # Ownership
    data_owner: str
    technical_owner: str
    business_unit: str
    
    # Purpose
    purpose: str
    legal_basis: str
    
    # Security
    encryption_enabled: bool
    access_controls: List[str]
    
    # Compliance
    contains_pii: bool
    contains_phi: bool
    gdpr_applicable: bool
    ccpa_applicable: bool
    
    # Retention
    default_retention_policy: RetentionPolicy
    retention_days: Optional[int] = None
    
    # Audit
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_updated: datetime = field(default_factory=datetime.utcnow)
    last_reviewed: datetime = field(default_factory=datetime.utcnow)
    reviewed_by: Optional[str] = None
    
    def get_highest_classification(self) -> DataClassification:
        """Get highest classification level across all fields"""
        
        classifications = [f.classification for f in self.fields]
        
        # Order: PUBLIC < INTERNAL < SENSITIVE < BIOMETRIC_ADJACENT
        if DataClassification.BIOMETRIC_ADJACENT in classifications:
            return DataClassification.BIOMETRIC_ADJACENT
        elif DataClassification.SENSITIVE in classifications:
            return DataClassification.SENSITIVE
        elif DataClassification.INTERNAL in classifications:
            return DataClassification.INTERNAL
        else:
            return DataClassification.PUBLIC
    
    def get_pii_fields(self) -> List[FieldClassification]:
        """Get all PII fields"""
        return [f for f in self.fields if f.pii]
    
    def get_biometric_adjacent_fields(self) -> List[FieldClassification]:
        """Get all biometric-adjacent fields"""
        return [f for f in self.fields if f.classification == DataClassification.BIOMETRIC_ADJACENT]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "table_name": self.table_name,
            "database_name": self.database_name,
            "schema_name": self.schema_name,
            "fields": [f.to_dict() for f in self.fields],
            "data_owner": self.data_owner,
            "technical_owner": self.technical_owner,
            "business_unit": self.business_unit,
            "purpose": self.purpose,
            "legal_basis": self.legal_basis,
            "encryption_enabled": self.encryption_enabled,
            "access_controls": self.access_controls,
            "contains_pii": self.contains_pii,
            "contains_phi": self.contains_phi,
            "gdpr_applicable": self.gdpr_applicable,
            "ccpa_applicable": self.ccpa_applicable,
            "default_retention_policy": self.default_retention_policy.value,
            "retention_days": self.retention_days,
            "highest_classification": self.get_highest_classification().value,
            "pii_field_count": len(self.get_pii_fields()),
            "biometric_adjacent_field_count": len(self.get_biometric_adjacent_fields()),
            "created_at": self.created_at.isoformat(),
            "last_updated": self.last_updated.isoformat(),
            "last_reviewed": self.last_reviewed.isoformat(),
            "reviewed_by": self.reviewed_by
        }


class DataClassificationRegistry:
    """
    Data Classification Registry
    
    Central registry for all data classifications and inventory
    """
    
    def __init__(self):
        self.inventory: Dict[str, DataInventoryEntry] = {}
        self.classifications: Dict[str, Dict[str, FieldClassification]] = {}
    
    def register_table(self, entry: DataInventoryEntry):
        """
        Register table in data inventory
        
        Args:
            entry: Data inventory entry
        """
        
        table_key = f"{entry.database_name}.{entry.schema_name}.{entry.table_name}"
        self.inventory[table_key] = entry
        
        # Index field classifications
        for field in entry.fields:
            field_key = f"{table_key}.{field.field_name}"
            
            if table_key not in self.classifications:
                self.classifications[table_key] = {}
            
            self.classifications[table_key][field.field_name] = field
        
        logger.info(
            f"📋 Registered table: {table_key}\n"
            f"   Classification: {entry.get_highest_classification().value}\n"
            f"   Fields: {len(entry.fields)}\n"
            f"   PII Fields: {len(entry.get_pii_fields())}\n"
            f"   Owner: {entry.data_owner}"
        )
    
    def get_table_inventory(self, table_name: str) -> Optional[DataInventoryEntry]:
        """Get inventory entry for table"""
        return self.inventory.get(table_name)
    
    def get_field_classification(
        self,
        table_name: str,
        field_name: str
    ) -> Optional[FieldClassification]:
        """Get classification for specific field"""
        
        if table_name in self.classifications:
            return self.classifications[table_name].get(field_name)
        
        return None
    
    def get_tables_by_classification(
        self,
        classification: DataClassification
    ) -> List[DataInventoryEntry]:
        """Get all tables with specific classification"""
        
        return [
            entry for entry in self.inventory.values()
            if entry.get_highest_classification() == classification
        ]
    
    def get_pii_tables(self) -> List[DataInventoryEntry]:
        """Get all tables containing PII"""
        return [entry for entry in self.inventory.values() if entry.contains_pii]
    
    def get_biometric_adjacent_tables(self) -> List[DataInventoryEntry]:
        """Get all tables containing biometric-adjacent data"""
        return [
            entry for entry in self.inventory.values()
            if len(entry.get_biometric_adjacent_fields()) > 0
        ]
    
    def get_tables_by_owner(self, owner: str) -> List[DataInventoryEntry]:
        """Get all tables owned by specific person/team"""
        return [entry for entry in self.inventory.values() if entry.data_owner == owner]
    
    def get_tables_by_retention(
        self,
        retention_policy: RetentionPolicy
    ) -> List[DataInventoryEntry]:
        """Get all tables with specific retention policy"""
        return [
            entry for entry in self.inventory.values()
            if entry.default_retention_policy == retention_policy
        ]
    
    def generate_inventory_report(self) -> Dict[str, Any]:
        """Generate comprehensive inventory report"""
        
        total_tables = len(self.inventory)
        total_fields = sum(len(entry.fields) for entry in self.inventory.values())
        
        # Classification breakdown
        classification_counts = {
            DataClassification.PUBLIC: 0,
            DataClassification.INTERNAL: 0,
            DataClassification.SENSITIVE: 0,
            DataClassification.BIOMETRIC_ADJACENT: 0
        }
        
        for entry in self.inventory.values():
            classification_counts[entry.get_highest_classification()] += 1
        
        # PII/PHI counts
        pii_tables = len(self.get_pii_tables())
        biometric_adjacent_tables = len(self.get_biometric_adjacent_tables())
        
        # Retention breakdown
        retention_counts = {
            RetentionPolicy.SHORT_TERM: 0,
            RetentionPolicy.MEDIUM_TERM: 0,
            RetentionPolicy.LONG_TERM: 0,
            RetentionPolicy.INDEFINITE: 0
        }
        
        for entry in self.inventory.values():
            retention_counts[entry.default_retention_policy] += 1
        
        report = {
            "generated_at": datetime.utcnow().isoformat(),
            "summary": {
                "total_tables": total_tables,
                "total_fields": total_fields,
                "pii_tables": pii_tables,
                "biometric_adjacent_tables": biometric_adjacent_tables
            },
            "classification_breakdown": {
                k.value: v for k, v in classification_counts.items()
            },
            "retention_breakdown": {
                k.value: v for k, v in retention_counts.items()
            },
            "compliance": {
                "gdpr_applicable_tables": len([
                    e for e in self.inventory.values() if e.gdpr_applicable
                ]),
                "ccpa_applicable_tables": len([
                    e for e in self.inventory.values() if e.ccpa_applicable
                ])
            }
        }
        
        logger.info(
            f"📊 Data Inventory Report:\n"
            f"   Total Tables: {total_tables}\n"
            f"   Total Fields: {total_fields}\n"
            f"   PII Tables: {pii_tables}\n"
            f"   Biometric-Adjacent Tables: {biometric_adjacent_tables}\n"
            f"   Classification: PUBLIC={classification_counts[DataClassification.PUBLIC]}, "
            f"INTERNAL={classification_counts[DataClassification.INTERNAL]}, "
            f"SENSITIVE={classification_counts[DataClassification.SENSITIVE]}, "
            f"BIOMETRIC={classification_counts[DataClassification.BIOMETRIC_ADJACENT]}"
        )
        
        return report
    
    def export_inventory(self, filepath: str):
        """Export inventory to JSON file"""
        
        export_data = {
            "export_date": datetime.utcnow().isoformat(),
            "inventory": [entry.to_dict() for entry in self.inventory.values()]
        }
        
        with open(filepath, 'w') as f:
            json.dump(export_data, f, indent=2)
        
        logger.info(f"📤 Inventory exported to: {filepath}")


# Global registry instance
registry = DataClassificationRegistry()
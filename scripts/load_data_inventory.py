#!/usr/bin/env python3
import asyncio
import asyncpg
import sys
sys.path.insert(0, 'config')
from data_classifications import initialize_certivo_data_classifications, registry

async def load_inventory():
    # Initialize classifications
    initialize_certivo_data_classifications()
    
    # Connect to database
    conn = await asyncpg.connect(
        "postgresql://certivo:certivo@localhost:5432/certivo"
    )
    
    # Load each table
    for table_key, entry in registry.inventory.items():
        # Insert into data_inventory
        inventory_id = await conn.fetchval("""
            INSERT INTO data_inventory (
                table_name, database_name, schema_name,
                data_owner, technical_owner, business_unit,
                purpose, legal_basis, highest_classification,
                encryption_enabled, access_controls,
                contains_pii, contains_phi,
                gdpr_applicable, ccpa_applicable,
                default_retention_policy, retention_days
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17)
            RETURNING id
        """,
            entry.table_name, entry.database_name, entry.schema_name,
            entry.data_owner, entry.technical_owner, entry.business_unit,
            entry.purpose, entry.legal_basis,
            entry.get_highest_classification().value,
            entry.encryption_enabled, entry.access_controls,
            entry.contains_pii, entry.contains_phi,
            entry.gdpr_applicable, entry.ccpa_applicable,
            entry.default_retention_policy.value, entry.retention_days
        )
        
        # Insert field classifications
        for field in entry.fields:
            await conn.execute("""
                INSERT INTO field_classifications (
                    data_inventory_id, field_name, classification,
                    description, data_type, owner, business_unit,
                    retention_policy, retention_days,
                    pii, phi, gdpr_applicable, ccpa_applicable,
                    encryption_required, encryption_at_rest,
                    encryption_in_transit, access_logging_required,
                    purpose, legal_basis
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19)
            """,
                inventory_id, field.field_name, field.classification.value,
                field.description, field.data_type, field.owner, field.business_unit,
                field.retention_policy.value, field.retention_days,
                field.pii, field.phi, field.gdpr_applicable, field.ccpa_applicable,
                field.encryption_required, field.encryption_at_rest,
                field.encryption_in_transit, field.access_logging_required,
                field.purpose, field.legal_basis
            )
    
    await conn.close()
    print("✅ Data inventory loaded into database")

if __name__ == "__main__":
    asyncio.run(load_inventory())
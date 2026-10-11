"""
Policy Engine
Customer-specific risk policies without code changes
"""

import asyncpg
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import json
import logging

from risk_scoring import RiskFactor, RiskScoringEngine

logger = logging.getLogger(__name__)


class PolicyAction(str, Enum):
    """Policy decision actions"""
    APPROVE = "approve"
    DENY = "deny"
    REVIEW = "review"
    CHALLENGE = "challenge"
    STEP_UP = "step_up"  # Require additional verification


@dataclass
class RiskPolicy:
    """Customer risk policy configuration"""
    policy_id: str
    customer_id: str
    policy_name: str
    
    # Risk thresholds
    approve_threshold: float  # Below this = approve
    review_threshold: float   # Above approve, below review = challenge
    deny_threshold: float     # Above this = deny
    
    # Factor weights
    factor_weights: Dict[RiskFactor, float]
    
    # Custom rules (JSON)
    custom_rules: Dict[str, Any]
    
    # Policy metadata
    version: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
    created_by: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "customer_id": self.customer_id,
            "policy_name": self.policy_name,
            "approve_threshold": self.approve_threshold,
            "review_threshold": self.review_threshold,
            "deny_threshold": self.deny_threshold,
            "factor_weights": {k.value: v for k, v in self.factor_weights.items()},
            "custom_rules": self.custom_rules,
            "version": self.version,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": self.created_by
        }


class PolicyEngine:
    """
    Policy engine for customer-specific risk policies
    
    Features:
    - Per-customer policy configuration
    - Dynamic policy updates (no code changes)
    - Policy versioning
    - Custom rule evaluation
    - Policy audit trail
    """
    
    def __init__(self, postgres_pool: asyncpg.Pool):
        self.postgres = postgres_pool
        
        # Policy cache (refreshed periodically)
        self._policy_cache: Dict[str, RiskPolicy] = {}
    
    async def create_policy(
        self,
        customer_id: str,
        policy_name: str,
        approve_threshold: float,
        review_threshold: float,
        deny_threshold: float,
        factor_weights: Optional[Dict[RiskFactor, float]] = None,
        custom_rules: Optional[Dict[str, Any]] = None,
        created_by: str = "system"
    ) -> RiskPolicy:
        """
        Create new risk policy
        
        Args:
            customer_id: Customer identifier
            policy_name: Human-readable policy name
            approve_threshold: Approval threshold (0.0-1.0)
            review_threshold: Review threshold
            deny_threshold: Denial threshold
            factor_weights: Custom factor weights
            custom_rules: Additional custom rules
            created_by: Policy creator
        
        Returns:
            Created policy
        """
        
        # Validate thresholds
        if not (0 <= approve_threshold < review_threshold < deny_threshold <= 1.0):
            raise ValueError(
                "Thresholds must be: 0 <= approve < review < deny <= 1.0"
            )
        
        # Use default weights if not provided
        if factor_weights is None:
            factor_weights = RiskScoringEngine.DEFAULT_WEIGHTS.copy()
        
        # Validate weights
        total = sum(factor_weights.values())
        if abs(total - 1.0) > 0.001:
            raise ValueError(f"Factor weights must sum to 1.0, got {total}")
        
        # Generate policy ID
        policy_id = f"POL-{customer_id}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        
        now = datetime.utcnow()
        
        # Store in database
        async with self.postgres.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO risk_policies
                (policy_id, customer_id, policy_name, approve_threshold,
                 review_threshold, deny_threshold, factor_weights, custom_rules,
                 version, is_active, created_at, updated_at, created_by)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                """,
                policy_id,
                customer_id,
                policy_name,
                approve_threshold,
                review_threshold,
                deny_threshold,
                json.dumps({k.value: v for k, v in factor_weights.items()}),
                json.dumps(custom_rules or {}),
                1,  # version
                True,  # is_active
                now,
                now,
                created_by
            )
        
        policy = RiskPolicy(
            policy_id=policy_id,
            customer_id=customer_id,
            policy_name=policy_name,
            approve_threshold=approve_threshold,
            review_threshold=review_threshold,
            deny_threshold=deny_threshold,
            factor_weights=factor_weights,
            custom_rules=custom_rules or {},
            version=1,
            is_active=True,
            created_at=now,
            updated_at=now,
            created_by=created_by
        )
        
        # Update cache
        self._policy_cache[customer_id] = policy
        
        logger.info(
            f"✅ Policy created: {policy_id}\n"
            f"   Customer: {customer_id}\n"
            f"   Thresholds: approve={approve_threshold}, review={review_threshold}, deny={deny_threshold}\n"
            f"   Weights: {factor_weights}"
        )
        
        return policy
    
    async def update_policy(
        self,
        customer_id: str,
        approve_threshold: Optional[float] = None,
        review_threshold: Optional[float] = None,
        deny_threshold: Optional[float] = None,
        factor_weights: Optional[Dict[RiskFactor, float]] = None,
        custom_rules: Optional[Dict[str, Any]] = None,
        updated_by: str = "system"
    ) -> RiskPolicy:
        """
        Update existing policy
        
        Args:
            customer_id: Customer identifier
            approve_threshold: New approval threshold
            review_threshold: New review threshold
            deny_threshold: New denial threshold
            factor_weights: New factor weights
            custom_rules: New custom rules
            updated_by: Who made the update
        
        Returns:
            Updated policy
        """
        
        # Get current policy
        current_policy = await self.get_policy(customer_id)
        
        if not current_policy:
            raise ValueError(f"No policy found for customer: {customer_id}")
        
        # Build update
        updates = {
            "approve_threshold": approve_threshold or current_policy.approve_threshold,
            "review_threshold": review_threshold or current_policy.review_threshold,
            "deny_threshold": deny_threshold or current_policy.deny_threshold,
            "factor_weights": factor_weights or current_policy.factor_weights,
            "custom_rules": custom_rules if custom_rules is not None else current_policy.custom_rules
        }
        
        # Validate thresholds
        if not (0 <= updates["approve_threshold"] < updates["review_threshold"] < updates["deny_threshold"] <= 1.0):
            raise ValueError("Invalid threshold configuration")
        
        # Increment version
        new_version = current_policy.version + 1
        now = datetime.utcnow()
        
        # Update database
        async with self.postgres.acquire() as conn:
            await conn.execute(
                """
                UPDATE risk_policies
                SET approve_threshold = $1,
                    review_threshold = $2,
                    deny_threshold = $3,
                    factor_weights = $4,
                    custom_rules = $5,
                    version = $6,
                    updated_at = $7,
                    updated_by = $8
                WHERE customer_id = $9 AND is_active = true
                """,
                updates["approve_threshold"],
                updates["review_threshold"],
                updates["deny_threshold"],
                json.dumps({k.value: v for k, v in updates["factor_weights"].items()}),
                json.dumps(updates["custom_rules"]),
                new_version,
                now,
                updated_by,
                customer_id
            )
            
            # Record policy change
            await conn.execute(
                """
                INSERT INTO policy_change_log
                (policy_id, customer_id, old_version, new_version,
                 changes, changed_by, changed_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                current_policy.policy_id,
                customer_id,
                current_policy.version,
                new_version,
                json.dumps(updates, default=str),
                updated_by,
                now
            )
        
        # Create updated policy object
        updated_policy = RiskPolicy(
            policy_id=current_policy.policy_id,
            customer_id=customer_id,
            policy_name=current_policy.policy_name,
            approve_threshold=updates["approve_threshold"],
            review_threshold=updates["review_threshold"],
            deny_threshold=updates["deny_threshold"],
            factor_weights=updates["factor_weights"],
            custom_rules=updates["custom_rules"],
            version=new_version,
            is_active=True,
            created_at=current_policy.created_at,
            updated_at=now,
            created_by=current_policy.created_by
        )
        
        # Update cache
        self._policy_cache[customer_id] = updated_policy
        
        logger.info(
            f"✅ Policy updated: {current_policy.policy_id}\n"
            f"   Customer: {customer_id}\n"
            f"   Version: {current_policy.version} → {new_version}\n"
            f"   Updated by: {updated_by}"
        )
        
        return updated_policy
    
    async def get_policy(
        self,
        customer_id: str,
        use_cache: bool = True
    ) -> Optional[RiskPolicy]:
        """
        Get active policy for customer
        
        Args:
            customer_id: Customer identifier
            use_cache: Use cached policy if available
        
        Returns:
            Active policy or None
        """
        
        # Check cache
        if use_cache and customer_id in self._policy_cache:
            return self._policy_cache[customer_id]
        
        # Load from database
        async with self.postgres.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM risk_policies
                WHERE customer_id = $1 AND is_active = true
                ORDER BY version DESC
                LIMIT 1
                """,
                customer_id
            )
        
        if not row:
            return None
        
        # Parse factor weights
        factor_weights_json = json.loads(row["factor_weights"])
        factor_weights = {
            RiskFactor(k): v for k, v in factor_weights_json.items()
        }
        
        policy = RiskPolicy(
            policy_id=row["policy_id"],
            customer_id=row["customer_id"],
            policy_name=row["policy_name"],
            approve_threshold=float(row["approve_threshold"]),
            review_threshold=float(row["review_threshold"]),
            deny_threshold=float(row["deny_threshold"]),
            factor_weights=factor_weights,
            custom_rules=json.loads(row["custom_rules"]),
            version=row["version"],
            is_active=row["is_active"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            created_by=row["created_by"]
        )
        
        # Update cache
        self._policy_cache[customer_id] = policy
        
        return policy
    
    async def refresh_cache(self):
        """Refresh policy cache from database"""
        
        async with self.postgres.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM risk_policies
                WHERE is_active = true
                """
            )
        
        self._policy_cache.clear()
        
        for row in rows:
            factor_weights_json = json.loads(row["factor_weights"])
            factor_weights = {
                RiskFactor(k): v for k, v in factor_weights_json.items()
            }
            
            policy = RiskPolicy(
                policy_id=row["policy_id"],
                customer_id=row["customer_id"],
                policy_name=row["policy_name"],
                approve_threshold=float(row["approve_threshold"]),
                review_threshold=float(row["review_threshold"]),
                deny_threshold=float(row["deny_threshold"]),
                factor_weights=factor_weights,
                custom_rules=json.loads(row["custom_rules"]),
                version=row["version"],
                is_active=row["is_active"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                created_by=row["created_by"]
            )
            
            self._policy_cache[policy.customer_id] = policy
        
        logger.info(f"✅ Policy cache refreshed: {len(self._policy_cache)} policies loaded")
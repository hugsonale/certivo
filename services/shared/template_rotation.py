"""
Challenge template rotation and A/B testing
Hardens against pattern recognition attacks
"""

import redis.asyncio as redis
import secrets
import json
import time
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta


class TemplateRotationManager:
    """
    Manages template rotation and A/B testing
    Prevents attackers from learning patterns
    """
    
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self.rotation_window = 3600  # 1 hour
        self.ab_test_ratio = 0.5  # 50/50 split
    
    async def get_active_templates(self) -> List[str]:
        """Get currently active template IDs"""
        active_key = "template_rotation:active"
        
        # Check if rotation exists
        templates = await self.redis.smembers(active_key)
        
        if not templates:
            # Initialize with default templates
            default_templates = [
                "two_step_sequence",
                "three_step_timed",
                "combinatorial_challenge"
            ]
            
            for template_id in default_templates:
                await self.redis.sadd(active_key, template_id)
            
            # Set expiry for rotation
            await self.redis.expire(active_key, self.rotation_window)
            
            return default_templates
        
        return list(templates)
    
    async def rotate_templates(self) -> List[str]:
        """
        Rotate active templates
        Called periodically to change challenge patterns
        """
        
        all_templates = [
            "simple_turn",
            "two_step_sequence",
            "three_step_timed",
            "combinatorial_challenge",
            "mega_combinatorial"
        ]
        
        # Select 3-4 random templates using CSPRNG
        num_active = secrets.choice([3, 4])
        active_templates = secrets.SystemRandom().sample(all_templates, num_active)
        
        # Update Redis
        active_key = "template_rotation:active"
        
        # Clear old
        await self.redis.delete(active_key)
        
        # Add new
        for template_id in active_templates:
            await self.redis.sadd(active_key, template_id)
        
        # Set expiry
        await self.redis.expire(active_key, self.rotation_window)
        
        # Log rotation
        await self._log_rotation(active_templates)
        
        return active_templates
    
    async def _log_rotation(self, templates: List[str]):
        """Log template rotation for monitoring"""
        log_key = f"template_rotation:log:{int(time.time())}"
        log_data = {
            "templates": templates,
            "timestamp": datetime.utcnow().isoformat(),
            "rotation_window": self.rotation_window
        }
        
        await self.redis.setex(
            log_key,
            86400,  # Keep logs for 24 hours
            json.dumps(log_data)
        )
    
    async def select_template_for_ab_test(
        self,
        device_id: str,
        variant_a: str,
        variant_b: str
    ) -> str:
        """
        A/B test between two template variants
        Uses consistent hashing for same device
        """
        
        # Consistent assignment based on device_id hash
        import hashlib
        device_hash = hashlib.sha256(device_id.encode()).hexdigest()
        hash_int = int(device_hash[:8], 16)
        
        # Deterministic assignment
        if hash_int % 2 == 0:
            selected = variant_a
        else:
            selected = variant_b
        
        # Track A/B test assignment
        await self._track_ab_assignment(device_id, selected, variant_a, variant_b)
        
        return selected
    
    async def _track_ab_assignment(
        self,
        device_id: str,
        selected: str,
        variant_a: str,
        variant_b: str
    ):
        """Track A/B test assignments"""
        
        ab_key = f"ab_test:{variant_a}_vs_{variant_b}"
        
        # Increment counter for selected variant
        await self.redis.hincrby(ab_key, selected, 1)
        
        # Set expiry
        await self.redis.expire(ab_key, 86400)
    
    async def get_ab_test_results(
        self,
        variant_a: str,
        variant_b: str
    ) -> Dict[str, int]:
        """Get A/B test results"""
        
        ab_key = f"ab_test:{variant_a}_vs_{variant_b}"
        results = await self.redis.hgetall(ab_key)
        
        return {
            variant_a: int(results.get(variant_a, 0)),
            variant_b: int(results.get(variant_b, 0))
        }
    
    async def get_template_effectiveness(
        self,
        template_id: str
    ) -> Dict[str, Any]:
        """
        Get effectiveness metrics for a template
        
        Returns:
            success_rate, avg_liveness_score, total_uses
        """
        
        metrics_key = f"template_metrics:{template_id}"
        metrics = await self.redis.hgetall(metrics_key)
        
        if not metrics:
            return {
                "template_id": template_id,
                "success_rate": 0,
                "avg_liveness_score": 0,
                "total_uses": 0
            }
        
        total = int(metrics.get("total", 0))
        successes = int(metrics.get("successes", 0))
        total_score = float(metrics.get("total_score", 0))
        
        return {
            "template_id": template_id,
            "success_rate": successes / total if total > 0 else 0,
            "avg_liveness_score": total_score / total if total > 0 else 0,
            "total_uses": total
        }
    
    async def record_challenge_result(
        self,
        template_id: str,
        success: bool,
        liveness_score: float
    ):
        """Record challenge result for template effectiveness tracking"""
        
        metrics_key = f"template_metrics:{template_id}"
        
        # Increment total
        await self.redis.hincrby(metrics_key, "total", 1)
        
        # Increment successes
        if success:
            await self.redis.hincrby(metrics_key, "successes", 1)
        
        # Add to total score
        await self.redis.hincrbyfloat(metrics_key, "total_score", liveness_score)
        
        # Set expiry
        await self.redis.expire(metrics_key, 86400 * 7)  # 7 days
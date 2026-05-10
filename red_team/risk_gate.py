"""
Risk Gate Validation
Calculate weighted bypass score and enforce launch criteria
"""

from typing import Dict, Any, List
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class RiskGate:
    """
    Risk gate validation for production launch
    
    Acceptance Criteria:
    - Weighted bypass score < 0.05 (5%)
    """
    
    # Attack weights based on real-world threat likelihood
    ATTACK_WEIGHTS = {
        "replay_attack": 0.30,        # Most common
        "video_injection": 0.25,      # Deepfakes increasing
        "headless_automation": 0.20,  # Bot farms
        "device_spoofing": 0.15,      # Device cloning
        "prompt_prediction": 0.10     # Challenge farming
    }
    
    # Risk gate threshold
    RISK_GATE_THRESHOLD = 0.05  # 5%
    
    @classmethod
    def calculate_weighted_score(
        cls,
        attack_results: Dict[str, float]
    ) -> float:
        """
        Calculate weighted bypass score
        
        Args:
            attack_results: Dict of {attack_type: bypass_rate}
        
        Returns:
            Weighted score (0.0 - 1.0)
        """
        
        weighted_sum = 0.0
        total_weight = 0.0
        
        for attack_type, bypass_rate in attack_results.items():
            weight = cls.ATTACK_WEIGHTS.get(attack_type, 0.05)
            weighted_sum += weight * bypass_rate
            total_weight += weight
        
        if total_weight > 0:
            return weighted_sum / total_weight
        else:
            return 0.0
    
    @classmethod
    def validate_launch_readiness(
        cls,
        attack_results: Dict[str, float]
    ) -> Dict[str, Any]:
        """
        Validate if system meets launch criteria
        
        Returns:
            {
                "ready": bool,
                "weighted_score": float,
                "threshold": float,
                "margin": float,
                "failing_attacks": list
            }
        """
        
        weighted_score = cls.calculate_weighted_score(attack_results)
        ready = weighted_score < cls.RISK_GATE_THRESHOLD
        margin = cls.RISK_GATE_THRESHOLD - weighted_score
        
        # Identify failing attacks (> 5% bypass)
        failing_attacks = [
            {
                "attack": attack,
                "bypass_rate": rate,
                "weight": cls.ATTACK_WEIGHTS.get(attack, 0.05)
            }
            for attack, rate in attack_results.items()
            if rate > 0.05
        ]
        
        result = {
            "ready": ready,
            "weighted_score": weighted_score,
            "threshold": cls.RISK_GATE_THRESHOLD,
            "margin": margin,
            "failing_attacks": failing_attacks,
            "status": "✅ PASS" if ready else "❌ FAIL"
        }
        
        logger.info("="*60)
        logger.info("RISK GATE VALIDATION")
        logger.info("="*60)
        logger.info(f"Weighted Bypass Score: {weighted_score:.4f}")
        logger.info(f"Threshold: {cls.RISK_GATE_THRESHOLD}")
        logger.info(f"Margin: {margin:+.4f}")
        logger.info(f"Status: {result['status']}")
        
        if failing_attacks:
            logger.warning(f"\nFailing Attacks: {len(failing_attacks)}")
            for attack in failing_attacks:
                logger.warning(
                    f"  - {attack['attack']}: {attack['bypass_rate']:.2%} "
                    f"(weight: {attack['weight']:.0%})"
                )
        
        logger.info("="*60)
        
        return result
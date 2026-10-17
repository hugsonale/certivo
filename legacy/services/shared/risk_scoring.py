"""
Risk Scoring Engine
Weighted multi-factor risk assessment
"""

from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import json
import logging

logger = logging.getLogger(__name__)


class RiskFactor(str, Enum):
    """Risk assessment factors"""
    LIVENESS = "liveness"
    BEHAVIOR = "behavior"
    DEVICE = "device"
    NETWORK = "network"


class RiskLevel(str, Enum):
    """Risk level categories"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class RiskFactorScore:
    """Individual risk factor score"""
    factor: RiskFactor
    score: float  # 0.0 - 1.0 (0 = no risk, 1 = maximum risk)
    weight: float  # Factor weight in overall score
    confidence: float  # 0.0 - 1.0
    signals: Dict[str, Any]  # Raw signals that contributed
    explanation: str  # Human-readable explanation
    
    def weighted_score(self) -> float:
        """Calculate weighted contribution"""
        return self.score * self.weight
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "factor": self.factor.value,
            "score": round(self.score, 4),
            "weight": round(self.weight, 4),
            "confidence": round(self.confidence, 4),
            "weighted_contribution": round(self.weighted_score(), 4),
            "signals": self.signals,
            "explanation": self.explanation
        }


@dataclass
class RiskAssessment:
    """Complete risk assessment result"""
    session_id: str
    device_id: str
    overall_risk_score: float  # 0.0 - 1.0
    risk_level: RiskLevel
    factors: Dict[RiskFactor, RiskFactorScore]
    timestamp: datetime
    
    # Decision metadata
    threshold_used: float
    passed: bool
    decision: str  # "approve", "deny", "review", "challenge"
    
    # Explainability
    primary_concerns: List[str]
    explanation: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "device_id": self.device_id,
            "overall_risk_score": round(self.overall_risk_score, 4),
            "risk_level": self.risk_level.value,
            "factors": {
                k.value: v.to_dict() for k, v in self.factors.items()
            },
            "timestamp": self.timestamp.isoformat(),
            "threshold_used": round(self.threshold_used, 4),
            "passed": self.passed,
            "decision": self.decision,
            "primary_concerns": self.primary_concerns,
            "explanation": self.explanation
        }


class RiskScoringEngine:
    """
    Multi-factor risk scoring engine
    
    Features:
    - Weighted factor scoring
    - Configurable weights per customer
    - Real-time risk assessment
    - Explainable decisions
    """
    
    # Default weights (can be overridden per customer)
    DEFAULT_WEIGHTS = {
        RiskFactor.LIVENESS: 0.40,  # 40% - Most critical
        RiskFactor.BEHAVIOR: 0.25,  # 25% - User patterns
        RiskFactor.DEVICE: 0.20,    # 20% - Device trust
        RiskFactor.NETWORK: 0.15    # 15% - Network reputation
    }
    
    def __init__(self, weights: Optional[Dict[RiskFactor, float]] = None):
        """
        Initialize risk scoring engine
        
        Args:
            weights: Custom factor weights (defaults to DEFAULT_WEIGHTS)
        """
        self.weights = weights or self.DEFAULT_WEIGHTS.copy()
        
        # Validate weights sum to 1.0
        total = sum(self.weights.values())
        if abs(total - 1.0) > 0.001:
            raise ValueError(f"Weights must sum to 1.0, got {total}")
    
    def calculate_liveness_score(
        self,
        liveness_result: Dict[str, Any]
    ) -> RiskFactorScore:
        """
        Calculate liveness risk score
        
        Args:
            liveness_result: Liveness detection results
        
        Returns:
            RiskFactorScore for liveness
        """
        
        # Extract signals
        overall_score = liveness_result.get("overall_liveness_score", 0.0)
        motion_score = liveness_result.get("motion_score", 0.0)
        temporal_score = liveness_result.get("temporal_score", 0.0)
        anti_spoof_score = liveness_result.get("anti_spoof_score", 0.0)
        action_score = liveness_result.get("action_score", 0.0)
        
        # Convert liveness score (0-1) to risk score (0-1)
        # High liveness = low risk
        risk_score = 1.0 - overall_score
        
        # Confidence based on signal quality
        confidence = liveness_result.get("confidence", 0.8)
        
        # Build explanation
        concerns = []
        if motion_score < 0.5:
            concerns.append("unnatural motion patterns")
        if temporal_score < 0.5:
            concerns.append("temporal inconsistencies")
        if anti_spoof_score < 0.5:
            concerns.append("potential spoofing detected")
        if action_score < 0.5:
            concerns.append("action verification failed")
        
        if concerns:
            explanation = f"Liveness concerns: {', '.join(concerns)}"
        elif risk_score < 0.2:
            explanation = "Strong liveness signals, low risk"
        elif risk_score < 0.5:
            explanation = "Acceptable liveness, moderate risk"
        else:
            explanation = "Weak liveness signals, high risk"
        
        return RiskFactorScore(
            factor=RiskFactor.LIVENESS,
            score=risk_score,
            weight=self.weights[RiskFactor.LIVENESS],
            confidence=confidence,
            signals={
                "overall_liveness": overall_score,
                "motion": motion_score,
                "temporal": temporal_score,
                "anti_spoof": anti_spoof_score,
                "action": action_score
            },
            explanation=explanation
        )
    
    def calculate_behavior_score(
        self,
        behavior_data: Dict[str, Any]
    ) -> RiskFactorScore:
        """
        Calculate behavioral risk score
        
        Args:
            behavior_data: User behavior metrics
        
        Returns:
            RiskFactorScore for behavior
        """
        
        risk_score = 0.0
        signals = {}
        concerns = []
        
        # Failed attempts history
        failed_attempts = behavior_data.get("recent_failed_attempts", 0)
        if failed_attempts > 5:
            risk_score += 0.3
            concerns.append(f"{failed_attempts} recent failures")
        elif failed_attempts > 2:
            risk_score += 0.15
        signals["failed_attempts"] = failed_attempts
        
        # Velocity (attempts per hour)
        velocity = behavior_data.get("attempts_per_hour", 0)
        if velocity > 10:
            risk_score += 0.25
            concerns.append(f"high velocity ({velocity}/hour)")
        elif velocity > 5:
            risk_score += 0.10
        signals["velocity"] = velocity
        
        # Session exhaustion
        session_exhaustion_rate = behavior_data.get("session_exhaustion_rate", 0.0)
        if session_exhaustion_rate > 0.7:
            risk_score += 0.25
            concerns.append(f"session exhaustion ({session_exhaustion_rate:.0%})")
        signals["session_exhaustion_rate"] = session_exhaustion_rate
        
        # Time pattern anomalies
        time_pattern_score = behavior_data.get("time_pattern_score", 1.0)
        if time_pattern_score < 0.3:
            risk_score += 0.15
            concerns.append("unusual time patterns")
        signals["time_pattern_score"] = time_pattern_score
        
        # Browser automation signals
        automation_detected = behavior_data.get("automation_detected", False)
        if automation_detected:
            risk_score += 0.5
            concerns.append("automation detected")
        signals["automation_detected"] = automation_detected
        
        # Cap at 1.0
        risk_score = min(risk_score, 1.0)
        
        # Build explanation
        if concerns:
            explanation = f"Behavioral concerns: {', '.join(concerns)}"
        elif risk_score < 0.2:
            explanation = "Normal behavioral patterns"
        elif risk_score < 0.5:
            explanation = "Some behavioral anomalies detected"
        else:
            explanation = "Suspicious behavioral patterns"
        
        return RiskFactorScore(
            factor=RiskFactor.BEHAVIOR,
            score=risk_score,
            weight=self.weights[RiskFactor.BEHAVIOR],
            confidence=0.85,
            signals=signals,
            explanation=explanation
        )
    
    def calculate_device_score(
        self,
        device_data: Dict[str, Any]
    ) -> RiskFactorScore:
        """
        Calculate device trust risk score
        
        Args:
            device_data: Device characteristics and history
        
        Returns:
            RiskFactorScore for device
        """
        
        risk_score = 0.0
        signals = {}
        concerns = []
        
        # Device age
        is_new_device = device_data.get("is_new_device", False)
        days_since_first_seen = device_data.get("days_since_first_seen", 0)
        
        if is_new_device:
            risk_score += 0.20
            concerns.append("new device")
        elif days_since_first_seen < 7:
            risk_score += 0.10
            concerns.append("recently registered device")
        
        signals["is_new_device"] = is_new_device
        signals["days_since_first_seen"] = days_since_first_seen
        
        # Device reputation
        reputation_score = device_data.get("reputation_score", 0.5)
        if reputation_score < 0.3:
            risk_score += 0.30
            concerns.append("poor device reputation")
        elif reputation_score < 0.6:
            risk_score += 0.10
        signals["reputation_score"] = reputation_score
        
        # Fingerprint consistency
        fingerprint_changes = device_data.get("fingerprint_changes", 0)
        if fingerprint_changes > 5:
            risk_score += 0.25
            concerns.append(f"{fingerprint_changes} fingerprint changes")
        elif fingerprint_changes > 2:
            risk_score += 0.10
        signals["fingerprint_changes"] = fingerprint_changes
        
        # Jailbroken/rooted
        is_compromised = device_data.get("is_compromised", False)
        if is_compromised:
            risk_score += 0.40
            concerns.append("compromised device (jailbroken/rooted)")
        signals["is_compromised"] = is_compromised
        
        # Emulator detection
        is_emulator = device_data.get("is_emulator", False)
        if is_emulator:
            risk_score += 0.35
            concerns.append("emulator detected")
        signals["is_emulator"] = is_emulator
        
        # Cap at 1.0
        risk_score = min(risk_score, 1.0)
        
        # Build explanation
        if concerns:
            explanation = f"Device concerns: {', '.join(concerns)}"
        elif risk_score < 0.2:
            explanation = "Trusted device with good history"
        elif risk_score < 0.5:
            explanation = "Device requires monitoring"
        else:
            explanation = "Untrusted or suspicious device"
        
        return RiskFactorScore(
            factor=RiskFactor.DEVICE,
            score=risk_score,
            weight=self.weights[RiskFactor.DEVICE],
            confidence=0.90,
            signals=signals,
            explanation=explanation
        )
    
    def calculate_network_score(
        self,
        network_data: Dict[str, Any]
    ) -> RiskFactorScore:
        """
        Calculate network reputation risk score
        
        Args:
            network_data: Network and IP information
        
        Returns:
            RiskFactorScore for network
        """
        
        risk_score = 0.0
        signals = {}
        concerns = []
        
        # VPN/Proxy detection
        is_vpn = network_data.get("is_vpn", False)
        is_proxy = network_data.get("is_proxy", False)
        is_tor = network_data.get("is_tor", False)
        
        if is_tor:
            risk_score += 0.50
            concerns.append("Tor exit node")
        elif is_vpn:
            risk_score += 0.20
            concerns.append("VPN detected")
        elif is_proxy:
            risk_score += 0.25
            concerns.append("proxy detected")
        
        signals["is_vpn"] = is_vpn
        signals["is_proxy"] = is_proxy
        signals["is_tor"] = is_tor
        
        # IP reputation
        ip_reputation = network_data.get("ip_reputation_score", 0.5)
        if ip_reputation < 0.2:
            risk_score += 0.30
            concerns.append("poor IP reputation")
        elif ip_reputation < 0.5:
            risk_score += 0.10
        signals["ip_reputation"] = ip_reputation
        
        # Datacenter detection
        is_datacenter = network_data.get("is_datacenter", False)
        if is_datacenter:
            risk_score += 0.25
            concerns.append("datacenter IP")
        signals["is_datacenter"] = is_datacenter
        
        # ASN reputation
        asn_risk_score = network_data.get("asn_risk_score", 0.0)
        if asn_risk_score > 0.7:
            risk_score += 0.20
            concerns.append("high-risk ASN")
        signals["asn_risk_score"] = asn_risk_score
        
        # Geographic anomaly
        location_mismatch = network_data.get("location_mismatch", False)
        if location_mismatch:
            risk_score += 0.15
            concerns.append("location mismatch")
        signals["location_mismatch"] = location_mismatch
        
        # Cap at 1.0
        risk_score = min(risk_score, 1.0)
        
        # Build explanation
        if concerns:
            explanation = f"Network concerns: {', '.join(concerns)}"
        elif risk_score < 0.2:
            explanation = "Clean network with good reputation"
        elif risk_score < 0.5:
            explanation = "Network requires monitoring"
        else:
            explanation = "High-risk or suspicious network"
        
        return RiskFactorScore(
            factor=RiskFactor.NETWORK,
            score=risk_score,
            weight=self.weights[RiskFactor.NETWORK],
            confidence=0.80,
            signals=signals,
            explanation=explanation
        )
    
    def assess_risk(
        self,
        session_id: str,
        device_id: str,
        liveness_result: Dict[str, Any],
        behavior_data: Dict[str, Any],
        device_data: Dict[str, Any],
        network_data: Dict[str, Any],
        threshold: float = 0.50
    ) -> RiskAssessment:
        """
        Perform complete risk assessment
        
        Args:
            session_id: Session identifier
            device_id: Device identifier
            liveness_result: Liveness detection results
            behavior_data: Behavioral metrics
            device_data: Device information
            network_data: Network information
            threshold: Risk threshold for approval
        
        Returns:
            Complete risk assessment
        """
        
        # Calculate individual factor scores
        liveness_score = self.calculate_liveness_score(liveness_result)
        behavior_score = self.calculate_behavior_score(behavior_data)
        device_score = self.calculate_device_score(device_data)
        network_score = self.calculate_network_score(network_data)
        
        # Store all factors
        factors = {
            RiskFactor.LIVENESS: liveness_score,
            RiskFactor.BEHAVIOR: behavior_score,
            RiskFactor.DEVICE: device_score,
            RiskFactor.NETWORK: network_score
        }
        
        # Calculate weighted overall score
        overall_risk_score = sum(
            factor.weighted_score() for factor in factors.values()
        )
        
        # Determine risk level
        if overall_risk_score >= 0.75:
            risk_level = RiskLevel.CRITICAL
        elif overall_risk_score >= 0.50:
            risk_level = RiskLevel.HIGH
        elif overall_risk_score >= 0.25:
            risk_level = RiskLevel.MEDIUM
        else:
            risk_level = RiskLevel.LOW
        
        # Make decision
        passed = overall_risk_score < threshold
        
        if passed:
            decision = "approve"
        elif overall_risk_score >= 0.75:
            decision = "deny"
        elif overall_risk_score >= threshold:
            decision = "review"  # Manual review required
        else:
            decision = "challenge"  # Additional challenge
        
        # Identify primary concerns (top 2 factors)
        sorted_factors = sorted(
            factors.values(),
            key=lambda f: f.weighted_score(),
            reverse=True
        )
        
        primary_concerns = [
            f"{f.factor.value}: {f.explanation}"
            for f in sorted_factors[:2]
            if f.score > 0.3  # Only include significant concerns
        ]
        
        # Build overall explanation
        if decision == "approve":
            explanation = f"Risk score {overall_risk_score:.2%} below threshold {threshold:.2%}. Verification approved."
        elif decision == "deny":
            explanation = f"Critical risk score {overall_risk_score:.2%}. Verification denied. Primary concerns: {'; '.join(primary_concerns)}"
        elif decision == "review":
            explanation = f"High risk score {overall_risk_score:.2%} above threshold {threshold:.2%}. Manual review required. Primary concerns: {'; '.join(primary_concerns)}"
        else:
            explanation = f"Moderate risk score {overall_risk_score:.2%}. Additional challenge recommended."
        
        assessment = RiskAssessment(
            session_id=session_id,
            device_id=device_id,
            overall_risk_score=overall_risk_score,
            risk_level=risk_level,
            factors=factors,
            timestamp=datetime.utcnow(),
            threshold_used=threshold,
            passed=passed,
            decision=decision,
            primary_concerns=primary_concerns,
            explanation=explanation
        )
        
        logger.info(
            f"📊 Risk Assessment: {session_id}\n"
            f"   Overall Score: {overall_risk_score:.2%}\n"
            f"   Risk Level: {risk_level.value}\n"
            f"   Decision: {decision}\n"
            f"   Liveness: {liveness_score.score:.2%} (weight: {liveness_score.weight:.1%})\n"
            f"   Behavior: {behavior_score.score:.2%} (weight: {behavior_score.weight:.1%})\n"
            f"   Device: {device_score.score:.2%} (weight: {device_score.weight:.1%})\n"
            f"   Network: {network_score.score:.2%} (weight: {network_score.weight:.1%})"
        )
        
        return assessment
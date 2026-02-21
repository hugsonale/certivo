"""
Admin Dashboard Services
Database queries, metrics calculations, and business logic
"""

from sqlalchemy.orm import Session
from sqlalchemy import func, desc, and_
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import json
import psutil
import time

# Import database models (from your existing database.py)
from database import (
    SessionRecord,
    ChallengeResult,
    TrustedDevice,
    ActiveChallenge,
    BotReport,
    get_recent_sessions,
    get_failed_challenges,
)

# Try to import get_success_rate_by_direction, if not available create fallback
try:
    from database import get_success_rate_by_direction
except ImportError:
    def get_success_rate_by_direction(db: Session) -> Dict[str, Any]:
        """Fallback function if not available in database.py"""
        return {}

from admin import utils
from admin.config import METRICS_DEFAULT_DAYS


# ============================================================================
# OVERVIEW / DASHBOARD METRICS
# ============================================================================

def get_dashboard_metrics(db: Session) -> Dict[str, Any]:
    """
    Get all metrics for the dashboard overview page
    Safe fallback if tables don't exist yet
    """
    
    try:
        # Total verifications (all time)
        total_verifications = db.query(SessionRecord).count()
    except Exception as e:
        print(f"Warning: Could not query sessions: {e}")
        total_verifications = 0
    
    try:
        # Verifications today
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        verifications_today = db.query(SessionRecord).filter(
            SessionRecord.timestamp_utc >= today_start
        ).count()
    except Exception as e:
        print(f"Warning: Could not query today's sessions: {e}")
        verifications_today = 0
    
    try:
        # Success rate
        total_challenges = db.query(ChallengeResult).count()
        successful_challenges = db.query(ChallengeResult).filter(
            ChallengeResult.challenge_passed == True
        ).count()
    except Exception as e:
        print(f"Warning: Could not query challenges: {e}")
        total_challenges = 0
        successful_challenges = 0
    
    success_rate = utils.calculate_success_rate(total_challenges, successful_challenges)
    
    # Failure rate
    failed_challenges = total_challenges - successful_challenges
    failure_rate = utils.calculate_failure_rate(total_challenges, failed_challenges)
    
    try:
        # Fast-track verifications
        fast_track_count = db.query(SessionRecord).filter(
            SessionRecord.fast_track == True
        ).count()
    except Exception as e:
        print(f"Warning: Could not query fast-track sessions: {e}")
        fast_track_count = 0
    
    try:
        # Suspicious attempts
        suspicious_count = db.query(BotReport).filter(
            BotReport.bot_detected == True
        ).count()
    except Exception as e:
        print(f"Warning: Could not query bot reports: {e}")
        suspicious_count = 0
    
    try:
        # Active trusted devices - query without trust_revoked column
        trusted_devices_count = db.query(TrustedDevice).filter(
            TrustedDevice.trust_level == "high"
        ).count()
    except Exception as e:
        print(f"Warning: Could not query trusted devices: {e}")
        trusted_devices_count = 0
    
    return {
        "total_verifications": total_verifications,
        "verifications_today": verifications_today,
        "success_rate": success_rate,
        "failure_rate": failure_rate,
        "fast_track_count": fast_track_count,
        "suspicious_count": suspicious_count,
        "trusted_devices_count": trusted_devices_count,
        "total_challenges": total_challenges,
        "successful_challenges": successful_challenges,
        "failed_challenges": failed_challenges
    }


def get_activity_chart_data(db: Session, days: int = 7) -> Dict[str, Any]:
    """
    Get verification activity for the last N days
    Returns data formatted for Chart.js
    """
    try:
        start_date, end_date = utils.get_date_range(days)
        
        # Get all sessions in date range
        sessions = db.query(SessionRecord).filter(
            SessionRecord.timestamp_utc >= start_date
        ).all()
        
        # Group by date
        activity_by_date = utils.group_by_date(sessions, 'timestamp_utc')
        
        # Prepare chart data
        chart_data = utils.prepare_line_chart_data(activity_by_date, days)
        
        return chart_data
    except Exception as e:
        print(f"Warning: Could not get activity chart data: {e}")
        # Return empty chart data
        return {
            "labels": [],
            "data": []
        }


def get_success_failure_breakdown(db: Session, days: int = 7) -> Dict[str, Any]:
    """
    Get success vs failure breakdown
    """
    try:
        start_date, end_date = utils.get_date_range(days)
        
        # Get challenges in date range
        challenges = db.query(ChallengeResult).filter(
            ChallengeResult.timestamp_utc >= start_date
        ).all()
        
        # Count successes and failures
        success_count = sum(1 for c in challenges if c.challenge_passed)
        failure_count = len(challenges) - success_count
        
        return {
            "labels": ["Success", "Failure"],
            "data": [success_count, failure_count]
        }
    except Exception as e:
        print(f"Warning: Could not get breakdown data: {e}")
        return {
            "labels": ["Success", "Failure"],
            "data": [0, 0]
        }


def get_alerts(db: Session) -> List[Dict[str, str]]:
    """
    Detect and return system alerts
    """
    alerts = []
    
    try:
        # Check high failure rate
        total = db.query(ChallengeResult).count()
        failed = db.query(ChallengeResult).filter(
            ChallengeResult.challenge_passed == False
        ).count()
        
        if utils.detect_high_failure_rate(total, failed, threshold=30.0):
            failure_rate = utils.calculate_failure_rate(total, failed)
            alerts.append({
                "type": "warning",
                "message": f"High failure rate detected: {failure_rate}% of challenges failing"
            })
    except Exception as e:
        print(f"Warning: Could not check failure rate: {e}")
    
    try:
        # Check for suspicious IPs
        recent_bots = db.query(BotReport).filter(
            BotReport.timestamp_utc >= datetime.utcnow() - timedelta(hours=24)
        ).all()
        
        if len(recent_bots) > 10:
            alerts.append({
                "type": "danger",
                "message": f"{len(recent_bots)} suspicious bot attempts detected in the last 24 hours"
            })
    except Exception as e:
        print(f"Warning: Could not check bot reports: {e}")
    
    return alerts


# ============================================================================
# SESSIONS
# ============================================================================

def get_all_sessions(db: Session, limit: int = 100) -> List[SessionRecord]:
    """Get all verification sessions"""
    return db.query(SessionRecord).order_by(
        desc(SessionRecord.timestamp_utc)
    ).limit(limit).all()


def get_session_details(db: Session, session_id: str) -> Optional[Dict[str, Any]]:
    """Get detailed information about a specific session"""
    session = db.query(SessionRecord).filter(
        SessionRecord.session_id == session_id
    ).first()
    
    if not session:
        return None
    
    # Get all challenges for this session
    challenges = db.query(ChallengeResult).filter(
        ChallengeResult.session_id == session_id
    ).all()
    
    return {
        "session": session,
        "challenges": challenges
    }


def search_sessions(db: Session, **filters) -> List[SessionRecord]:
    """
    Search sessions with filters
    Supports: device_id, trust_level, fast_track, date_from, date_to
    """
    query = db.query(SessionRecord)
    
    if 'device_id' in filters and filters['device_id']:
        query = query.filter(SessionRecord.device_id == filters['device_id'])
    
    if 'trust_level' in filters and filters['trust_level']:
        query = query.filter(SessionRecord.trust_level == filters['trust_level'])
    
    if 'fast_track' in filters and filters['fast_track'] is not None:
        query = query.filter(SessionRecord.fast_track == filters['fast_track'])
    
    if 'date_from' in filters and filters['date_from']:
        query = query.filter(SessionRecord.timestamp_utc >= filters['date_from'])
    
    if 'date_to' in filters and filters['date_to']:
        query = query.filter(SessionRecord.timestamp_utc <= filters['date_to'])
    
    return query.order_by(desc(SessionRecord.timestamp_utc)).all()


# ============================================================================
# CHALLENGES
# ============================================================================

def get_all_challenges(db: Session, limit: int = 100, include_expired: bool = True) -> Dict:
    """Get all challenges (both active and completed)"""
    
    try:
        # Get active challenges
        active = db.query(ActiveChallenge).order_by(
            desc(ActiveChallenge.created_at)
        ).limit(limit).all()
    except Exception as e:
        print(f"Warning: Could not query active challenges: {e}")
        active = []
    
    try:
        # Get completed challenges (from results)
        completed = db.query(ChallengeResult).order_by(
            desc(ChallengeResult.timestamp_utc)
        ).limit(limit).all()
    except Exception as e:
        print(f"Warning: Could not query completed challenges: {e}")
        completed = []
    
    # Combine and return
    return {
        "active": active,
        "completed": completed
    }


def get_challenge_stats(db: Session) -> Dict[str, Any]:
    """Get challenge statistics"""
    
    try:
        # Total challenges
        total_active = db.query(ActiveChallenge).count()
        total_completed = db.query(ChallengeResult).count()
        
        # Expired challenges
        now = datetime.utcnow()
        expired = db.query(ActiveChallenge).filter(
            ActiveChallenge.expires_at < now
        ).count()
        
        # Used challenges
        used = db.query(ActiveChallenge).filter(
            ActiveChallenge.used == True
        ).count()
    except Exception as e:
        print(f"Warning: Could not get challenge stats: {e}")
        total_active = 0
        total_completed = 0
        expired = 0
        used = 0
    
    # Success rate by direction - with error handling
    try:
        direction_stats = get_success_rate_by_direction(db)
    except Exception as e:
        print(f"Warning: Could not get direction stats: {e}")
        direction_stats = {}
    
    return {
        "total_active": total_active,
        "total_completed": total_completed,
        "expired": expired,
        "used": used,
        "direction_stats": direction_stats
    }


# ============================================================================
# TRUSTED DEVICES
# ============================================================================

def get_all_trusted_devices(db: Session) -> List[TrustedDevice]:
    """Get all trusted devices"""
    try:
        return db.query(TrustedDevice).order_by(
            desc(TrustedDevice.last_verified_utc)
        ).all()
    except Exception as e:
        print(f"Warning: Could not query trusted devices: {e}")
        return []


def get_device_details(db: Session, device_id: str) -> Optional[Dict[str, Any]]:
    """Get detailed information about a device"""
    device = db.query(TrustedDevice).filter(
        TrustedDevice.device_id == device_id
    ).first()
    
    if not device:
        return None
    
    # Get device's verification history
    sessions = db.query(SessionRecord).filter(
        SessionRecord.device_id == device_id
    ).order_by(desc(SessionRecord.timestamp_utc)).all()
    
    challenges = db.query(ChallengeResult).filter(
        ChallengeResult.device_id == device_id
    ).order_by(desc(ChallengeResult.timestamp_utc)).all()
    
    return {
        "device": device,
        "sessions": sessions,
        "challenges": challenges
    }


def revoke_device_trust(db: Session, device_id: str) -> bool:
    """Revoke trust for a device"""
    device = db.query(TrustedDevice).filter(
        TrustedDevice.device_id == device_id
    ).first()
    
    if not device:
        return False
    
    # Set trust level to low
    device.trust_level = "low"
    device.trusted_since_utc = None
    db.commit()
    
    print(f"🔒 Trust revoked for device {device_id}")
    return True


def update_device_trust_level(db: Session, device_id: str, trust_level: str) -> bool:
    """Update device trust level"""
    device = db.query(TrustedDevice).filter(
        TrustedDevice.device_id == device_id
    ).first()
    
    if not device:
        return False
    
    device.trust_level = trust_level
    
    if trust_level == "high" and not device.trusted_since_utc:
        device.trusted_since_utc = datetime.utcnow()
    elif trust_level != "high":
        device.trusted_since_utc = None
    
    db.commit()
    return True


# ============================================================================
# BOT / SUSPICIOUS ACTIVITY
# ============================================================================

def get_bot_reports(db: Session, limit: int = 100) -> List[BotReport]:
    """Get bot detection reports"""
    return db.query(BotReport).order_by(
        desc(BotReport.timestamp_utc)
    ).limit(limit).all()


def get_bot_statistics(db: Session) -> Dict[str, Any]:
    """Get bot detection statistics"""
    total = db.query(BotReport).count()
    detected = db.query(BotReport).filter(
        BotReport.bot_detected == True
    ).count()
    
    # Get reports from last 24 hours
    last_24h = db.query(BotReport).filter(
        BotReport.timestamp_utc >= datetime.utcnow() - timedelta(hours=24)
    ).count()
    
    # Calculate detection rate
    detection_rate = utils.calculate_success_rate(total, detected) if total > 0 else 0
    
    return {
        "total_reports": total,
        "bots_detected": detected,
        "detection_rate": detection_rate,
        "last_24h": last_24h
    }


def search_bot_reports(db: Session, **filters) -> List[BotReport]:
    """Search bot reports with filters"""
    query = db.query(BotReport)
    
    if 'ip_address' in filters and filters['ip_address']:
        query = query.filter(BotReport.ip_address == filters['ip_address'])
    
    if 'bot_detected' in filters and filters['bot_detected'] is not None:
        query = query.filter(BotReport.bot_detected == filters['bot_detected'])
    
    if 'min_score' in filters and filters['min_score']:
        query = query.filter(BotReport.suspicion_score >= filters['min_score'])
    
    return query.order_by(desc(BotReport.timestamp_utc)).all()


# ============================================================================
# LOGS
# ============================================================================

def get_system_logs(db: Session, limit: int = 100) -> List[Dict]:
    """
    Get system logs from various sources
    This combines data from multiple tables
    """
    
    logs = []
    
    # Add challenge verification events
    recent_challenges = db.query(ChallengeResult).order_by(
        desc(ChallengeResult.timestamp_utc)
    ).limit(limit).all()
    
    for challenge in recent_challenges:
        logs.append({
            "timestamp": challenge.timestamp_utc,
            "event_type": "challenge_verification",
            "session_id": challenge.session_id,
            "challenge_id": challenge.challenge_id,
            "details": {
                "passed": challenge.challenge_passed,
                "liveness_score": challenge.liveness_score,
                "direction_detected": challenge.direction_detected,
                "direction_matched": challenge.direction_matched
            },
            "error": not challenge.challenge_passed
        })
    
    # Add bot detection events
    recent_bots = db.query(BotReport).order_by(
        desc(BotReport.timestamp_utc)
    ).limit(50).all()
    
    for bot in recent_bots:
        logs.append({
            "timestamp": bot.timestamp_utc,
            "event_type": "bot_detection",
            "session_id": bot.device_id,
            "challenge_id": None,
            "details": {
                "bot_detected": bot.bot_detected,
                "suspicion_score": bot.suspicion_score,
                "ip_address": bot.ip_address
            },
            "error": bot.bot_detected
        })
    
    # Sort by timestamp
    logs.sort(key=lambda x: x['timestamp'], reverse=True)
    
    return logs[:limit]


def search_logs(db: Session, **filters) -> List[Dict]:
    """Search logs with filters"""
    logs = get_system_logs(db, limit=500)
    
    # Filter by session_id
    if 'session_id' in filters and filters['session_id']:
        logs = [l for l in logs if l['session_id'] == filters['session_id']]
    
    # Filter by event_type
    if 'event_type' in filters and filters['event_type']:
        logs = [l for l in logs if l['event_type'] == filters['event_type']]
    
    # Filter by date
    if 'date_from' in filters and filters['date_from']:
        logs = [l for l in logs if l['timestamp'] >= filters['date_from']]
    
    if 'date_to' in filters and filters['date_to']:
        logs = [l for l in logs if l['timestamp'] <= filters['date_to']]
    
    return logs


# ============================================================================
# SYSTEM HEALTH
# ============================================================================

# Store start time for uptime calculation
_server_start_time = time.time()

def get_system_health() -> Dict[str, Any]:
    """Get system health metrics"""
    
    # CPU usage
    cpu_percent = psutil.cpu_percent(interval=1)
    
    # Memory usage
    memory = psutil.virtual_memory()
    memory_percent = memory.percent
    memory_used = utils.format_file_size(memory.used)
    memory_total = utils.format_file_size(memory.total)
    
    # Disk usage
    disk = psutil.disk_usage('/')
    disk_percent = disk.percent
    disk_used = utils.format_file_size(disk.used)
    disk_total = utils.format_file_size(disk.total)
    
    # Uptime
    uptime_seconds = time.time() - _server_start_time
    uptime_hours = uptime_seconds / 3600
    
    return {
        "cpu_percent": round(cpu_percent, 2),
        "memory_percent": round(memory_percent, 2),
        "memory_used": memory_used,
        "memory_total": memory_total,
        "disk_percent": round(disk_percent, 2),
        "disk_used": disk_used,
        "disk_total": disk_total,
        "uptime_hours": round(uptime_hours, 2),
        "uptime_seconds": int(uptime_seconds)
    }


def get_processing_metrics(db: Session) -> Dict[str, Any]:
    """Get verification processing metrics"""
    
    # Average liveness score
    avg_liveness = db.query(func.avg(ChallengeResult.liveness_score)).filter(
        ChallengeResult.challenge_passed == True
    ).scalar() or 0
    
    # Total verifications in progress (active challenges)
    active_count = db.query(ActiveChallenge).filter(
        ActiveChallenge.used == False,
        ActiveChallenge.expires_at > datetime.utcnow()
    ).count()
    
    # Recent processing (last hour)
    one_hour_ago = datetime.utcnow() - timedelta(hours=1)
    recent_count = db.query(ChallengeResult).filter(
        ChallengeResult.timestamp_utc >= one_hour_ago
    ).count()
    
    return {
        "avg_liveness_score": round(avg_liveness * 100, 2),
        "active_verifications": active_count,
        "verifications_last_hour": recent_count
    }
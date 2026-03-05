"""
Admin Dashboard Utilities
Helper functions for metrics calculation, alerts, and formatting
"""

from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import json


# ============================================================================
# METRICS CALCULATIONS
# ============================================================================

def calculate_success_rate(total: int, successful: int) -> float:
    """Calculate success rate percentage"""
    if total == 0:
        return 0.0
    return round((successful / total) * 100, 2)


def calculate_failure_rate(total: int, failed: int) -> float:
    """Calculate failure rate percentage"""
    if total == 0:
        return 0.0
    return round((failed / total) * 100, 2)


def get_date_range(days: int = 7) -> tuple:
    """Get start and end datetime for the last N days"""
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)
    return start_date, end_date


def group_by_date(items: List[Any], date_field: str = 'timestamp_utc') -> Dict[str, int]:
    """Group items by date and count"""
    grouped = {}
    for item in items:
        date = getattr(item, date_field).date().isoformat()
        grouped[date] = grouped.get(date, 0) + 1
    return grouped


# ============================================================================
# ALERT DETECTION
# ============================================================================

def detect_high_failure_rate(total: int, failed: int, threshold: float = 30.0) -> bool:
    """Detect if failure rate exceeds threshold"""
    if total == 0:
        return False
    failure_rate = (failed / total) * 100
    return failure_rate >= threshold


def detect_suspicious_ip_activity(ip_counts: Dict[str, int], threshold: int = 10) -> List[str]:
    """Find IPs with suspicious number of attempts"""
    suspicious = []
    for ip, count in ip_counts.items():
        if count >= threshold:
            suspicious.append(ip)
    return suspicious


def detect_no_face_issues(total: int, no_face_count: int, threshold: float = 20.0) -> bool:
    """Detect if no-face detection rate is too high"""
    if total == 0:
        return False
    rate = (no_face_count / total) * 100
    return rate >= threshold


# ============================================================================
# FORMATTING HELPERS
# ============================================================================

def format_timestamp(dt: datetime) -> str:
    """Format datetime for display"""
    if not dt:
        return "N/A"
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def format_datetime_relative(dt: datetime) -> str:
    """Format datetime as relative time (e.g., '2 hours ago')"""
    if not dt:
        return "N/A"
    
    now = datetime.utcnow()
    diff = now - dt
    
    seconds = diff.total_seconds()
    
    if seconds < 60:
        return f"{int(seconds)}s ago"
    elif seconds < 3600:
        return f"{int(seconds / 60)}m ago"
    elif seconds < 86400:
        return f"{int(seconds / 3600)}h ago"
    else:
        return f"{int(seconds / 86400)}d ago"


def format_json(data: Any) -> str:
    """Format data as pretty JSON string"""
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except:
            return data
    return json.dumps(data, indent=2)


def format_percentage(value: float, decimals: int = 2) -> str:
    """Format float as percentage string"""
    return f"{round(value, decimals)}%"


def format_file_size(bytes: int) -> str:
    """Format bytes as human-readable file size"""
    if bytes < 1024:
        return f"{bytes}B"
    elif bytes < 1024 * 1024:
        return f"{round(bytes / 1024, 2)}KB"
    elif bytes < 1024 * 1024 * 1024:
        return f"{round(bytes / (1024 * 1024), 2)}MB"
    else:
        return f"{round(bytes / (1024 * 1024 * 1024), 2)}GB"


# ============================================================================
# DATA VALIDATION
# ============================================================================

def is_valid_session_id(session_id: str) -> bool:
    """Validate session ID format"""
    return bool(session_id and isinstance(session_id, str) and len(session_id) > 0)


def is_valid_device_id(device_id: str) -> bool:
    """Validate device ID format"""
    return bool(device_id and isinstance(device_id, str) and len(device_id) > 0)


def sanitize_ip_address(ip: str) -> str:
    """Sanitize IP address for display"""
    if not ip or ip == "unknown":
        return "N/A"
    return ip


# ============================================================================
# CHART DATA PREPARATION
# ============================================================================

def prepare_line_chart_data(data_dict: Dict[str, int], days: int = 7) -> Dict[str, List]:
    """Prepare data for Chart.js line chart"""
    end_date = datetime.utcnow().date()
    start_date = end_date - timedelta(days=days - 1)
    
    labels = []
    values = []
    
    current = start_date
    while current <= end_date:
        date_str = current.isoformat()
        labels.append(date_str)
        values.append(data_dict.get(date_str, 0))
        current += timedelta(days=1)
    
    return {
        "labels": labels,
        "data": values
    }


def prepare_bar_chart_data(categories: Dict[str, int]) -> Dict[str, List]:
    """Prepare data for Chart.js bar chart"""
    return {
        "labels": list(categories.keys()),
        "data": list(categories.values())
    }


# ============================================================================
# RISK LEVEL CALCULATION
# ============================================================================

def calculate_risk_level(signals: Dict[str, Any]) -> str:
    """Calculate risk level based on bot detection signals"""
    score = 0
    
    # Check individual signals
    if signals.get('suspicious_user_agent'):
        score += 3
    if signals.get('missing_headers'):
        score += len(signals.get('missing_headers', [])) * 2
    if signals.get('automation_headers'):
        score += 4
    if signals.get('generic_accept'):
        score += 1
    if signals.get('no_language'):
        score += 2
    
    # Determine level
    if score >= 10:
        return "high"
    elif score >= 5:
        return "medium"
    else:
        return "low"


def get_risk_color(risk_level: str) -> str:
    """Get color code for risk level"""
    colors = {
        "high": "#ef4444",
        "medium": "#f59e0b",
        "low": "#10b981"
    }
    return colors.get(risk_level, "#94a3b8")


# ============================================================================
# PAGINATION HELPERS
# ============================================================================

def paginate(items: List[Any], page: int = 1, per_page: int = 50) -> Dict[str, Any]:
    """Paginate a list of items"""
    total = len(items)
    total_pages = (total + per_page - 1) // per_page  # Ceiling division
    
    start = (page - 1) * per_page
    end = start + per_page
    
    return {
        "items": items[start:end],
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages
    }


# ============================================================================
# JINJA2 TEMPLATE FILTERS
# ============================================================================

def format_timestamp(dt: datetime) -> str:
    """Format datetime for display in templates"""
    if not dt:
        return "N/A"
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def format_json_pretty(data: str) -> str:
    """Format JSON string with indentation"""
    if not data:
        return ""
    try:
        import json
        parsed = json.loads(data) if isinstance(data, str) else data
        return json.dumps(parsed, indent=2)
    except:
        return str(data)


def format_percentage(value: float) -> str:
    """Format number as percentage"""
    if value is None:
        return "0%"
    return f"{value:.1f}%"
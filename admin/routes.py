"""
Admin Dashboard Routes
"""

from fastapi import APIRouter, Request, Depends, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from datetime import datetime
from typing import Optional

from admin import auth, config, services, utils
from database import get_db, revoke_device_trust
from logger import log_admin_action

# Create router
router = APIRouter(prefix="/admin", tags=["admin"])

# Templates
templates = Jinja2Templates(directory="admin/templates")

# ... rest of your routes


# ============================================================================
# TEMPLATE FILTERS
# ============================================================================

templates.env.filters['format_timestamp'] = utils.format_timestamp
templates.env.filters['format_relative'] = utils.format_datetime_relative
templates.env.filters['format_percentage'] = utils.format_percentage
templates.env.filters['format_json'] = utils.format_json


# ============================================================================
# LOGIN / LOGOUT
# ============================================================================

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Admin login page"""
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...)
):
    """Process login"""
    client_ip = auth.get_client_ip(request)
    
    # Authenticate
    session_token = auth.authenticate(username, password, client_ip)
    
    if not session_token:
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Invalid username or password"
        })
    
    # Create response with session cookie
    response = RedirectResponse(url="/admin/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key=config.SESSION_COOKIE_NAME,
        value=session_token,
        httponly=config.SESSION_COOKIE_HTTPONLY,
        secure=config.SESSION_COOKIE_SECURE,
        max_age=config.SESSION_MAX_AGE
    )
    
    return response


@router.get("/logout")
async def logout(request: Request):
    """Logout and destroy session"""
    session_token = request.cookies.get(config.SESSION_COOKIE_NAME)
    
    if session_token:
        auth.destroy_session(session_token)
    
    response = RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(config.SESSION_COOKIE_NAME)
    
    return response


# ============================================================================
# DASHBOARD / OVERVIEW
# ============================================================================

@router.get("/", response_class=HTMLResponse)
@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    """Admin dashboard overview"""
    
    # Require authentication
    try:
        session = auth.require_auth(request)
    except HTTPException:
        return auth.create_redirect_to_login()
    
    # Get metrics
    metrics = services.get_dashboard_metrics(db)
    activity_data = services.get_activity_chart_data(db, days=7)
    breakdown_data = services.get_success_failure_breakdown(db, days=7)
    alerts = services.get_alerts(db)
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "session": session,
        "metrics": metrics,
        "activity_data": activity_data,
        "breakdown_data": breakdown_data,
        "alerts": alerts
    })


# ============================================================================
# SESSIONS
# ============================================================================

@router.get("/sessions", response_class=HTMLResponse)
async def sessions_page(request: Request, db: Session = Depends(get_db)):
    """Sessions management page"""
    
    try:
        session = auth.require_auth(request)
    except HTTPException:
        return auth.create_redirect_to_login()
    
    # Get all sessions
    sessions_list = services.get_all_sessions(db, limit=100)
    
    return templates.TemplateResponse("sessions.html", {
        "request": request,
        "session": session,
        "sessions": sessions_list
    })


@router.get("/sessions/{session_id}", response_class=HTMLResponse)
async def session_details(request: Request, session_id: str, db: Session = Depends(get_db)):
    """Session details page"""
    
    try:
        session = auth.require_auth(request)
    except HTTPException:
        return auth.create_redirect_to_login()
    
    # Get session details
    details = services.get_session_details(db, session_id)
    
    if not details:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return templates.TemplateResponse("sessions.html", {
        "request": request,
        "session": session,
        "session_details": details
    })


# ============================================================================
# CHALLENGES
# ============================================================================

@router.get("/challenges", response_class=HTMLResponse)
async def challenges_page(request: Request, db: Session = Depends(get_db)):
    """Challenges monitoring page"""
    
    try:
        session = auth.require_auth(request)
    except HTTPException:
        return auth.create_redirect_to_login()
    
    # Get challenges
    challenges_data = services.get_all_challenges(db, limit=100)
    stats = services.get_challenge_stats(db)
    
    return templates.TemplateResponse("challenges.html", {
        "request": request,
        "session": session,
        "challenges": challenges_data,
        "stats": stats
    })


# ============================================================================
# TRUSTED DEVICES
# ============================================================================

@router.get("/trusted-devices", response_class=HTMLResponse)
async def trusted_devices_page(request: Request, db: Session = Depends(get_db)):
    """Trusted devices management"""
    
    try:
        session = auth.require_auth(request)
    except HTTPException:
        return auth.create_redirect_to_login()
    
    # Get trusted devices
    devices = services.get_all_trusted_devices(db)
    
    return templates.TemplateResponse("trusted_devices.html", {
        "request": request,
        "session": session,
        "devices": devices
    })


@router.post("/trusted-devices/{device_id}/revoke")
async def revoke_device(request: Request, device_id: str, db: Session = Depends(get_db)):
    """Revoke device trust"""
    
    try:
        auth.require_auth(request)
    except HTTPException:
        return auth.create_redirect_to_login()
    
    # Revoke trust
    success = services.revoke_device_trust(db, device_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Device not found")
    
    return RedirectResponse(url="/admin/trusted-devices", status_code=status.HTTP_303_SEE_OTHER)





# ============================================================================
# BOT ACTIVITY
# ============================================================================

@router.get("/bot-activity", response_class=HTMLResponse)
async def bot_activity_page(request: Request, db: Session = Depends(get_db)):
    """Bot and suspicious activity monitoring"""
    
    try:
        session = auth.require_auth(request)
    except HTTPException:
        return auth.create_redirect_to_login()
    
    # Get bot reports
    reports = services.get_bot_reports(db, limit=100)
    stats = services.get_bot_statistics(db)
    
    return templates.TemplateResponse("bot_activity.html", {
        "request": request,
        "session": session,
        "reports": reports,
        "stats": stats
    })


# ============================================================================
# LOGS
# ============================================================================

@router.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request, db: Session = Depends(get_db)):
    """System logs viewer"""
    
    try:
        session = auth.require_auth(request)
    except HTTPException:
        return auth.create_redirect_to_login()
    
    # Get logs
    logs = services.get_system_logs(db, limit=200)
    
    return templates.TemplateResponse("logs.html", {
        "request": request,
        "session": session,
        "logs": logs
    })


@admin_router.post("/trusted-devices/{device_id}/revoke")
async def revoke_device_trust_endpoint(
    device_id: str,
    request: Request,
    db: Session = Depends(get_db),
    username: str = Depends(require_auth)
):
    """Revoke trust for a device"""
    
    success = revoke_device_trust(db, device_id, reason="Manual admin revocation")
    
    if success:
        # ✅ Log admin action
        log_admin_action(
            admin_user=username,
            action="revoke_device_trust",
            target=device_id,
            details={"reason": "manual_revocation"}
        )
        
        return {"status": "success", "message": f"Trust revoked for device {device_id}"}
    else:
        return {"status": "error", "message": "Device not found"}


# ============================================================================
# SYSTEM HEALTH
# ============================================================================

@router.get("/system-health", response_class=HTMLResponse)
async def system_health_page(request: Request, db: Session = Depends(get_db)):
    """System health monitoring"""
    
    try:
        session = auth.require_auth(request)
    except HTTPException:
        return auth.create_redirect_to_login()
    
    # Get system health
    health = services.get_system_health()
    processing = services.get_processing_metrics(db)
    
    return templates.TemplateResponse("system_health.html", {
        "request": request,
        "session": session,
        "health": health,
        "processing": processing
    })
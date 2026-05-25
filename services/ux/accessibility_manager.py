"""
Accessibility Manager
WCAG 2.1 AA compliance with fallback paths
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class AccessibilityFeature(str, Enum):
    """Accessibility features"""
    SCREEN_READER = "screen_reader"
    KEYBOARD_NAVIGATION = "keyboard_navigation"
    HIGH_CONTRAST = "high_contrast"
    REDUCED_MOTION = "reduced_motion"
    CAPTIONS = "captions"
    AUDIO_DESCRIPTIONS = "audio_descriptions"


class FallbackMethod(str, Enum):
    """Alternative verification methods"""
    MANUAL_REVIEW = "manual_review"
    DOCUMENT_UPLOAD = "document_upload"
    SMS_VERIFICATION = "sms_verification"
    EMAIL_VERIFICATION = "email_verification"
    SUPPORT_ASSISTED = "support_assisted"


@dataclass
class AccessibilityConfig:
    """User accessibility configuration"""
    screen_reader_enabled: bool = False
    keyboard_only: bool = False
    high_contrast: bool = False
    reduced_motion: bool = False
    
    # User preferences
    font_size: str = "normal"  # "small", "normal", "large", "extra_large"
    language: str = "en"
    
    # Detected capabilities
    camera_available: bool = True
    microphone_available: bool = True
    
    # Fallback path
    needs_fallback: bool = False
    fallback_reason: Optional[str] = None


class AccessibilityManager:
    """
    Accessibility Manager
    
    Features:
    - WCAG 2.1 AA compliance
    - Screen reader support
    - Keyboard navigation
    - High contrast mode
    - Reduced motion
    - Camera/mic fallback paths
    
    ACCEPTANCE CRITERIA:
    - Fallback path when camera/mic unsupported
    - WCAG-informed UI improvements
    """
    
    # WCAG 2.1 AA Requirements
    WCAG_REQUIREMENTS = {
        "color_contrast": {
            "normal_text": 4.5,  # Minimum contrast ratio
            "large_text": 3.0,
            "ui_components": 3.0
        },
        "text_sizing": {
            "min_font_size": 14,  # px
            "line_height": 1.5,
            "paragraph_spacing": 2.0
        },
        "timing": {
            "default_timeout": 30,  # seconds
            "adjustable": True,
            "can_disable": True
        },
        "navigation": {
            "keyboard_accessible": True,
            "focus_visible": True,
            "skip_links": True
        }
    }
    
    def detect_accessibility_needs(
        self,
        user_agent: str,
        browser_features: Dict[str, Any]
    ) -> AccessibilityConfig:
        """
        Detect user's accessibility needs
        
        Args:
            user_agent: User agent string
            browser_features: Browser capabilities
        
        Returns:
            Accessibility configuration
        """
        
        config = AccessibilityConfig()
        
        # Detect screen reader
        screen_reader_indicators = [
            "NVDA", "JAWS", "VoiceOver", "TalkBack", "ChromeVox"
        ]
        
        config.screen_reader_enabled = any(
            indicator in user_agent for indicator in screen_reader_indicators
        )
        
        # Detect camera availability
        config.camera_available = browser_features.get("camera", False)
        config.microphone_available = browser_features.get("microphone", False)
        
        # Detect preferences from browser
        if "prefers-reduced-motion" in browser_features:
            config.reduced_motion = browser_features["prefers-reduced-motion"]
        
        if "prefers-contrast" in browser_features:
            config.high_contrast = browser_features["prefers-contrast"] == "high"
        
        # Determine if fallback needed
        if not config.camera_available:
            config.needs_fallback = True
            config.fallback_reason = "camera_unavailable"
        
        logger.info(
            f"♿ Accessibility detection:\n"
            f"   Screen reader: {config.screen_reader_enabled}\n"
            f"   Camera: {config.camera_available}\n"
            f"   Microphone: {config.microphone_available}\n"
            f"   High contrast: {config.high_contrast}\n"
            f"   Reduced motion: {config.reduced_motion}\n"
            f"   Needs fallback: {config.needs_fallback}"
        )
        
        return config
    
    def get_fallback_options(
        self,
        reason: str,
        user_context: Optional[Dict[str, Any]] = None
    ) -> List[FallbackMethod]:
        """
        Get fallback verification options
        
        Args:
            reason: Reason for fallback
            user_context: Optional user context
        
        Returns:
            List of fallback options
        """
        
        fallback_options = []
        
        if reason == "camera_unavailable":
            # Camera not available - offer alternatives
            fallback_options = [
                FallbackMethod.DOCUMENT_UPLOAD,
                FallbackMethod.SMS_VERIFICATION,
                FallbackMethod.EMAIL_VERIFICATION,
                FallbackMethod.SUPPORT_ASSISTED
            ]
        
        elif reason == "camera_permission_denied":
            # User denied camera - suggest alternatives
            fallback_options = [
                FallbackMethod.DOCUMENT_UPLOAD,
                FallbackMethod.MANUAL_REVIEW
            ]
        
        elif reason == "repeated_failure":
            # Multiple failed attempts - offer help
            fallback_options = [
                FallbackMethod.SUPPORT_ASSISTED,
                FallbackMethod.DOCUMENT_UPLOAD
            ]
        
        elif reason == "accessibility_required":
            # User requires accessible path
            fallback_options = [
                FallbackMethod.DOCUMENT_UPLOAD,
                FallbackMethod.SMS_VERIFICATION,
                FallbackMethod.SUPPORT_ASSISTED
            ]
        
        logger.info(
            f"🔄 Fallback options for '{reason}':\n"
            f"   Options: {', '.join([o.value for o in fallback_options])}"
        )
        
        return fallback_options
    
    def get_wcag_compliant_styles(
        self,
        config: AccessibilityConfig
    ) -> Dict[str, Any]:
        """
        Get WCAG-compliant CSS styles
        
        Args:
            config: Accessibility configuration
        
        Returns:
            CSS style configuration
        """
        
        styles = {
            "fontSize": "16px",
            "lineHeight": "1.5",
            "color": "#000000",
            "backgroundColor": "#FFFFFF",
            "focusOutline": "3px solid #0066CC",
            "buttonMinHeight": "44px",  # Touch target size
            "buttonMinWidth": "44px"
        }
        
        # High contrast mode
        if config.high_contrast:
            styles.update({
                "color": "#000000",
                "backgroundColor": "#FFFFFF",
                "borderColor": "#000000",
                "borderWidth": "2px",
                "focusOutline": "4px solid #000000"
            })
        
        # Large text
        if config.font_size == "large":
            styles["fontSize"] = "18px"
        elif config.font_size == "extra_large":
            styles["fontSize"] = "20px"
        
        # Reduced motion
        if config.reduced_motion:
            styles.update({
                "animation": "none",
                "transition": "none"
            })
        
        return styles
    
    def get_aria_labels(
        self,
        component: str,
        state: Dict[str, Any],
        language: str = "en"
    ) -> Dict[str, str]:
        """
        Get ARIA labels for component
        
        Args:
            component: Component name
            state: Component state
            language: Language code
        
        Returns:
            ARIA attributes
        """
        
        aria_labels = {
            "camera_view": {
                "en": {
                    "role": "region",
                    "aria-label": "Camera preview",
                    "aria-live": "polite",
                    "aria-describedby": "camera-instructions"
                }
            },
            "challenge_button": {
                "en": {
                    "role": "button",
                    "aria-label": "Start verification challenge",
                    "aria-pressed": "false"
                }
            },
            "progress_indicator": {
                "en": {
                    "role": "progressbar",
                    "aria-label": "Verification progress",
                    "aria-valuenow": str(state.get("progress", 0)),
                    "aria-valuemin": "0",
                    "aria-valuemax": "100"
                }
            }
        }
        
        return aria_labels.get(component, {}).get(language, {})
    
    def announce_to_screen_reader(
        self,
        message: str,
        priority: str = "polite"
    ) -> Dict[str, Any]:
        """
        Create screen reader announcement
        
        Args:
            message: Message to announce
            priority: "polite" or "assertive"
        
        Returns:
            Screen reader announcement config
        """
        
        return {
            "role": "status",
            "aria-live": priority,
            "aria-atomic": "true",
            "message": message
        }
"""
Real-Time Guidance System
Clear, progressive instructions during verification
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class GuidancePhase(str, Enum):
    """Verification phases"""
    INITIAL = "initial"
    CONSENT = "consent"
    CAMERA_SETUP = "camera_setup"
    POSITIONING = "positioning"
    CHALLENGE = "challenge"
    PROCESSING = "processing"
    COMPLETE = "complete"
    ERROR = "error"


class ChallengeAction(str, Enum):
    """Challenge action types"""
    BLINK = "blink"
    SMILE = "smile"
    HEAD_TURN_LEFT = "head_turn_left"
    HEAD_TURN_RIGHT = "head_turn_right"
    NOD = "nod"
    RAISE_EYEBROWS = "raise_eyebrows"
    OPEN_MOUTH = "open_mouth"


@dataclass
class GuidanceMessage:
    """Real-time guidance message"""
    phase: GuidancePhase
    message: str
    message_type: str  # "instruction", "feedback", "error", "success"
    
    # Visual guidance
    icon: Optional[str] = None
    animation: Optional[str] = None
    
    # Audio guidance (optional)
    audio_url: Optional[str] = None
    
    # Accessibility
    aria_label: str = ""
    screen_reader_text: str = ""
    
    # Multi-language support
    message_key: str = ""  # For translation lookup


class GuidanceSystem:
    """
    Real-Time Guidance System
    
    Features:
    - Progressive instructions
    - Real-time feedback
    - Multi-language support
    - Screen reader support
    - Clear error messages
    
    ACCEPTANCE CRITERIA:
    - Clear real-time guidance during capture
    """
    
    # Guidance messages for each phase
    GUIDANCE_TEMPLATES = {
        GuidancePhase.INITIAL: {
            "en": {
                "title": "Welcome to Verification",
                "message": "We'll verify you're a real person in about 15 seconds",
                "instruction": "Tap 'Start' when ready",
                "icon": "👋",
                "aria_label": "Welcome screen. Verification takes about 15 seconds"
            },
            "es": {
                "title": "Bienvenido a la Verificación",
                "message": "Verificaremos que eres una persona real en unos 15 segundos",
                "instruction": "Toca 'Comenzar' cuando estés listo",
                "icon": "👋",
                "aria_label": "Pantalla de bienvenida. La verificación toma unos 15 segundos"
            },
            "fr": {
                "title": "Bienvenue à la Vérification",
                "message": "Nous vérifierons que vous êtes une vraie personne en 15 secondes",
                "instruction": "Appuyez sur 'Commencer' quand vous êtes prêt",
                "icon": "👋",
                "aria_label": "Écran de bienvenue. La vérification prend environ 15 secondes"
            }
        },
        
        GuidancePhase.CONSENT: {
            "en": {
                "title": "Your Privacy Matters",
                "message": "We need your permission to use your camera for verification",
                "instruction": "Review and accept to continue",
                "icon": "🔒",
                "aria_label": "Privacy consent screen. Review terms and accept to continue"
            },
            "es": {
                "title": "Tu Privacidad Importa",
                "message": "Necesitamos tu permiso para usar tu cámara para verificación",
                "instruction": "Revisa y acepta para continuar",
                "icon": "🔒",
                "aria_label": "Pantalla de consentimiento. Revisa términos y acepta para continuar"
            }
        },
        
        GuidancePhase.CAMERA_SETUP: {
            "en": {
                "title": "Camera Setup",
                "message": "Position your face in the frame",
                "instruction": "Make sure your face is visible and well-lit",
                "icon": "📷",
                "aria_label": "Camera setup. Position your face in the frame with good lighting"
            },
            "es": {
                "title": "Configuración de Cámara",
                "message": "Coloca tu rostro en el marco",
                "instruction": "Asegúrate de que tu rostro esté visible y bien iluminado",
                "icon": "📷",
                "aria_label": "Configuración de cámara. Coloca tu rostro en el marco con buena iluminación"
            }
        },
        
        GuidancePhase.POSITIONING: {
            "en": {
                "good_position": {
                    "message": "Perfect! Hold still",
                    "type": "success",
                    "icon": "✅",
                    "aria_label": "Good position. Hold still"
                },
                "move_closer": {
                    "message": "Move a bit closer",
                    "type": "instruction",
                    "icon": "➡️",
                    "aria_label": "Move closer to camera"
                },
                "move_back": {
                    "message": "Move a bit farther",
                    "type": "instruction",
                    "icon": "⬅️",
                    "aria_label": "Move back from camera"
                },
                "too_dark": {
                    "message": "More light needed",
                    "type": "instruction",
                    "icon": "💡",
                    "aria_label": "Increase lighting"
                },
                "face_not_detected": {
                    "message": "Position your face in the frame",
                    "type": "instruction",
                    "icon": "👤",
                    "aria_label": "Face not detected. Center your face in frame"
                }
            }
        }
    }
    
    # Challenge-specific guidance
    CHALLENGE_GUIDANCE = {
        ChallengeAction.BLINK: {
            "en": {
                "prepare": "Get ready to blink",
                "execute": "Blink now",
                "success": "Great! Blink detected",
                "retry": "Try blinking again",
                "icon": "👁️",
                "animation": "blink-demo.gif"
            },
            "es": {
                "prepare": "Prepárate para parpadear",
                "execute": "Parpadea ahora",
                "success": "¡Genial! Parpadeo detectado",
                "retry": "Intenta parpadear de nuevo",
                "icon": "👁️"
            }
        },
        
        ChallengeAction.SMILE: {
            "en": {
                "prepare": "Get ready to smile",
                "execute": "Smile now 😊",
                "success": "Perfect smile!",
                "retry": "Try smiling again",
                "icon": "😊",
                "animation": "smile-demo.gif"
            },
            "es": {
                "prepare": "Prepárate para sonreír",
                "execute": "Sonríe ahora 😊",
                "success": "¡Sonrisa perfecta!",
                "retry": "Intenta sonreír de nuevo",
                "icon": "😊"
            }
        },
        
        ChallengeAction.HEAD_TURN_LEFT: {
            "en": {
                "prepare": "Get ready to turn your head",
                "execute": "Turn your head left ⬅️",
                "success": "Good turn!",
                "retry": "Turn left a bit more",
                "icon": "⬅️",
                "animation": "turn-left-demo.gif"
            },
            "es": {
                "prepare": "Prepárate para girar la cabeza",
                "execute": "Gira tu cabeza a la izquierda ⬅️",
                "success": "¡Buen giro!",
                "retry": "Gira más a la izquierda",
                "icon": "⬅️"
            }
        },
        
        ChallengeAction.HEAD_TURN_RIGHT: {
            "en": {
                "prepare": "Get ready to turn your head",
                "execute": "Turn your head right ➡️",
                "success": "Good turn!",
                "retry": "Turn right a bit more",
                "icon": "➡️",
                "animation": "turn-right-demo.gif"
            },
            "es": {
                "prepare": "Prepárate para girar la cabeza",
                "execute": "Gira tu cabeza a la derecha ➡️",
                "success": "¡Buen giro!",
                "retry": "Gira más a la derecha",
                "icon": "➡️"
            }
        },
        
        ChallengeAction.NOD: {
            "en": {
                "prepare": "Get ready to nod",
                "execute": "Nod your head ⬇️",
                "success": "Perfect nod!",
                "retry": "Try nodding again",
                "icon": "⬇️",
                "animation": "nod-demo.gif"
            },
            "es": {
                "prepare": "Prepárate para asentir",
                "execute": "Asiente con la cabeza ⬇️",
                "success": "¡Asentimiento perfecto!",
                "retry": "Intenta asentir de nuevo",
                "icon": "⬇️"
            }
        },
        
        ChallengeAction.RAISE_EYEBROWS: {
            "en": {
                "prepare": "Get ready to raise your eyebrows",
                "execute": "Raise your eyebrows",
                "success": "Great expression!",
                "retry": "Try raising them higher",
                "icon": "😮",
                "animation": "eyebrow-demo.gif"
            },
            "es": {
                "prepare": "Prepárate para levantar las cejas",
                "execute": "Levanta las cejas",
                "success": "¡Genial expresión!",
                "retry": "Intenta levantarlas más",
                "icon": "😮"
            }
        }
    }
    
    def get_phase_guidance(
        self,
        phase: GuidancePhase,
        language: str = "en",
        context: Optional[Dict[str, Any]] = None
    ) -> GuidanceMessage:
        """
        Get guidance for current phase
        
        Args:
            phase: Current phase
            language: Language code
            context: Optional context data
        
        Returns:
            Guidance message
        """
        
        template = self.GUIDANCE_TEMPLATES.get(phase, {}).get(language, {})
        
        if not template:
            # Fallback to English
            template = self.GUIDANCE_TEMPLATES.get(phase, {}).get("en", {})
        
        message = GuidanceMessage(
            phase=phase,
            message=template.get("message", ""),
            message_type="instruction",
            icon=template.get("icon"),
            aria_label=template.get("aria_label", template.get("message", "")),
            screen_reader_text=template.get("aria_label", template.get("message", ""))
        )
        
        return message
    
    def get_challenge_guidance(
        self,
        action: ChallengeAction,
        stage: str,  # "prepare", "execute", "success", "retry"
        language: str = "en"
    ) -> GuidanceMessage:
        """
        Get challenge-specific guidance
        
        Args:
            action: Challenge action
            stage: Current stage
            language: Language code
        
        Returns:
            Guidance message
        """
        
        guidance = self.CHALLENGE_GUIDANCE.get(action, {}).get(language, {})
        
        if not guidance:
            # Fallback to English
            guidance = self.CHALLENGE_GUIDANCE.get(action, {}).get("en", {})
        
        message_text = guidance.get(stage, "")
        message_type = "success" if stage == "success" else "instruction"
        
        message = GuidanceMessage(
            phase=GuidancePhase.CHALLENGE,
            message=message_text,
            message_type=message_type,
            icon=guidance.get("icon"),
            animation=guidance.get("animation"),
            aria_label=message_text,
            screen_reader_text=message_text
        )
        
        return message
    
    def get_positioning_feedback(
        self,
        face_detected: bool,
        face_size: float,  # 0-1 scale
        lighting_score: float,  # 0-1 scale
        language: str = "en"
    ) -> GuidanceMessage:
        """
        Get real-time positioning feedback
        
        Args:
            face_detected: Whether face is detected
            face_size: Relative face size
            lighting_score: Lighting quality score
            language: Language code
        
        Returns:
            Guidance message
        """
        
        positioning = self.GUIDANCE_TEMPLATES[GuidancePhase.POSITIONING].get(language, {})
        
        if not face_detected:
            feedback = positioning.get("face_not_detected", {})
        elif lighting_score < 0.3:
            feedback = positioning.get("too_dark", {})
        elif face_size < 0.4:
            feedback = positioning.get("move_closer", {})
        elif face_size > 0.8:
            feedback = positioning.get("move_back", {})
        else:
            feedback = positioning.get("good_position", {})
        
        message = GuidanceMessage(
            phase=GuidancePhase.POSITIONING,
            message=feedback.get("message", ""),
            message_type=feedback.get("type", "instruction"),
            icon=feedback.get("icon"),
            aria_label=feedback.get("aria_label", feedback.get("message", "")),
            screen_reader_text=feedback.get("aria_label", feedback.get("message", ""))
        )
        
        return message
    
    def get_error_guidance(
        self,
        error_code: str,
        language: str = "en"
    ) -> GuidanceMessage:
        """
        Get user-friendly error guidance
        
        Args:
            error_code: Error code
            language: Language code
        
        Returns:
            Guidance message
        """
        
        error_messages = {
            "camera_permission_denied": {
                "en": {
                    "message": "Camera access is needed for verification",
                    "instruction": "Please allow camera access in your browser settings",
                    "recovery": "fallback_available"
                },
                "es": {
                    "message": "Se necesita acceso a la cámara para verificación",
                    "instruction": "Por favor permite el acceso a la cámara en la configuración de tu navegador"
                }
            },
            "camera_not_found": {
                "en": {
                    "message": "No camera detected",
                    "instruction": "Please connect a camera or use a device with a camera",
                    "recovery": "fallback_available"
                },
                "es": {
                    "message": "No se detectó cámara",
                    "instruction": "Por favor conecta una cámara o usa un dispositivo con cámara"
                }
            },
            "poor_lighting": {
                "en": {
                    "message": "Lighting is too low",
                    "instruction": "Move to a brighter area or turn on more lights",
                    "recovery": "retry"
                },
                "es": {
                    "message": "La iluminación es muy baja",
                    "instruction": "Muévete a un área más iluminada o enciende más luces"
                }
            },
            "face_not_detected": {
                "en": {
                    "message": "Couldn't detect your face",
                    "instruction": "Make sure your face is clearly visible in the frame",
                    "recovery": "retry"
                },
                "es": {
                    "message": "No se pudo detectar tu rostro",
                    "instruction": "Asegúrate de que tu rostro esté claramente visible en el marco"
                }
            },
            "challenge_timeout": {
                "en": {
                    "message": "Time ran out",
                    "instruction": "Let's try again with a bit more time",
                    "recovery": "retry"
                },
                "es": {
                    "message": "Se acabó el tiempo",
                    "instruction": "Intentemos de nuevo con un poco más de tiempo"
                }
            },
            "upload_failed": {
                "en": {
                    "message": "Upload failed",
                    "instruction": "Check your internet connection and try again",
                    "recovery": "retry"
                },
                "es": {
                    "message": "Falló la carga",
                    "instruction": "Verifica tu conexión a internet e intenta de nuevo"
                }
            }
        }
        
        error_data = error_messages.get(error_code, {}).get(language, {})
        
        if not error_data:
            # Fallback to English
            error_data = error_messages.get(error_code, {}).get("en", {})
        
        if not error_data:
            # Generic error
            error_data = {
                "message": "Something went wrong",
                "instruction": "Please try again",
                "recovery": "retry"
            }
        
        message = GuidanceMessage(
            phase=GuidancePhase.ERROR,
            message=error_data.get("message", ""),
            message_type="error",
            icon="⚠️",
            aria_label=f"Error: {error_data.get('message', '')}. {error_data.get('instruction', '')}",
            screen_reader_text=f"Error occurred. {error_data.get('message', '')}. {error_data.get('instruction', '')}"
        )
        
        return message
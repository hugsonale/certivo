"""
Challenge Template System
Composite, accessible, and locale-aware challenge templates
"""

from typing import Dict, Any, List, Optional, Tuple
from enum import Enum
from dataclasses import dataclass
import secrets
import random
from datetime import datetime


class ChallengeType(str, Enum):
    """Challenge type categories"""
    MOTION = "motion"               # Head movements
    FACIAL = "facial"               # Facial expressions
    VISUAL = "visual"               # Eye movements, blinking
    AUDIO = "audio"                 # Speech/reading
    COMPOSITE = "composite"         # Multiple actions
    ACCESSIBLE = "accessible"       # Accessibility alternatives


class ActionType(str, Enum):
    """Individual action types"""
    # Motion actions
    TURN_HEAD_LEFT = "turn_head_left"
    TURN_HEAD_RIGHT = "turn_head_right"
    TURN_HEAD_UP = "turn_head_up"
    TURN_HEAD_DOWN = "turn_head_down"
    NOD = "nod"
    SHAKE_HEAD = "shake_head"
    TILT_LEFT = "tilt_left"
    TILT_RIGHT = "tilt_right"
    
    # Facial actions
    BLINK = "blink"
    SMILE = "smile"
    RAISE_EYEBROWS = "raise_eyebrows"
    CLOSE_EYES = "close_eyes"
    OPEN_MOUTH = "open_mouth"
    
    # Visual actions
    LOOK_LEFT = "look_left"
    LOOK_RIGHT = "look_right"
    LOOK_UP = "look_up"
    LOOK_DOWN = "look_down"
    
    # Audio actions
    READ_DIGITS = "read_digits"
    SPEAK_PHRASE = "speak_phrase"
    COUNT_ALOUD = "count_aloud"


class Locale(str, Enum):
    """Supported locales"""
    EN_US = "en-US"
    EN_GB = "en-GB"
    ES_ES = "es-ES"
    ES_MX = "es-MX"
    FR_FR = "fr-FR"
    DE_DE = "de-DE"
    IT_IT = "it-IT"
    PT_BR = "pt-BR"
    ZH_CN = "zh-CN"
    JA_JP = "ja-JP"
    KO_KR = "ko-KR"
    AR_SA = "ar-SA"
    HI_IN = "hi-IN"
    RU_RU = "ru-RU"


@dataclass
class Action:
    """Single action within a challenge"""
    action_type: ActionType
    direction: Optional[str] = None
    intensity: Optional[str] = None  # subtle, normal, strong
    timing: Optional[str] = None     # slow, normal, fast
    duration_seconds: Optional[float] = None
    count: Optional[int] = None      # For repeated actions
    value: Optional[str] = None      # For reading digits/phrases
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "action": self.action_type.value,
            "direction": self.direction,
            "intensity": self.intensity,
            "timing": self.timing,
            "duration_seconds": self.duration_seconds,
            "count": self.count,
            "value": self.value
        }


@dataclass
class ChallengeTemplate:
    """Challenge template definition"""
    template_id: str
    name: str
    challenge_type: ChallengeType
    description: str
    actions: List[Action]
    estimated_duration_seconds: float
    difficulty: str  # easy, medium, hard
    accessibility_level: str  # universal, limited_mobility, vision_impaired, hearing_impaired
    entropy_bits: float
    
    # Locale support
    supports_locales: List[Locale]
    
    # Accessibility metadata
    requires_motion: bool = True
    requires_vision: bool = True
    requires_audio: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "template_id": self.template_id,
            "name": self.name,
            "challenge_type": self.challenge_type.value,
            "description": self.description,
            "actions": [a.to_dict() for a in self.actions],
            "estimated_duration_seconds": self.estimated_duration_seconds,
            "difficulty": self.difficulty,
            "accessibility_level": self.accessibility_level,
            "entropy_bits": self.entropy_bits,
            "supports_locales": [l.value for l in self.supports_locales],
            "requires_motion": self.requires_motion,
            "requires_vision": self.requires_vision,
            "requires_audio": self.requires_audio
        }


class ChallengeTemplateLibrary:
    """
    Library of challenge templates
    
    Features:
    - 12+ templates for variety
    - Composite multi-step challenges
    - Accessibility alternatives
    - Locale-aware prompts
    """
    
    def __init__(self):
        self.templates: Dict[str, ChallengeTemplate] = {}
        self._initialize_templates()
    
    def _initialize_templates(self):
        """Initialize all challenge templates"""
        
        # ============================================================
        # TEMPLATE 1: Simple Head Turn
        # ============================================================
        self.templates["T01_SIMPLE_TURN"] = ChallengeTemplate(
            template_id="T01_SIMPLE_TURN",
            name="Simple Head Turn",
            challenge_type=ChallengeType.MOTION,
            description="Turn your head to one side",
            actions=[
                Action(
                    action_type=ActionType.TURN_HEAD_LEFT,
                    direction="left",
                    intensity="normal",
                    timing="normal",
                    duration_seconds=1.5
                )
            ],
            estimated_duration_seconds=2.0,
            difficulty="easy",
            accessibility_level="universal",
            entropy_bits=2.0,  # 4 directions
            supports_locales=[l for l in Locale],
            requires_motion=True,
            requires_vision=True,
            requires_audio=False
        )
        
        # ============================================================
        # TEMPLATE 2: Blink Sequence
        # ============================================================
        self.templates["T02_BLINK_SEQUENCE"] = ChallengeTemplate(
            template_id="T02_BLINK_SEQUENCE",
            name="Blink Sequence",
            challenge_type=ChallengeType.FACIAL,
            description="Blink your eyes a specific number of times",
            actions=[
                Action(
                    action_type=ActionType.BLINK,
                    count=3,  # Will be randomized 2-4
                    timing="normal"
                )
            ],
            estimated_duration_seconds=3.0,
            difficulty="easy",
            accessibility_level="universal",
            entropy_bits=1.6,  # 3 possible counts (2, 3, 4)
            supports_locales=[l for l in Locale],
            requires_motion=False,
            requires_vision=True,
            requires_audio=False
        )
        
        # ============================================================
        # TEMPLATE 3: Smile and Nod
        # ============================================================
        self.templates["T03_SMILE_NOD"] = ChallengeTemplate(
            template_id="T03_SMILE_NOD",
            name="Smile and Nod",
            challenge_type=ChallengeType.COMPOSITE,
            description="Smile, then nod your head",
            actions=[
                Action(
                    action_type=ActionType.SMILE,
                    intensity="normal",
                    duration_seconds=1.0
                ),
                Action(
                    action_type=ActionType.NOD,
                    count=2,
                    timing="normal"
                )
            ],
            estimated_duration_seconds=4.0,
            difficulty="easy",
            accessibility_level="universal",
            entropy_bits=3.0,  # 2 actions
            supports_locales=[l for l in Locale],
            requires_motion=True,
            requires_vision=True,
            requires_audio=False
        )
        
        # ============================================================
        # TEMPLATE 4: Turn Left, Blink Twice
        # ============================================================
        self.templates["T04_TURN_BLINK"] = ChallengeTemplate(
            template_id="T04_TURN_BLINK",
            name="Turn Left, Blink Twice",
            challenge_type=ChallengeType.COMPOSITE,
            description="Turn your head left, then blink twice",
            actions=[
                Action(
                    action_type=ActionType.TURN_HEAD_LEFT,
                    direction="left",
                    intensity="normal",
                    duration_seconds=1.5
                ),
                Action(
                    action_type=ActionType.BLINK,
                    count=2,
                    timing="normal"
                )
            ],
            estimated_duration_seconds=4.0,
            difficulty="medium",
            accessibility_level="universal",
            entropy_bits=4.6,  # 4 directions × 3 blink counts
            supports_locales=[l for l in Locale],
            requires_motion=True,
            requires_vision=True,
            requires_audio=False
        )
        
        # ============================================================
        # TEMPLATE 5: Read Random Digits
        # ============================================================
        self.templates["T05_READ_DIGITS"] = ChallengeTemplate(
            template_id="T05_READ_DIGITS",
            name="Read Random Digits",
            challenge_type=ChallengeType.AUDIO,
            description="Read the displayed digits aloud",
            actions=[
                Action(
                    action_type=ActionType.READ_DIGITS,
                    value="XXX",  # Placeholder, will be random
                    duration_seconds=3.0
                )
            ],
            estimated_duration_seconds=5.0,
            difficulty="easy",
            accessibility_level="universal",
            entropy_bits=9.97,  # 3 digits = 1000 combinations
            supports_locales=[l for l in Locale],
            requires_motion=False,
            requires_vision=True,
            requires_audio=True
        )
        
        # ============================================================
        # TEMPLATE 6: Turn Left → Blink Twice → Read Digits
        # ============================================================
        self.templates["T06_COMPOSITE_FULL"] = ChallengeTemplate(
            template_id="T06_COMPOSITE_FULL",
            name="Turn, Blink, Read (Full Composite)",
            challenge_type=ChallengeType.COMPOSITE,
            description="Turn left, blink twice, then read the displayed digits",
            actions=[
                Action(
                    action_type=ActionType.TURN_HEAD_LEFT,
                    direction="left",
                    intensity="normal",
                    duration_seconds=1.5
                ),
                Action(
                    action_type=ActionType.BLINK,
                    count=2,
                    timing="normal"
                ),
                Action(
                    action_type=ActionType.READ_DIGITS,
                    value="XXX",  # Random 3 digits
                    duration_seconds=3.0
                )
            ],
            estimated_duration_seconds=8.0,
            difficulty="hard",
            accessibility_level="universal",
            entropy_bits=14.6,  # 4 × 3 × 1000
            supports_locales=[l for l in Locale],
            requires_motion=True,
            requires_vision=True,
            requires_audio=True
        )
        
        # ============================================================
        # TEMPLATE 7: Look Around Sequence
        # ============================================================
        self.templates["T07_LOOK_SEQUENCE"] = ChallengeTemplate(
            template_id="T07_LOOK_SEQUENCE",
            name="Look Around Sequence",
            challenge_type=ChallengeType.VISUAL,
            description="Look left, then right, then center",
            actions=[
                Action(
                    action_type=ActionType.LOOK_LEFT,
                    direction="left",
                    duration_seconds=1.0
                ),
                Action(
                    action_type=ActionType.LOOK_RIGHT,
                    direction="right",
                    duration_seconds=1.0
                )
            ],
            estimated_duration_seconds=3.0,
            difficulty="easy",
            accessibility_level="universal",
            entropy_bits=3.6,  # Different sequences
            supports_locales=[l for l in Locale],
            requires_motion=False,
            requires_vision=True,
            requires_audio=False
        )
        
        # ============================================================
        # TEMPLATE 8: Nod and Smile
        # ============================================================
        self.templates["T08_NOD_SMILE"] = ChallengeTemplate(
            template_id="T08_NOD_SMILE",
            name="Nod and Smile",
            challenge_type=ChallengeType.COMPOSITE,
            description="Nod once, then smile",
            actions=[
                Action(
                    action_type=ActionType.NOD,
                    count=1,
                    timing="normal"
                ),
                Action(
                    action_type=ActionType.SMILE,
                    intensity="normal",
                    duration_seconds=1.5
                )
            ],
            estimated_duration_seconds=4.0,
            difficulty="easy",
            accessibility_level="universal",
            entropy_bits=2.6,
            supports_locales=[l for l in Locale],
            requires_motion=True,
            requires_vision=True,
            requires_audio=False
        )
        
        # ============================================================
        # TEMPLATE 9: Raise Eyebrows and Blink
        # ============================================================
        self.templates["T09_EYEBROW_BLINK"] = ChallengeTemplate(
            template_id="T09_EYEBROW_BLINK",
            name="Raise Eyebrows and Blink",
            challenge_type=ChallengeType.FACIAL,
            description="Raise your eyebrows, then blink",
            actions=[
                Action(
                    action_type=ActionType.RAISE_EYEBROWS,
                    intensity="normal",
                    duration_seconds=1.0
                ),
                Action(
                    action_type=ActionType.BLINK,
                    count=1,
                    timing="normal"
                )
            ],
            estimated_duration_seconds=3.0,
            difficulty="medium",
            accessibility_level="universal",
            entropy_bits=2.0,
            supports_locales=[l for l in Locale],
            requires_motion=False,
            requires_vision=True,
            requires_audio=False
        )
        
        # ============================================================
        # TEMPLATE 10: Tilt and Turn
        # ============================================================
        self.templates["T10_TILT_TURN"] = ChallengeTemplate(
            template_id="T10_TILT_TURN",
            name="Tilt and Turn",
            challenge_type=ChallengeType.MOTION,
            description="Tilt your head right, then turn left",
            actions=[
                Action(
                    action_type=ActionType.TILT_RIGHT,
                    direction="right",
                    intensity="normal",
                    duration_seconds=1.5
                ),
                Action(
                    action_type=ActionType.TURN_HEAD_LEFT,
                    direction="left",
                    intensity="normal",
                    duration_seconds=1.5
                )
            ],
            estimated_duration_seconds=4.0,
            difficulty="medium",
            accessibility_level="universal",
            entropy_bits=4.0,  # 2 tilts × 4 turns
            supports_locales=[l for l in Locale],
            requires_motion=True,
            requires_vision=True,
            requires_audio=False
        )
        
        # ============================================================
        # TEMPLATE 11: Count Aloud (Accessible)
        # ============================================================
        self.templates["T11_COUNT_ALOUD"] = ChallengeTemplate(
            template_id="T11_COUNT_ALOUD",
            name="Count Aloud (Accessible)",
            challenge_type=ChallengeType.AUDIO,
            description="Count from 1 to a specified number",
            actions=[
                Action(
                    action_type=ActionType.COUNT_ALOUD,
                    count=3,  # Count to 3
                    duration_seconds=3.0
                )
            ],
            estimated_duration_seconds=4.0,
            difficulty="easy",
            accessibility_level="limited_mobility",
            entropy_bits=2.3,  # Different ending numbers
            supports_locales=[l for l in Locale],
            requires_motion=False,
            requires_vision=False,
            requires_audio=True
        )
        
        # ============================================================
        # TEMPLATE 12: Speak Phrase (Accessible)
        # ============================================================
        self.templates["T12_SPEAK_PHRASE"] = ChallengeTemplate(
            template_id="T12_SPEAK_PHRASE",
            name="Speak Phrase (Accessible)",
            challenge_type=ChallengeType.AUDIO,
            description="Speak the displayed phrase",
            actions=[
                Action(
                    action_type=ActionType.SPEAK_PHRASE,
                    value="I am a human",  # Will be locale-specific
                    duration_seconds=3.0
                )
            ],
            estimated_duration_seconds=4.0,
            difficulty="easy",
            accessibility_level="limited_mobility",
            entropy_bits=4.6,  # Multiple phrases
            supports_locales=[l for l in Locale],
            requires_motion=False,
            requires_vision=True,
            requires_audio=True
        )
        
        # ============================================================
        # TEMPLATE 13: Open Mouth Wide
        # ============================================================
        self.templates["T13_OPEN_MOUTH"] = ChallengeTemplate(
            template_id="T13_OPEN_MOUTH",
            name="Open Mouth Wide",
            challenge_type=ChallengeType.FACIAL,
            description="Open your mouth wide",
            actions=[
                Action(
                    action_type=ActionType.OPEN_MOUTH,
                    intensity="strong",
                    duration_seconds=2.0
                )
            ],
            estimated_duration_seconds=3.0,
            difficulty="easy",
            accessibility_level="universal",
            entropy_bits=1.6,
            supports_locales=[l for l in Locale],
            requires_motion=False,
            requires_vision=True,
            requires_audio=False
        )
        
        # ============================================================
        # TEMPLATE 14: Close Eyes and Nod
        # ============================================================
        self.templates["T14_CLOSE_NOD"] = ChallengeTemplate(
            template_id="T14_CLOSE_NOD",
            name="Close Eyes and Nod",
            challenge_type=ChallengeType.COMPOSITE,
            description="Close your eyes, then nod",
            actions=[
                Action(
                    action_type=ActionType.CLOSE_EYES,
                    duration_seconds=1.5
                ),
                Action(
                    action_type=ActionType.NOD,
                    count=1,
                    timing="normal"
                )
            ],
            estimated_duration_seconds=4.0,
            difficulty="medium",
            accessibility_level="universal",
            entropy_bits=2.0,
            supports_locales=[l for l in Locale],
            requires_motion=True,
            requires_vision=True,
            requires_audio=False
        )
        
        # ============================================================
        # TEMPLATE 15: Shake Head
        # ============================================================
        self.templates["T15_SHAKE_HEAD"] = ChallengeTemplate(
            template_id="T15_SHAKE_HEAD",
            name="Shake Head",
            challenge_type=ChallengeType.MOTION,
            description="Shake your head (side to side)",
            actions=[
                Action(
                    action_type=ActionType.SHAKE_HEAD,
                    count=2,
                    timing="normal"
                )
            ],
            estimated_duration_seconds=3.0,
            difficulty="easy",
            accessibility_level="universal",
            entropy_bits=1.6,
            supports_locales=[l for l in Locale],
            requires_motion=True,
            requires_vision=True,
            requires_audio=False
        )
    
    def get_template(self, template_id: str) -> Optional[ChallengeTemplate]:
        """Get template by ID"""
        return self.templates.get(template_id)
    
    def get_all_templates(self) -> List[ChallengeTemplate]:
        """Get all templates"""
        return list(self.templates.values())
    
    def get_templates_by_accessibility(
        self,
        requires_motion: Optional[bool] = None,
        requires_vision: Optional[bool] = None,
        requires_audio: Optional[bool] = None
    ) -> List[ChallengeTemplate]:
        """
        Get templates matching accessibility criteria
        
        Args:
            requires_motion: Filter by motion requirement
            requires_vision: Filter by vision requirement
            requires_audio: Filter by audio requirement
        
        Returns:
            List of matching templates
        """
        
        templates = self.get_all_templates()
        
        if requires_motion is not None:
            templates = [t for t in templates if t.requires_motion == requires_motion]
        
        if requires_vision is not None:
            templates = [t for t in templates if t.requires_vision == requires_vision]
        
        if requires_audio is not None:
            templates = [t for t in templates if t.requires_audio == requires_audio]
        
        return templates
    
    def get_templates_by_difficulty(self, difficulty: str) -> List[ChallengeTemplate]:
        """Get templates by difficulty level"""
        return [t for t in self.get_all_templates() if t.difficulty == difficulty]
    
    def get_count(self) -> int:
        """Get total template count"""
        return len(self.templates)
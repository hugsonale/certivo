"""
Challenge Generator
Generate personalized challenges based on user constraints
"""

import secrets
import random
from typing import Dict, Any, List, Optional
from datetime import datetime

from challenge_templates import (
    ChallengeTemplateLibrary,
    ChallengeTemplate,
    Action,
    ActionType,
    Locale
)
from locale_prompts import LocalePrompts


class AccessibilityProfile:
    """User accessibility profile"""
    
    def __init__(
        self,
        limited_mobility: bool = False,
        vision_impaired: bool = False,
        hearing_impaired: bool = False,
        preferred_locale: str = Locale.EN_US.value
    ):
        self.limited_mobility = limited_mobility
        self.vision_impaired = vision_impaired
        self.hearing_impaired = hearing_impaired
        self.preferred_locale = preferred_locale
    
    def can_perform_motion(self) -> bool:
        """Can user perform head/body movements"""
        return not self.limited_mobility
    
    def can_see_visual(self) -> bool:
        """Can user see visual prompts"""
        return not self.vision_impaired
    
    def can_hear_audio(self) -> bool:
        """Can user hear audio prompts"""
        return not self.hearing_impaired


class ChallengeGenerator:
    """
    Generate challenges with accessibility awareness
    
    Features:
    - Accessibility-aware template selection
    - Locale-aware prompts
    - Random value generation (digits, phrases)
    - Template rotation
    """
    
    def __init__(self):
        self.library = ChallengeTemplateLibrary()
        self.locale_prompts = LocalePrompts()
    
    def generate_challenge(
        self,
        accessibility_profile: Optional[AccessibilityProfile] = None,
        difficulty: Optional[str] = None,
        template_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generate challenge
        
        Args:
            accessibility_profile: User accessibility constraints
            difficulty: Desired difficulty (easy, medium, hard)
            template_id: Specific template to use (optional)
        
        Returns:
            Challenge data with actions and prompts
        """
        
        # Default accessibility profile
        if not accessibility_profile:
            accessibility_profile = AccessibilityProfile()
        
        # Select template
        if template_id:
            template = self.library.get_template(template_id)
            if not template:
                raise ValueError(f"Template not found: {template_id}")
        else:
            template = self._select_template(accessibility_profile, difficulty)
        
        # Generate challenge from template
        challenge = self._instantiate_template(template, accessibility_profile)
        
        return challenge
    
    def _select_template(
        self,
        profile: AccessibilityProfile,
        difficulty: Optional[str] = None
    ) -> ChallengeTemplate:
        """
        Select appropriate template based on accessibility
        
        Args:
            profile: User accessibility profile
            difficulty: Desired difficulty
        
        Returns:
            Selected template
        """
        
        # Filter by accessibility
        candidates = self.library.get_templates_by_accessibility(
            requires_motion=profile.can_perform_motion() or None,
            requires_vision=profile.can_see_visual() or None,
            requires_audio=profile.can_hear_audio() or None
        )
        
        # Filter by difficulty if specified
        if difficulty:
            candidates = [t for t in candidates if t.difficulty == difficulty]
        
        # Filter by locale support
        candidates = [
            t for t in candidates
            if Locale(profile.preferred_locale) in t.supports_locales
        ]
        
        if not candidates:
            # Fallback to simplest accessible template
            candidates = self.library.get_templates_by_difficulty("easy")
        
        # Select random template (CSPRNG)
        template = secrets.choice(candidates)
        
        return template
    
    def _instantiate_template(
        self,
        template: ChallengeTemplate,
        profile: AccessibilityProfile
    ) -> Dict[str, Any]:
        """
        Instantiate template with random values
        
        Args:
            template: Challenge template
            profile: Accessibility profile
        
        Returns:
            Challenge instance
        """
        
        actions = []
        
        for action in template.actions:
            # Clone action
            action_instance = Action(
                action_type=action.action_type,
                direction=action.direction,
                intensity=action.intensity,
                timing=action.timing,
                duration_seconds=action.duration_seconds,
                count=action.count,
                value=action.value
            )
            
            # Randomize where needed
            if action.action_type == ActionType.READ_DIGITS:
                # Generate random 3-digit number
                action_instance.value = str(secrets.randbelow(1000)).zfill(3)
            
            elif action.action_type == ActionType.SPEAK_PHRASE:
                # Select random phrase (locale-aware)
                phrases = self._get_phrases_for_locale(profile.preferred_locale)
                action_instance.value = secrets.choice(phrases)
            
            elif action.action_type == ActionType.COUNT_ALOUD:
                # Randomize count (2-5)
                action_instance.count = secrets.choice([2, 3, 4, 5])
            
            elif action.action_type == ActionType.BLINK:
                # Randomize blink count (1-4)
                if action.count is None or action.count == 0:
                    action_instance.count = secrets.choice([1, 2, 3, 4])
            
            elif action.action_type in [
                ActionType.TURN_HEAD_LEFT,
                ActionType.TURN_HEAD_RIGHT,
                ActionType.TURN_HEAD_UP,
                ActionType.TURN_HEAD_DOWN
            ]:
                # Randomize direction if not specified
                if not action.direction:
                    directions = ["left", "right", "up", "down"]
                    action_instance.direction = secrets.choice(directions)
            
            actions.append(action_instance)
        
        # Generate localized prompts
        locale = profile.preferred_locale
        
        action_prompts = []
        for action in actions:
            kwargs = {}
            if action.value:
                kwargs["value"] = action.value
            if action.count:
                kwargs["count"] = action.count
            
            prompt = self.locale_prompts.get_prompt(
                action.action_type.value,
                locale,
                **kwargs
            )
            action_prompts.append(prompt)
        
        # Composite prompt
        composite_prompt = self.locale_prompts.format_composite_prompt(
            [a.to_dict() for a in actions],
            locale
        )
        
        # Build challenge response
        challenge = {
            "challenge_id": self._generate_challenge_id(),
            "template_id": template.template_id,
            "template_name": template.name,
            "challenge_type": template.challenge_type.value,
            "difficulty": template.difficulty,
            "estimated_duration_seconds": template.estimated_duration_seconds,
            "entropy_bits": template.entropy_bits,
            "locale": locale,
            "prompt": composite_prompt,
            "actions": [a.to_dict() for a in actions],
            "action_prompts": action_prompts,
            "accessibility": {
                "requires_motion": template.requires_motion,
                "requires_vision": template.requires_vision,
                "requires_audio": template.requires_audio
            },
            "generated_at": datetime.utcnow().isoformat()
        }
        
        return challenge
    
    def _generate_challenge_id(self) -> str:
        """Generate unique challenge ID"""
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        random_suffix = secrets.token_hex(4)
        return f"CH-{timestamp}-{random_suffix}"
    
    def _get_phrases_for_locale(self, locale: str) -> List[str]:
        """Get random phrases for locale"""
        
        phrases_by_locale = {
            Locale.EN_US.value: [
                "I am a human",
                "This is my voice",
                "Hello there",
                "Verification complete",
                "Access granted"
            ],
            Locale.ES_ES.value: [
                "Soy un humano",
                "Esta es mi voz",
                "Hola",
                "Verificación completa",
                "Acceso concedido"
            ],
            Locale.FR_FR.value: [
                "Je suis un humain",
                "C'est ma voix",
                "Bonjour",
                "Vérification terminée",
                "Accès accordé"
            ],
            Locale.DE_DE.value: [
                "Ich bin ein Mensch",
                "Das ist meine Stimme",
                "Hallo",
                "Überprüfung abgeschlossen",
                "Zugang gewährt"
            ],
            # Add more locales...
        }
        
        return phrases_by_locale.get(locale, phrases_by_locale[Locale.EN_US.value])
    
    def get_template_count(self) -> int:
        """Get total number of templates"""
        return self.library.get_count()
    
    def get_accessible_template_count(
        self,
        profile: AccessibilityProfile
    ) -> int:
        """Get number of accessible templates for profile"""
        
        templates = self.library.get_templates_by_accessibility(
            requires_motion=profile.can_perform_motion() or None,
            requires_vision=profile.can_see_visual() or None,
            requires_audio=profile.can_hear_audio() or None
        )
        
        return len(templates)
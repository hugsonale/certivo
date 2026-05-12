"""
Locale-Aware Challenge Prompts
Multi-language support for challenge instructions
"""

from typing import Dict, Any
from enum import Enum


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


class LocalePrompts:
    """
    Locale-aware prompt translations
    
    Supports 14 languages with culturally appropriate phrasing
    """
    
    # Action prompts by locale
    PROMPTS: Dict[str, Dict[str, str]] = {
        # ============================================================
        # ENGLISH (US)
        # ============================================================
        Locale.EN_US.value: {
            "turn_head_left": "Turn your head to the left",
            "turn_head_right": "Turn your head to the right",
            "turn_head_up": "Look up",
            "turn_head_down": "Look down",
            "nod": "Nod your head",
            "shake_head": "Shake your head",
            "tilt_left": "Tilt your head to the left",
            "tilt_right": "Tilt your head to the right",
            "blink": "Blink your eyes",
            "smile": "Smile",
            "raise_eyebrows": "Raise your eyebrows",
            "close_eyes": "Close your eyes",
            "open_mouth": "Open your mouth",
            "look_left": "Look to the left",
            "look_right": "Look to the right",
            "look_up": "Look up",
            "look_down": "Look down",
            "read_digits": "Read these digits aloud: {value}",
            "speak_phrase": "Say: {value}",
            "count_aloud": "Count aloud from 1 to {count}",
            "then": "then",
            "once": "once",
            "twice": "twice",
            "times": "times",
        },
        
        # ============================================================
        # ENGLISH (UK)
        # ============================================================
        Locale.EN_GB.value: {
            "turn_head_left": "Turn your head to the left",
            "turn_head_right": "Turn your head to the right",
            "turn_head_up": "Look up",
            "turn_head_down": "Look down",
            "nod": "Nod your head",
            "shake_head": "Shake your head",
            "tilt_left": "Tilt your head to the left",
            "tilt_right": "Tilt your head to the right",
            "blink": "Blink your eyes",
            "smile": "Smile",
            "raise_eyebrows": "Raise your eyebrows",
            "close_eyes": "Close your eyes",
            "open_mouth": "Open your mouth",
            "look_left": "Look to the left",
            "look_right": "Look to the right",
            "look_up": "Look up",
            "look_down": "Look down",
            "read_digits": "Read these digits aloud: {value}",
            "speak_phrase": "Say: {value}",
            "count_aloud": "Count aloud from 1 to {count}",
            "then": "then",
            "once": "once",
            "twice": "twice",
            "times": "times",
        },
        
        # ============================================================
        # SPANISH (SPAIN)
        # ============================================================
        Locale.ES_ES.value: {
            "turn_head_left": "Gira tu cabeza a la izquierda",
            "turn_head_right": "Gira tu cabeza a la derecha",
            "turn_head_up": "Mira hacia arriba",
            "turn_head_down": "Mira hacia abajo",
            "nod": "Asiente con la cabeza",
            "shake_head": "Niega con la cabeza",
            "tilt_left": "Inclina tu cabeza a la izquierda",
            "tilt_right": "Inclina tu cabeza a la derecha",
            "blink": "Parpadea",
            "smile": "Sonríe",
            "raise_eyebrows": "Levanta las cejas",
            "close_eyes": "Cierra los ojos",
            "open_mouth": "Abre la boca",
            "look_left": "Mira a la izquierda",
            "look_right": "Mira a la derecha",
            "look_up": "Mira hacia arriba",
            "look_down": "Mira hacia abajo",
            "read_digits": "Lee estos dígitos en voz alta: {value}",
            "speak_phrase": "Di: {value}",
            "count_aloud": "Cuenta en voz alta del 1 al {count}",
            "then": "luego",
            "once": "una vez",
            "twice": "dos veces",
            "times": "veces",
        },
        
        # ============================================================
        # SPANISH (MEXICO)
        # ============================================================
        Locale.ES_MX.value: {
            "turn_head_left": "Voltea tu cabeza a la izquierda",
            "turn_head_right": "Voltea tu cabeza a la derecha",
            "turn_head_up": "Mira hacia arriba",
            "turn_head_down": "Mira hacia abajo",
            "nod": "Asiente con la cabeza",
            "shake_head": "Niega con la cabeza",
            "tilt_left": "Inclina tu cabeza a la izquierda",
            "tilt_right": "Inclina tu cabeza a la derecha",
            "blink": "Parpadea",
            "smile": "Sonríe",
            "raise_eyebrows": "Levanta las cejas",
            "close_eyes": "Cierra los ojos",
            "open_mouth": "Abre la boca",
            "look_left": "Mira a la izquierda",
            "look_right": "Mira a la derecha",
            "look_up": "Mira hacia arriba",
            "look_down": "Mira hacia abajo",
            "read_digits": "Lee estos números en voz alta: {value}",
            "speak_phrase": "Di: {value}",
            "count_aloud": "Cuenta en voz alta del 1 al {count}",
            "then": "luego",
            "once": "una vez",
            "twice": "dos veces",
            "times": "veces",
        },
        
        # ============================================================
        # FRENCH
        # ============================================================
        Locale.FR_FR.value: {
            "turn_head_left": "Tournez la tête vers la gauche",
            "turn_head_right": "Tournez la tête vers la droite",
            "turn_head_up": "Regardez vers le haut",
            "turn_head_down": "Regardez vers le bas",
            "nod": "Hochez la tête",
            "shake_head": "Secouez la tête",
            "tilt_left": "Inclinez la tête vers la gauche",
            "tilt_right": "Inclinez la tête vers la droite",
            "blink": "Clignez des yeux",
            "smile": "Souriez",
            "raise_eyebrows": "Levez les sourcils",
            "close_eyes": "Fermez les yeux",
            "open_mouth": "Ouvrez la bouche",
            "look_left": "Regardez à gauche",
            "look_right": "Regardez à droite",
            "look_up": "Regardez en haut",
            "look_down": "Regardez en bas",
            "read_digits": "Lisez ces chiffres à voix haute : {value}",
            "speak_phrase": "Dites : {value}",
            "count_aloud": "Comptez à voix haute de 1 à {count}",
            "then": "puis",
            "once": "une fois",
            "twice": "deux fois",
            "times": "fois",
        },
        
        # ============================================================
        # GERMAN
        # ============================================================
        Locale.DE_DE.value: {
            "turn_head_left": "Drehen Sie den Kopf nach links",
            "turn_head_right": "Drehen Sie den Kopf nach rechts",
            "turn_head_up": "Schauen Sie nach oben",
            "turn_head_down": "Schauen Sie nach unten",
            "nod": "Nicken Sie mit dem Kopf",
            "shake_head": "Schütteln Sie den Kopf",
            "tilt_left": "Neigen Sie den Kopf nach links",
            "tilt_right": "Neigen Sie den Kopf nach rechts",
            "blink": "Blinzeln Sie",
            "smile": "Lächeln Sie",
            "raise_eyebrows": "Heben Sie die Augenbrauen",
            "close_eyes": "Schließen Sie die Augen",
            "open_mouth": "Öffnen Sie den Mund",
            "look_left": "Schauen Sie nach links",
            "look_right": "Schauen Sie nach rechts",
            "look_up": "Schauen Sie nach oben",
            "look_down": "Schauen Sie nach unten",
            "read_digits": "Lesen Sie diese Ziffern laut vor: {value}",
            "speak_phrase": "Sagen Sie: {value}",
            "count_aloud": "Zählen Sie laut von 1 bis {count}",
            "then": "dann",
            "once": "einmal",
            "twice": "zweimal",
            "times": "mal",
        },
        
        # ============================================================
        # ITALIAN
        # ============================================================
        Locale.IT_IT.value: {
            "turn_head_left": "Gira la testa a sinistra",
            "turn_head_right": "Gira la testa a destra",
            "turn_head_up": "Guarda in alto",
            "turn_head_down": "Guarda in basso",
            "nod": "Annuisci con la testa",
            "shake_head": "Scuoti la testa",
            "tilt_left": "Inclina la testa a sinistra",
            "tilt_right": "Inclina la testa a destra",
            "blink": "Sbatti le palpebre",
            "smile": "Sorridi",
            "raise_eyebrows": "Alza le sopracciglia",
            "close_eyes": "Chiudi gli occhi",
            "open_mouth": "Apri la bocca",
            "look_left": "Guarda a sinistra",
            "look_right": "Guarda a destra",
            "look_up": "Guarda in alto",
            "look_down": "Guarda in basso",
            "read_digits": "Leggi queste cifre ad alta voce: {value}",
            "speak_phrase": "Di: {value}",
            "count_aloud": "Conta ad alta voce da 1 a {count}",
            "then": "poi",
            "once": "una volta",
            "twice": "due volte",
            "times": "volte",
        },
        
        # ============================================================
        # PORTUGUESE (BRAZIL)
        # ============================================================
        Locale.PT_BR.value: {
            "turn_head_left": "Vire a cabeça para a esquerda",
            "turn_head_right": "Vire a cabeça para a direita",
            "turn_head_up": "Olhe para cima",
            "turn_head_down": "Olhe para baixo",
            "nod": "Acene com a cabeça",
            "shake_head": "Balance a cabeça negativamente",
            "tilt_left": "Incline a cabeça para a esquerda",
            "tilt_right": "Incline a cabeça para a direita",
            "blink": "Pisque os olhos",
            "smile": "Sorria",
            "raise_eyebrows": "Levante as sobrancelhas",
            "close_eyes": "Feche os olhos",
            "open_mouth": "Abra a boca",
            "look_left": "Olhe para a esquerda",
            "look_right": "Olhe para a direita",
            "look_up": "Olhe para cima",
            "look_down": "Olhe para baixo",
            "read_digits": "Leia estes dígitos em voz alta: {value}",
            "speak_phrase": "Diga: {value}",
            "count_aloud": "Conte em voz alta de 1 até {count}",
            "then": "depois",
            "once": "uma vez",
            "twice": "duas vezes",
            "times": "vezes",
        },
        
        # ============================================================
        # CHINESE (SIMPLIFIED)
        # ============================================================
        Locale.ZH_CN.value: {
            "turn_head_left": "向左转头",
            "turn_head_right": "向右转头",
            "turn_head_up": "向上看",
            "turn_head_down": "向下看",
            "nod": "点头",
            "shake_head": "摇头",
            "tilt_left": "头向左倾斜",
            "tilt_right": "头向右倾斜",
            "blink": "眨眼",
            "smile": "微笑",
            "raise_eyebrows": "抬起眉毛",
            "close_eyes": "闭上眼睛",
            "open_mouth": "张开嘴巴",
            "look_left": "向左看",
            "look_right": "向右看",
            "look_up": "向上看",
            "look_down": "向下看",
            "read_digits": "大声读出这些数字：{value}",
            "speak_phrase": "说：{value}",
            "count_aloud": "大声数数从1到{count}",
            "then": "然后",
            "once": "一次",
            "twice": "两次",
            "times": "次",
        },
        
        # ============================================================
        # JAPANESE
        # ============================================================
        Locale.JA_JP.value: {
            "turn_head_left": "頭を左に向けてください",
            "turn_head_right": "頭を右に向けてください",
            "turn_head_up": "上を向いてください",
            "turn_head_down": "下を向いてください",
            "nod": "うなずいてください",
            "shake_head": "首を横に振ってください",
            "tilt_left": "頭を左に傾けてください",
            "tilt_right": "頭を右に傾けてください",
            "blink": "まばたきをしてください",
            "smile": "笑顔を見せてください",
            "raise_eyebrows": "眉を上げてください",
            "close_eyes": "目を閉じてください",
            "open_mouth": "口を開けてください",
            "look_left": "左を見てください",
            "look_right": "右を見てください",
            "look_up": "上を見てください",
            "look_down": "下を見てください",
            "read_digits": "この数字を声に出して読んでください：{value}",
            "speak_phrase": "次のように言ってください：{value}",
            "count_aloud": "1から{count}まで声に出して数えてください",
            "then": "次に",
            "once": "1回",
            "twice": "2回",
            "times": "回",
        },
        
        # ============================================================
        # KOREAN
        # ============================================================
        Locale.KO_KR.value: {
            "turn_head_left": "머리를 왼쪽으로 돌리세요",
            "turn_head_right": "머리를 오른쪽으로 돌리세요",
            "turn_head_up": "위를 보세요",
            "turn_head_down": "아래를 보세요",
            "nod": "고개를 끄덕이세요",
            "shake_head": "고개를 저으세요",
            "tilt_left": "머리를 왼쪽으로 기울이세요",
            "tilt_right": "머리를 오른쪽으로 기울이세요",
            "blink": "눈을 깜빡이세요",
            "smile": "미소 지으세요",
            "raise_eyebrows": "눈썹을 올리세요",
            "close_eyes": "눈을 감으세요",
            "open_mouth": "입을 벌리세요",
            "look_left": "왼쪽을 보세요",
            "look_right": "오른쪽을 보세요",
            "look_up": "위를 보세요",
            "look_down": "아래를 보세요",
            "read_digits": "이 숫자를 소리내어 읽으세요: {value}",
            "speak_phrase": "다음과 같이 말하세요: {value}",
            "count_aloud": "1부터 {count}까지 소리내어 세세요",
            "then": "그런 다음",
            "once": "한 번",
            "twice": "두 번",
            "times": "번",
        },
        
        # ============================================================
        # ARABIC (SAUDI ARABIA)
        # ============================================================
        Locale.AR_SA.value: {
            "turn_head_left": "أدر رأسك إلى اليسار",
            "turn_head_right": "أدر رأسك إلى اليمين",
            "turn_head_up": "انظر إلى الأعلى",
            "turn_head_down": "انظر إلى الأسفل",
            "nod": "أومئ برأسك",
            "shake_head": "هز رأسك",
            "tilt_left": "أمل رأسك إلى اليسار",
            "tilt_right": "أمل رأسك إلى اليمين",
            "blink": "أرمش بعينيك",
            "smile": "ابتسم",
            "raise_eyebrows": "ارفع حاجبيك",
            "close_eyes": "أغمض عينيك",
            "open_mouth": "افتح فمك",
            "look_left": "انظر إلى اليسار",
            "look_right": "انظر إلى اليمين",
            "look_up": "انظر إلى الأعلى",
            "look_down": "انظر إلى الأسفل",
            "read_digits": "اقرأ هذه الأرقام بصوت عالٍ: {value}",
            "speak_phrase": "قل: {value}",
            "count_aloud": "عد بصوت عالٍ من 1 إلى {count}",
            "then": "ثم",
            "once": "مرة واحدة",
            "twice": "مرتين",
            "times": "مرات",
        },
        
        # ============================================================
        # HINDI (INDIA)
        # ============================================================
        Locale.HI_IN.value: {
            "turn_head_left": "अपना सिर बाईं ओर घुमाएं",
            "turn_head_right": "अपना सिर दाईं ओर घुमाएं",
            "turn_head_up": "ऊपर देखें",
            "turn_head_down": "नीचे देखें",
            "nod": "सिर हिलाएं",
            "shake_head": "सिर नकारात्मक रूप से हिलाएं",
            "tilt_left": "अपना सिर बाईं ओर झुकाएं",
            "tilt_right": "अपना सिर दाईं ओर झुकाएं",
            "blink": "पलक झपकाएं",
            "smile": "मुस्कुराएं",
            "raise_eyebrows": "भौहें उठाएं",
            "close_eyes": "आंखें बंद करें",
            "open_mouth": "मुंह खोलें",
            "look_left": "बाईं ओर देखें",
            "look_right": "दाईं ओर देखें",
            "look_up": "ऊपर देखें",
            "look_down": "नीचे देखें",
            "read_digits": "इन अंकों को जोर से पढ़ें: {value}",
            "speak_phrase": "कहें: {value}",
            "count_aloud": "1 से {count} तक जोर से गिनें",
            "then": "फिर",
            "once": "एक बार",
            "twice": "दो बार",
            "times": "बार",
        },
        
        # ============================================================
        # RUSSIAN
        # ============================================================
        Locale.RU_RU.value: {
            "turn_head_left": "Поверните голову влево",
            "turn_head_right": "Поверните голову вправо",
            "turn_head_up": "Посмотрите вверх",
            "turn_head_down": "Посмотрите вниз",
            "nod": "Кивните головой",
            "shake_head": "Покачайте головой",
            "tilt_left": "Наклоните голову влево",
            "tilt_right": "Наклоните голову вправо",
            "blink": "Моргните",
            "smile": "Улыбнитесь",
            "raise_eyebrows": "Поднимите брови",
            "close_eyes": "Закройте глаза",
            "open_mouth": "Откройте рот",
            "look_left": "Посмотрите влево",
            "look_right": "Посмотрите вправо",
            "look_up": "Посмотрите вверх",
            "look_down": "Посмотрите вниз",
            "read_digits": "Прочитайте эти цифры вслух: {value}",
            "speak_phrase": "Скажите: {value}",
            "count_aloud": "Считайте вслух от 1 до {count}",
            "then": "затем",
            "once": "один раз",
            "twice": "два раза",
            "times": "раз",
        },
    }
    
    @classmethod
    def get_prompt(
        cls,
        action_type: str,
        locale: str = Locale.EN_US.value,
        **kwargs
    ) -> str:
        """
        Get localized prompt for action
        
        Args:
            action_type: Action type (e.g., "turn_head_left")
            locale: Locale code (e.g., "en-US")
            **kwargs: Template variables (value, count, etc.)
        
        Returns:
            Localized prompt string
        """
        
        # Get locale prompts
        locale_prompts = cls.PROMPTS.get(locale, cls.PROMPTS[Locale.EN_US.value])
        
        # Get prompt template
        prompt_template = locale_prompts.get(action_type, action_type)
        
        # Format with variables
        try:
            prompt = prompt_template.format(**kwargs)
        except KeyError:
            prompt = prompt_template
        
        return prompt
    
    @classmethod
    def format_composite_prompt(
        cls,
        actions: list,
        locale: str = Locale.EN_US.value
    ) -> str:
        """
        Format composite challenge prompt
        
        Args:
            actions: List of actions with types and parameters
            locale: Locale code
        
        Returns:
            Composite prompt string (e.g., "Turn left, then blink twice")
        """
        
        locale_prompts = cls.PROMPTS.get(locale, cls.PROMPTS[Locale.EN_US.value])
        then_word = locale_prompts.get("then", "then")
        
        prompts = []
        
        for action in actions:
            action_type = action.get("action")
            
            # Build kwargs
            kwargs = {}
            if action.get("value"):
                kwargs["value"] = action["value"]
            if action.get("count"):
                # Format count word
                count = action["count"]
                if count == 1:
                    count_word = locale_prompts.get("once", "once")
                elif count == 2:
                    count_word = locale_prompts.get("twice", "twice")
                else:
                    count_word = f"{count} {locale_prompts.get('times', 'times')}"
                kwargs["count"] = action["count"]
            
            prompt = cls.get_prompt(action_type, locale, **kwargs)
            prompts.append(prompt)
        
        # Join with "then"
        if len(prompts) == 1:
            return prompts[0]
        else:
            return f", {then_word} ".join(prompts)
    
    @classmethod
    def get_supported_locales(cls) -> list:
        """Get list of supported locales"""
        return list(cls.PROMPTS.keys())
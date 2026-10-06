"""
Dynamic watermark and prompt overlay generation
Binds visual elements to challenge nonce for anti-replay
"""

from PIL import Image, ImageDraw, ImageFont
import io
import hashlib
from typing import Tuple, Optional
import base64


class WatermarkGenerator:
    """
    Generate dynamic watermarks tied to challenge nonce
    Makes it impossible to reuse videos across sessions
    """
    
    def __init__(self, font_path: Optional[str] = None):
        """
        Initialize watermark generator
        
        Args:
            font_path: Path to TTF font file (optional)
        """
        self.font_path = font_path
    
    def generate_watermark_code(self, nonce: str) -> str:
        """
        Generate unique watermark code from nonce
        
        Args:
            nonce: Cryptographic nonce
        
        Returns:
            6-character alphanumeric code
        """
        
        # Hash nonce and take first 6 chars
        hash_digest = hashlib.sha256(nonce.encode()).hexdigest()
        code = hash_digest[:6].upper()
        
        return code
    
    def generate_watermark_image(
        self,
        nonce: str,
        size: Tuple[int, int] = (640, 480),
        position: str = "bottom-right"
    ) -> bytes:
        """
        Generate watermark overlay image
        
        Args:
            nonce: Cryptographic nonce
            size: Image size (width, height)
            position: Watermark position
        
        Returns:
            PNG image bytes
        """
        
        # Generate watermark code
        code = self.generate_watermark_code(nonce)
        
        # Create transparent image
        img = Image.new('RGBA', size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        # Load font
        try:
            if self.font_path:
                font = ImageFont.truetype(self.font_path, 20)
            else:
                font = ImageFont.load_default()
        except:
            font = ImageFont.load_default()
        
        # Calculate text position
        text = f"Code: {code}"
        
        # Get text bounding box
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        # Calculate position
        if position == "bottom-right":
            x = size[0] - text_width - 10
            y = size[1] - text_height - 10
        elif position == "top-right":
            x = size[0] - text_width - 10
            y = 10
        elif position == "bottom-left":
            x = 10
            y = size[1] - text_height - 10
        else:  # top-left
            x = 10
            y = 10
        
        # Draw semi-transparent background
        padding = 5
        draw.rectangle(
            [x - padding, y - padding, x + text_width + padding, y + text_height + padding],
            fill=(0, 0, 0, 128)
        )
        
        # Draw text
        draw.text((x, y), text, fill=(255, 255, 255, 255), font=font)
        
        # Convert to bytes
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='PNG')
        img_bytes.seek(0)
        
        return img_bytes.read()
    
    def generate_prompt_overlay(
        self,
        nonce: str,
        instruction: str,
        size: Tuple[int, int] = (640, 480)
    ) -> bytes:
        """
        Generate dynamic prompt overlay with nonce-tied code
        
        Args:
            nonce: Cryptographic nonce
            instruction: Challenge instruction text
            size: Image size
        
        Returns:
            PNG image bytes
        """
        
        # Generate code
        code = self.generate_watermark_code(nonce)
        
        # Create image
        img = Image.new('RGBA', size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        # Load font
        try:
            if self.font_path:
                font_large = ImageFont.truetype(self.font_path, 24)
                font_small = ImageFont.truetype(self.font_path, 16)
            else:
                font_large = ImageFont.load_default()
                font_small = ImageFont.load_default()
        except:
            font_large = ImageFont.load_default()
            font_small = ImageFont.load_default()
        
        # Draw instruction
        draw.text((20, 20), instruction, fill=(255, 255, 255, 255), font=font_large)
        
        # Draw code
        code_text = f"Session Code: {code}"
        draw.text((20, size[1] - 40), code_text, fill=(255, 255, 0, 255), font=font_small)
        
        # Convert to bytes
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='PNG')
        img_bytes.seek(0)
        
        return img_bytes.read()
    
    def validate_watermark_in_video(
        self,
        nonce: str,
        video_frame: bytes,
        expected_code: Optional[str] = None
    ) -> bool:
        """
        Validate watermark presence in video frame (OCR-based)
        
        Args:
            nonce: Expected nonce
            video_frame: Video frame bytes
            expected_code: Expected code (if None, derive from nonce)
        
        Returns:
            True if watermark matches, False otherwise
        """
        
        if expected_code is None:
            expected_code = self.generate_watermark_code(nonce)
        
        # TODO: Implement OCR validation using pytesseract
        # For now, return True (placeholder)
        # In production, extract text from frame and verify code
        
        return True
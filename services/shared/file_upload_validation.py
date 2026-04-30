"""
File Upload Validation and Security
Prevents upload abuse and malicious file attacks
"""

import magic
import hashlib
import os
from typing import Optional, Tuple, Dict, Any
from fastapi import UploadFile
import tempfile
import subprocess


class FileUploadValidator:
    """
    Validate uploaded files
    
    Checks:
    1. File size limits
    2. MIME type validation
    3. Content type verification (magic bytes)
    4. Malicious content scanning
    5. Polyglot file detection
    """
    
    # Allowed MIME types
    ALLOWED_VIDEO_MIMES = {
        "video/webm",
        "video/mp4",
        "video/x-matroska"
    }
    
    # Magic bytes for video formats
    VIDEO_MAGIC_BYTES = {
        b"\x1a\x45\xdf\xa3": "video/webm",  # WebM/Matroska
        b"\x00\x00\x00\x18ftypmp4": "video/mp4",  # MP4
        b"\x00\x00\x00\x20ftypmp4": "video/mp4",
    }
    
    # Size limits
    MAX_VIDEO_SIZE = 50 * 1024 * 1024  # 50MB
    MIN_VIDEO_SIZE = 1024  # 1KB
    
    def __init__(self):
        self.mime_detector = magic.Magic(mime=True)
    
    async def validate_video_upload(
        self,
        file: UploadFile,
        expected_duration_range: Optional[Tuple[float, float]] = None
    ) -> Dict[str, Any]:
        """
        Validate video file upload
        
        Args:
            file: Uploaded file
            expected_duration_range: (min_seconds, max_seconds) or None
        
        Returns:
            Validation result
        
        Raises:
            ValueError: If validation fails
        """
        
        # Read file content
        content = await file.read()
        await file.seek(0)  # Reset for later use
        
        # ================================================================
        # CHECK 1: File Size
        # ================================================================
        
        file_size = len(content)
        
        if file_size > self.MAX_VIDEO_SIZE:
            raise ValueError(f"File too large: {file_size} bytes (max: {self.MAX_VIDEO_SIZE})")
        
        if file_size < self.MIN_VIDEO_SIZE:
            raise ValueError(f"File too small: {file_size} bytes (min: {self.MIN_VIDEO_SIZE})")
        
        # ================================================================
        # CHECK 2: Declared MIME Type
        # ================================================================
        
        declared_mime = file.content_type
        
        if declared_mime not in self.ALLOWED_VIDEO_MIMES:
            raise ValueError(f"Invalid MIME type: {declared_mime}")
        
        # ================================================================
        # CHECK 3: Magic Bytes (Content Sniffing)
        # ================================================================
        
        detected_mime = self._detect_mime_from_content(content)
        
        if detected_mime not in self.ALLOWED_VIDEO_MIMES:
            raise ValueError(f"Content type mismatch: detected {detected_mime}, expected video")
        
        # MIME type consistency check
        if declared_mime != detected_mime:
            raise ValueError(
                f"MIME type mismatch: declared {declared_mime}, detected {detected_mime}"
            )
        
        # ================================================================
        # CHECK 4: Polyglot File Detection
        # ================================================================
        
        if self._is_polyglot_file(content):
            raise ValueError("Polyglot file detected (potential attack)")
        
        # ================================================================
        # CHECK 5: Malformed File Detection
        # ================================================================
        
        # Save to temp file for deeper inspection
        with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        
        try:
            # Verify file can be opened by ffprobe
            is_valid, metadata = self._verify_video_integrity(tmp_path)
            
            if not is_valid:
                raise ValueError("Malformed video file")
            
            # Check duration if range specified
            if expected_duration_range:
                duration = metadata.get("duration", 0)
                min_dur, max_dur = expected_duration_range
                
                if not (min_dur <= duration <= max_dur):
                    raise ValueError(
                        f"Video duration {duration}s outside range [{min_dur}, {max_dur}]"
                    )
            
            # ============================================================
            # CHECK 6: Hash and Store
            # ============================================================
            
            file_hash = hashlib.sha256(content).hexdigest()
            
            return {
                "valid": True,
                "file_size": file_size,
                "mime_type": detected_mime,
                "file_hash": file_hash,
                "duration": metadata.get("duration", 0),
                "width": metadata.get("width", 0),
                "height": metadata.get("height", 0),
                "fps": metadata.get("fps", 0)
            }
            
        finally:
            # Cleanup temp file
            os.unlink(tmp_path)
    
    def _detect_mime_from_content(self, content: bytes) -> str:
        """
        Detect MIME type from file content (magic bytes)
        
        More reliable than declared Content-Type header
        """
        
        # Check magic bytes
        for magic_bytes, mime_type in self.VIDEO_MAGIC_BYTES.items():
            if content.startswith(magic_bytes):
                return mime_type
        
        # Fallback to libmagic
        try:
            # Write to temp file for libmagic
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp.write(content[:8192])  # First 8KB
                tmp_path = tmp.name
            
            detected = self.mime_detector.from_file(tmp_path)
            os.unlink(tmp_path)
            
            return detected
        except:
            return "application/octet-stream"
    
    def _is_polyglot_file(self, content: bytes) -> bool:
        """
        Detect polyglot files (multiple valid formats)
        
        Example: File that's both valid video AND valid HTML/JS
        Common attack: Embed script in video metadata
        """
        
        # Check for HTML/JS markers in video file
        dangerous_patterns = [
            b"<script",
            b"javascript:",
            b"onerror=",
            b"onclick=",
            b"<iframe",
            b"eval(",
            b"<?php",
            b"<%",  # ASP/JSP
        ]
        
        content_lower = content.lower()
        
        for pattern in dangerous_patterns:
            if pattern in content_lower:
                return True
        
        # Check for embedded executables
        executable_signatures = [
            b"MZ",  # Windows EXE
            b"\x7fELF",  # Linux ELF
            b"\xca\xfe\xba\xbe",  # Mach-O
        ]
        
        for signature in executable_signatures:
            if signature in content:
                return True
        
        return False
    
    def _verify_video_integrity(self, video_path: str) -> Tuple[bool, Dict[str, Any]]:
        """
        Verify video file integrity using ffprobe
        
        Returns:
            (is_valid, metadata)
        """
        
        try:
            # Run ffprobe
            result = subprocess.run([
                "ffprobe",
                "-v", "error",
                "-show_format",
                "-show_streams",
                "-of", "json",
                video_path
            ], capture_output=True, text=True, timeout=10)
            
            if result.returncode != 0:
                return False, {}
            
            # Parse output
            import json
            data = json.loads(result.stdout)
            
            # Extract metadata
            format_info = data.get("format", {})
            streams = data.get("streams", [])
            
            video_stream = None
            for stream in streams:
                if stream.get("codec_type") == "video":
                    video_stream = stream
                    break
            
            if not video_stream:
                return False, {}
            
            metadata = {
                "duration": float(format_info.get("duration", 0)),
                "size": int(format_info.get("size", 0)),
                "width": int(video_stream.get("width", 0)),
                "height": int(video_stream.get("height", 0)),
                "fps": eval(video_stream.get("r_frame_rate", "0/1"))
            }
            
            return True, metadata
            
        except Exception as e:
            print(f"Video integrity check failed: {e}")
            return False, {}
    
    def scan_for_malware(self, file_path: str) -> bool:
        """
        Scan file for malware using ClamAV (optional)
        
        Returns:
            True if clean, False if infected
        """
        
        # Check if ClamAV is available
        try:
            result = subprocess.run([
                "clamscan",
                "--no-summary",
                file_path
            ], capture_output=True, text=True, timeout=30)
            
            # ClamAV returns 0 if clean, 1 if infected
            return result.returncode == 0
            
        except FileNotFoundError:
            # ClamAV not installed - skip scan
            print("Warning: ClamAV not available, skipping malware scan")
            return True
        except Exception as e:
            print(f"Malware scan error: {e}")
            return True  # Fail open (don't block on scan errors)
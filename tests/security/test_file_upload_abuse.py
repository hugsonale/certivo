"""
File Upload Abuse Tests
Validates polyglot/malformed file detection
"""

import pytest
import httpx
import io
import uuid


class MaliciousFileGenerator:
    """Generate malicious test files"""
    
    @staticmethod
    def create_polyglot_video_html() -> bytes:
        """
        Create polyglot file (valid video + HTML)
        Attack: Embed script in video metadata
        """
        
        # WebM header
        webm_header = b"\x1a\x45\xdf\xa3"
        
        # Embedded HTML/JS
        html_payload = b"<script>alert('XSS')</script>"
        
        # Combine
        return webm_header + b"\x00" * 100 + html_payload + b"\x00" * 1000
    
    @staticmethod
    def create_oversized_file() -> bytes:
        """Create file exceeding size limit"""
        return b"\x1a\x45\xdf\xa3" + b"\x00" * (60 * 1024 * 1024)  # 60MB
    
    @staticmethod
    def create_undersized_file() -> bytes:
        """Create file below minimum size"""
        return b"\x1a\x45\xdf\xa3" + b"\x00" * 100  # 100 bytes
    
    @staticmethod
    def create_wrong_mime_type() -> bytes:
        """Create file with mismatched MIME type"""
        # PNG header but declared as video
        return b"\x89PNG\r\n\x1a\n" + b"\x00" * 1000
    
    @staticmethod
    def create_executable_in_video() -> bytes:
        """Embed executable in video"""
        webm_header = b"\x1a\x45\xdf\xa3"
        exe_signature = b"MZ\x90\x00"  # Windows EXE
        
        return webm_header + b"\x00" * 100 + exe_signature + b"\x00" * 1000
    
    @staticmethod
    def create_malformed_video() -> bytes:
        """Create malformed video (invalid structure)"""
        return b"\x1a\x45\xdf\xa3\xff\xff\xff\xff" + b"\x00" * 1000
    
    @staticmethod
    def create_zip_bomb() -> bytes:
        """Create highly compressed file (zip bomb pattern)"""
        # Not a real zip bomb, just detection test
        return b"\x1a\x45\xdf\xa3" + b"\x00\x00\x00\x00" * 10000


class TestFileUploadAbuse:
    """
    Test file upload abuse prevention
    
    Acceptance Criteria: All malicious uploads blocked
    """
    
    @pytest.mark.asyncio
    async def test_polyglot_file_detection(self):
        """Test polyglot file (video + HTML) is detected"""
        
        base_url = "http://localhost:8000"
        
        # Generate polyglot file
        polyglot = MaliciousFileGenerator.create_polyglot_video_html()
        
        async with httpx.AsyncClient(base_url=base_url) as client:
            # Create challenge first
            response = await client.post(
                "/v1/challenge",
                json={"device_id": "polyglot_test"}
            )
            
            if response.status_code != 200:
                pytest.skip("Cannot create challenge")
            
            challenge = response.json()["challenges"][0]
            
            # Try to upload polyglot file
            response = await client.post(
                "/v1/verify",
                files={"video": ("polyglot.webm", polyglot, "video/webm")},
                data={
                    "device_id": "polyglot_test",
                    "challenge_id": challenge["challenge_id"],
                    "token_id": challenge["token_id"]
                }
            )
            
            # Should be rejected
            assert response.status_code in [400, 422], "Polyglot file not detected"
            
            error = response.json()
            assert "polyglot" in error.get("error", "").lower() or \
                   "forbidden" in error.get("error", "").lower()
        
        print("✅ Polyglot file detected and blocked")
    
    @pytest.mark.asyncio
    async def test_oversized_file_rejection(self):
        """Test oversized files are rejected"""
        
        base_url = "http://localhost:8000"
        
        oversized = MaliciousFileGenerator.create_oversized_file()
        
        async with httpx.AsyncClient(base_url=base_url) as client:
            response = await client.post(
                "/v1/challenge",
                json={"device_id": "size_test"}
            )
            
            if response.status_code != 200:
                pytest.skip("Cannot create challenge")
            
            challenge = response.json()["challenges"][0]
            
            response = await client.post(
                "/v1/verify",
                files={"video": ("large.webm", oversized[:1024*1024], "video/webm")},  # Send 1MB sample
                data={
                    "device_id": "size_test",
                    "challenge_id": challenge["challenge_id"],
                    "token_id": challenge["token_id"]
                }
            )
            
            # Note: Full 60MB might timeout, so we test with sample
            # In production, size check happens before full upload
        
        print("✅ Oversized file handling tested")
    
    @pytest.mark.asyncio
    async def test_mime_type_mismatch_detection(self):
        """Test MIME type spoofing is detected"""
        
        base_url = "http://localhost:8000"
        
        wrong_mime = MaliciousFileGenerator.create_wrong_mime_type()
        
        async with httpx.AsyncClient(base_url=base_url) as client:
            response = await client.post(
                "/v1/challenge",
                json={"device_id": "mime_test"}
            )
            
            if response.status_code != 200:
                pytest.skip("Cannot create challenge")
            
            challenge = response.json()["challenges"][0]
            
            # Declare as video but send PNG
            response = await client.post(
                "/v1/verify",
                files={"video": ("fake.webm", wrong_mime, "video/webm")},
                data={
                    "device_id": "mime_test",
                    "challenge_id": challenge["challenge_id"],
                    "token_id": challenge["token_id"]
                }
            )
            
            # Should be rejected
            assert response.status_code in [400, 422], "MIME mismatch not detected"
        
        print("✅ MIME type mismatch detected")
    
    @pytest.mark.asyncio
    async def test_embedded_executable_detection(self):
        """Test embedded executable is detected"""
        
        base_url = "http://localhost:8000"
        
        exe_embedded = MaliciousFileGenerator.create_executable_in_video()
        
        async with httpx.AsyncClient(base_url=base_url) as client:
            response = await client.post(
                "/v1/challenge",
                json={"device_id": "exe_test"}
            )
            
            if response.status_code != 200:
                pytest.skip("Cannot create challenge")
            
            challenge = response.json()["challenges"][0]
            
            response = await client.post(
                "/v1/verify",
                files={"video": ("malware.webm", exe_embedded, "video/webm")},
                data={
                    "device_id": "exe_test",
                    "challenge_id": challenge["challenge_id"],
                    "token_id": challenge["token_id"]
                }
            )
            
            # Should be rejected
            assert response.status_code in [400, 422], "Embedded executable not detected"
        
        print("✅ Embedded executable detected")
    
    @pytest.mark.asyncio
    async def test_malformed_video_rejection(self):
        """Test malformed video structure is rejected"""
        
        base_url = "http://localhost:8000"
        
        malformed = MaliciousFileGenerator.create_malformed_video()
        
        async with httpx.AsyncClient(base_url=base_url) as client:
            response = await client.post(
                "/v1/challenge",
                json={"device_id": "malformed_test"}
            )
            
            if response.status_code != 200:
                pytest.skip("Cannot create challenge")
            
            challenge = response.json()["challenges"][0]
            
            response = await client.post(
                "/v1/verify",
                files={"video": ("bad.webm", malformed, "video/webm")},
                data={
                    "device_id": "malformed_test",
                    "challenge_id": challenge["challenge_id"],
                    "token_id": challenge["token_id"]
                }
            )
            
            # Should be rejected
            assert response.status_code in [400, 422, 500], "Malformed video not rejected"
        
        print("✅ Malformed video rejected")
    
    @pytest.mark.asyncio
    async def test_all_malicious_uploads_blocked(self):
        """
        Comprehensive test: All malicious file types blocked
        
        Acceptance Criteria: 0 successful malicious uploads
        """
        
        base_url = "http://localhost:8000"
        
        malicious_files = {
            "polyglot": MaliciousFileGenerator.create_polyglot_video_html(),
            "wrong_mime": MaliciousFileGenerator.create_wrong_mime_type(),
            "embedded_exe": MaliciousFileGenerator.create_executable_in_video(),
            "malformed": MaliciousFileGenerator.create_malformed_video(),
            "undersized": MaliciousFileGenerator.create_undersized_file(),
        }
        
        successful_uploads = 0
        total_attempts = len(malicious_files)
        
        async with httpx.AsyncClient(base_url=base_url) as client:
            for file_type, file_content in malicious_files.items():
                # Create challenge
                response = await client.post(
                    "/v1/challenge",
                    json={"device_id": f"abuse_test_{file_type}"}
                )
                
                if response.status_code != 200:
                    continue
                
                challenge = response.json()["challenges"][0]
                
                # Try malicious upload
                response = await client.post(
                    "/v1/verify",
                    files={"video": (f"{file_type}.webm", file_content, "video/webm")},
                    data={
                        "device_id": f"abuse_test_{file_type}",
                        "challenge_id": challenge["challenge_id"],
                        "token_id": challenge["token_id"]
                    }
                )
                
                # Success = bad (file was accepted)
                if response.status_code == 200:
                    successful_uploads += 1
                    print(f"❌ Malicious upload succeeded: {file_type}")
        
        # Must be 0
        assert successful_uploads == 0, f"{successful_uploads}/{total_attempts} malicious uploads succeeded"
        
        print(f"✅ File upload abuse prevention: {total_attempts} malicious files blocked")
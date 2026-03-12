# Contributing to Certivo

Thank you for your interest in contributing to Certivo! This guide will help you get started.

---

## 📋 Table of Contents

1. [Getting Started](#getting-started)
2. [Development Environment](#development-environment)
3. [Code Structure](#code-structure)
4. [Coding Standards](#coding-standards)
5. [Testing Requirements](#testing-requirements)
6. [Commit Guidelines](#commit-guidelines)
7. [Pull Request Process](#pull-request-process)
8. [Adding New Features](#adding-new-features)
9. [Bug Reports](#bug-reports)
10. [Questions & Support](#questions--support)

---

## 🚀 Getting Started

### Prerequisites
- Python 3.9+ (3.11 recommended)
- Git
- Basic knowledge of FastAPI
- Familiarity with OpenCV/MediaPipe (for CV work)

### Fork and Clone
```bash
# Fork the repository on GitHub first

# Clone your fork
git clone https://github.com/YOUR-USERNAME/certivo.git
cd certivo

# Add upstream remote
git remote add upstream https://github.com/ORIGINAL-REPO/certivo.git
```

---

## 💻 Development Environment

### Setup
```bash
# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Install development dependencies
pip install pytest pytest-cov pytest-asyncio black flake8 mypy

# Copy environment template
cp .env.example .env

# Edit .env with your settings
nano .env
```

### Run Development Server
```bash
# Start server with auto-reload
uvicorn main:app --reload --host 127.0.0.1 --port 8000

# Visit http://127.0.0.1:8000
```

### Run Tests
```bash
# All tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=. --cov-report=html

# Specific test file
pytest tests/test_challenge_engine.py -v

# Single test
pytest tests/test_database.py::test_store_and_retrieve_challenge -v
```

---

## 📁 Code Structure
```
certivo/
├── main.py                    # FastAPI app, routes, middleware
├── database.py                # SQLAlchemy models, DB operations
├── challenge_engine.py        # Challenge generation logic
├── human_verification.py      # Computer vision, liveness detection
├── rate_limiter.py           # Rate limiting logic
├── bot_detector.py           # Bot detection algorithms
├── logger.py                 # Logging utilities
├── cache.py                  # Caching layer
├── admin/                    # Admin dashboard
│   ├── routes.py             # Admin routes
│   ├── auth.py               # Authentication
│   ├── services.py           # Business logic
│   ├── utils.py              # Helpers
│   ├── config.py             # Configuration
│   └── templates/            # Jinja2 templates
├── static/                   # Static assets
├── templates/                # Frontend templates
├── tests/                    # Test suite
│   ├── test_challenge_engine.py
│   ├── test_database.py
│   └── test_integration.py
├── migrations/               # Database migrations
├── logs/                     # Application logs
├── docs/                     # Documentation
└── requirements.txt          # Python dependencies
```

---

## 📏 Coding Standards

### Python Style Guide

We follow **PEP 8** with some modifications:
```python
# Good
def calculate_trust_score(success_rate: float, liveness_score: float) -> float:
    """
    Calculate device trust score.
    
    Args:
        success_rate: Verification success rate (0-1)
        liveness_score: Average liveness score (0-1)
        
    Returns:
        Trust score (0-100)
    """
    return (success_rate * 70) + (liveness_score * 30)


# Bad
def calc_score(sr,ls):  # No types, unclear names
    return sr*70+ls*30  # No docstring, unclear formula
```

### Type Hints
Always use type hints for function parameters and returns:
```python
# Good
def store_challenge(
    db: Session,
    challenge_id: str,
    device_id: str,
    expires_at: datetime
) -> ActiveChallenge:
    pass

# Bad
def store_challenge(db, challenge_id, device_id, expires_at):
    pass
```

### Docstrings
Use Google-style docstrings:
```python
def detect_blinks(video_path: str, fast_track: bool = False) -> dict:
    """
    Detect eye blinks in video using Eye Aspect Ratio.
    
    Args:
        video_path: Path to video file
        fast_track: If True, use easier thresholds
        
    Returns:
        Dictionary containing:
            - passed: bool
            - blink_count: int
            - face_detected_frames: int
            
    Raises:
        FileNotFoundError: If video_path doesn't exist
    """
    pass
```

### Code Formatting
```bash
# Format with Black
black . --line-length 100

# Check style with flake8
flake8 . --max-line-length=100 --exclude=venv

# Type checking with mypy
mypy main.py database.py
```

---

## ✅ Testing Requirements

### All Code Must Be Tested

**Minimum requirements:**
- Unit tests for new functions
- Integration tests for new endpoints
- Code coverage > 70% for modified files

### Writing Tests
```python
# tests/test_challenge_engine.py

def test_trusted_device_gets_one_challenge():
    """Trusted devices should receive exactly 1 easy challenge."""
    challenges = generate_adaptive_challenges(trusted=True, num=1)
    
    assert len(challenges) == 1
    assert challenges[0]['difficulty'] == 'easy'
    assert challenges[0]['fast_track'] == True


def test_challenge_has_required_fields():
    """Every challenge must have all required fields."""
    challenges = generate_adaptive_challenges(trusted=False, num=1)
    
    required = ['challenge_id', 'expected_movement', 'difficulty']
    for field in required:
        assert field in challenges[0]
```

### Running Tests Before Commit
```bash
# Run full test suite
pytest tests/ -v

# Check coverage
pytest tests/ --cov=. --cov-report=term-missing

# Coverage must be > 70%
```

---

## 📝 Commit Guidelines

### Commit Message Format
```
<type>(<scope>): <subject>

<body>

<footer>
```

### Types
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code formatting (no logic change)
- `refactor`: Code restructuring (no feature/bug change)
- `perf`: Performance improvement
- `test`: Adding/updating tests
- `chore`: Maintenance tasks

### Examples
```bash
# Good commits
feat(challenge): add eyebrow raise detection
fix(rate-limiter): correct sliding window calculation
docs(api): update endpoint descriptions
test(database): add trust revocation tests

# Bad commits
updated stuff
fix bug
changes
WIP
```

### Commit Body (Optional)
```
feat(bot-detector): add pattern matching algorithm

Implements behavioral analysis to detect repeated
submission patterns. Tracks video fingerprints and
flags identical submissions.

Closes #42
```

---

## 🔀 Pull Request Process

### 1. Create Feature Branch
```bash
# Update main
git checkout main
git pull upstream main

# Create feature branch
git checkout -b feat/add-gesture-detection
```

### 2. Make Changes
```bash
# Write code
# Write tests
# Update documentation

# Run tests
pytest tests/ -v

# Format code
black . --line-length 100

# Check style
flake8 .
```

### 3. Commit Changes
```bash
git add .
git commit -m "feat(verification): add gesture detection support"
```

### 4. Push and Create PR
```bash
# Push to your fork
git push origin feat/add-gesture-detection

# Go to GitHub and create Pull Request
```

### 5. PR Checklist

Before submitting, ensure:

- [ ] All tests pass
- [ ] Code coverage ≥ 70%
- [ ] Code formatted with Black
- [ ] No flake8 warnings
- [ ] Documentation updated
- [ ] Changelog updated (if applicable)
- [ ] Commit messages follow guidelines
- [ ] PR description explains changes

### PR Template
```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Testing
- [ ] Unit tests added/updated
- [ ] Integration tests added/updated
- [ ] Manual testing completed

## Checklist
- [ ] Code follows style guidelines
- [ ] Self-review completed
- [ ] Comments added for complex code
- [ ] Documentation updated
- [ ] Tests passing
```

---

## 🎯 Adding New Features

### 1. New Challenge Type

**Example:** Adding "smile" detection

**Files to modify:**
```
human_verification.py    # Add detect_smile() function
challenge_engine.py      # Add "smile" to valid movements
main.py                  # (no changes needed)
tests/                   # Add test_smile_detection()
```

**Implementation:**
```python
# human_verification.py

def detect_smile(video_path: str, fast_track: bool = False) -> dict:
    """
    Detect smile using mouth corner landmarks.
    
    Args:
        video_path: Path to video file
        fast_track: Use easier thresholds if True
        
    Returns:
        Detection result dictionary
    """
    # Implementation here
    pass


# Update VALID_MOVEMENTS
VALID_MOVEMENTS = {"left", "right", "blink", "nod", "mouth", "eyebrows", "smile"}

# Update _run_detector()
def _run_detector(expected_movement: str, video_path: str, fast_track: bool):
    # ... existing code ...
    elif m == "smile":
        return detect_smile(video_path, fast_track)
```

**Test:**
```python
# tests/test_human_verification.py

def test_smile_detection():
    """Should detect smile in video."""
    # Create test video or mock
    result = detect_smile("test_video.webm", fast_track=False)
    
    assert result["passed"] == True
    assert "smile_frames" in result
```

---

### 2. New API Endpoint

**Example:** Adding device statistics endpoint
```python
# main.py

@app.get(
    "/v1/device/{device_id}/history",
    summary="Get device verification history",
    tags=["Device"]
)
async def get_device_history(
    device_id: str,
    limit: int = 10,
    db: Session = Depends(get_db)
):
    """
    Retrieve verification history for a device.
    
    Args:
        device_id: Device identifier
        limit: Maximum number of records
        
    Returns:
        List of verification attempts
    """
    results = get_session_results(db, device_id)
    return {
        "device_id": device_id,
        "history": results[:limit]
    }
```

**Test:**
```python
# tests/test_integration.py

def test_device_history_endpoint(client):
    """Should return device history."""
    response = client.get("/v1/device/test_device/history?limit=5")
    
    assert response.status_code == 200
    data = response.json()
    assert "history" in data
    assert len(data["history"]) <= 5
```

---

### 3. New Admin Dashboard Page

**Files needed:**
```
admin/routes.py               # Add route
admin/templates/my_page.html  # Add template
admin/services.py             # Add business logic (if needed)
```

**Example:**
```python
# admin/routes.py

@admin_router.get("/my-page")
async def my_page(request: Request, db: Session = Depends(get_db)):
    """My custom admin page."""
    if not is_authenticated(request):
        return RedirectResponse("/admin/login", status_code=303)
    
    # Get data
    data = get_my_data(db)
    
    # Render template
    return templates.TemplateResponse(
        "my_page.html",
        {"request": request, "data": data}
    )
```

---

## 🐛 Bug Reports

### Before Reporting

1. Search existing issues
2. Check documentation
3. Verify it's reproducible
4. Test on latest version

### Bug Report Template
```markdown
## Bug Description
Clear description of the bug

## Steps to Reproduce
1. Go to '...'
2. Click on '....'
3. See error

## Expected Behavior
What should happen

## Actual Behavior
What actually happens

## Environment
- OS: Ubuntu 22.04
- Python: 3.11.0
- Browser: Chrome 120
- Certivo Version: 1.0.0

## Logs
```
Paste relevant logs here
```

## Screenshots
If applicable
```

---

## ❓ Questions & Support

### Where to Ask

- **Usage Questions:** GitHub Discussions
- **Bug Reports:** GitHub Issues
- **Feature Requests:** GitHub Issues (label: enhancement)
- **Security Issues:** Email security@certivo.com (do not post publicly)

### Response Time

- Critical bugs: 24 hours
- Regular bugs: 3-5 days
- Feature requests: 1-2 weeks
- Questions: 1-3 days

---

## 📜 Code of Conduct

### Our Standards

✅ **Do:**
- Be respectful and inclusive
- Welcome newcomers
- Give and accept constructive feedback
- Focus on what's best for the project

❌ **Don't:**
- Use inappropriate language
- Harass or discriminate
- Publish private information
- Act unprofessionally

### Enforcement

Violations should be reported to: conduct@certivo.com

---

## 🏆 Recognition

Contributors will be:
- Listed in CONTRIBUTORS.md
- Credited in release notes
- Given GitHub contributor badge

---

## 📚 Additional Resources

- [Architecture Overview](ARCHITECTURE.md)
- [API Documentation](http://localhost:8000/docs)
- [Deployment Guide](DEPLOYMENT.md)
- [Admin Guide](ADMIN_GUIDE.md)
- [Error Codes](ERROR_CODES.md)

---

## 📄 License

By contributing, you agree that your contributions will be licensed under the same license as the project.

---

**Thank you for contributing to Certivo!** 🎉

**Last Updated:** 2026-03-12  
**Version:** 1.0.0
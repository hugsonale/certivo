# Challenge Testing Checklist

Test all 6 challenge types for Phase 3 completion.

---

## 🎯 Success Criteria

- Each challenge type: **80%+ success rate**
- All 6 challenges appear randomly
- No false positives (legitimate users blocked)
- Clear, helpful error messages

---

## ✅ Testing Protocol

### For Each Challenge Type:

1. **Start fresh verification**
2. **Allow camera access**
3. **Complete face calibration**
4. **Read instruction carefully**
5. **Perform action clearly**
6. **Record result (pass/fail)**

### Repeat 5 times per challenge type

---

## 📊 Challenge Testing Grid

### 1. Turn Left

| Attempt | Result | Notes |
|---------|--------|-------|
| 1 | ⬜ Pass / ❌ Fail | |
| 2 | ⬜ Pass / ❌ Fail | |
| 3 | ⬜ Pass / ❌ Fail | |
| 4 | ⬜ Pass / ❌ Fail | |
| 5 | ⬜ Pass / ❌ Fail | |

**Success Rate:** ____ / 5 = ____%

---

### 2. Turn Right

| Attempt | Result | Notes |
|---------|--------|-------|
| 1 | ⬜ Pass / ❌ Fail | |
| 2 | ⬜ Pass / ❌ Fail | |
| 3 | ⬜ Pass / ❌ Fail | |
| 4 | ⬜ Pass / ❌ Fail | |
| 5 | ⬜ Pass / ❌ Fail | |

**Success Rate:** ____ / 5 = ____%

---

### 3. Blink

| Attempt | Result | Notes |
|---------|--------|-------|
| 1 | ⬜ Pass / ❌ Fail | |
| 2 | ⬜ Pass / ❌ Fail | |
| 3 | ⬜ Pass / ❌ Fail | |
| 4 | ⬜ Pass / ❌ Fail | |
| 5 | ⬜ Pass / ❌ Fail | |

**Success Rate:** ____ / 5 = ____%

---

### 4. Nod

| Attempt | Result | Notes |
|---------|--------|-------|
| 1 | ⬜ Pass / ❌ Fail | |
| 2 | ⬜ Pass / ❌ Fail | |
| 3 | ⬜ Pass / ❌ Fail | |
| 4 | ⬜ Pass / ❌ Fail | |
| 5 | ⬜ Pass / ❌ Fail | |

**Success Rate:** ____ / 5 = ____%

---

### 5. Open Mouth

| Attempt | Result | Notes |
|---------|--------|-------|
| 1 | ⬜ Pass / ❌ Fail | |
| 2 | ⬜ Pass / ❌ Fail | |
| 3 | ⬜ Pass / ❌ Fail | |
| 4 | ⬜ Pass / ❌ Fail | |
| 5 | ⬜ Pass / ❌ Fail | |

**Success Rate:** ____ / 5 = ____%

---

### 6. Raise Eyebrows

| Attempt | Result | Notes |
|---------|--------|-------|
| 1 | ⬜ Pass / ❌ Fail | |
| 2 | ⬜ Pass / ❌ Fail | |
| 3 | ⬜ Pass / ❌ Fail | |
| 4 | ⬜ Pass / ❌ Fail | |
| 5 | ⬜ Pass / ❌ Fail | |

**Success Rate:** ____ / 5 = ____%

---

## 📈 Overall Results

| Challenge | Success Rate | Status |
|-----------|--------------|--------|
| Left | ___% | ⬜ / ❌ |
| Right | ___% | ⬜ / ❌ |
| Blink | ___% | ⬜ / ❌ |
| Nod | ___% | ⬜ / ❌ |
| Mouth | ___% | ⬜ / ❌ |
| Eyebrows | ___% | ⬜ / ❌ |

**Overall Success Rate:** ____%

**Target:** 80%+ for each challenge

---

## 🐛 Common Issues & Solutions

### Low Success Rate (<50%)

**Check:**
- Good lighting (face well-lit)
- Camera quality (not too blurry)
- Face centered in frame
- Action performed clearly

**Adjust if needed:**
- Increase thresholds in `human_verification.py`
- Check terminal logs for actual values
- Compare detected values vs thresholds

### High False Positives

**Check:**
- Thresholds too lenient
- Random movements being detected
- Video quality issues

**Adjust if needed:**
- Decrease thresholds slightly
- Add more validation frames

### Challenge Not Appearing

**Check:**
- All 6 in VALID_MOVEMENTS list
- Random selection working
- Database has no old cached challenges

---

## 🔧 Threshold Tuning Guide

If success rate is:

- **< 30%**: Thresholds WAY too strict - halve them
- **30-60%**: Thresholds too strict - reduce by 25%
- **60-80%**: Almost there - reduce by 10%
- **80-95%**: ✅ PERFECT - don't change
- **> 95%**: Too easy - increase by 10%

---

## 📝 Notes Section

Write observations here:
```
Lighting conditions:
Camera quality:
Browser used:
Any patterns noticed:
Suggested threshold changes:
```
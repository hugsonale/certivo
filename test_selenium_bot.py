from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, UnexpectedAlertPresentException
import time

print("🤖 Starting Selenium bot test...")
print("=" * 50)

# Initialize Chrome driver
options = webdriver.ChromeOptions()
# Don't add any special options - we want default Selenium behavior
# options.add_argument('--headless')  # Uncomment to test headless

driver = webdriver.Chrome(
    service=Service(ChromeDriverManager().install()),
    options=options
)

try:
    print("📍 Navigating to http://127.0.0.1:8000...")
    driver.get("http://127.0.0.1:8000")
    
    print("⏳ Waiting for page to load...")
    time.sleep(2)
    
    # Check webdriver flag (should be True in Selenium)
    webdriver_flag = driver.execute_script("return navigator.webdriver;")
    print(f"🔍 navigator.webdriver = {webdriver_flag}")
    
    # Find and click the "Start Face Verification" button
    print("🔘 Looking for 'Start Face Verification' button...")
    
    try:
        # Wait up to 5 seconds for button to be clickable
        start_button = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.ID, "startFaceBtn"))
        )
        
        print("✅ Button found! Clicking...")
        start_button.click()
        
        print("⏳ Waiting 3 seconds for bot detection to run...")
        time.sleep(3)
        
        # Check if alert appeared (bot detection triggered)
        try:
            alert = driver.switch_to.alert
            alert_text = alert.text
            print(f"\n🚨 ALERT DETECTED: {alert_text}")
            print("✅ SUCCESS: Bot detection is working!")
            alert.accept()
            bot_detected = True
        except:
            print("\n⚠️  No alert detected")
            print("   This could mean:")
            print("   1. Bot detection is in 'warn' mode (not blocking)")
            print("   2. Frontend bot detection didn't trigger")
            print("   3. Backend bot detection didn't trigger")
            bot_detected = False
        
        # Check browser console for bot detection logs
        print("\n🔍 Checking browser console logs...")
        logs = driver.get_log('browser')
        
        found_bot_logs = False
        for log in logs:
            msg = log['message']
            if any(keyword in msg.lower() for keyword in ['bot', 'automated', 'suspicion', 'webdriver']):
                print(f"   📋 {msg}")
                found_bot_logs = True
        
        if not found_bot_logs:
            print("   ℹ️  No bot-related messages in console")
        
        # Check page source for error messages
        page_source = driver.page_source
        if "BOT_DETECTED" in page_source or "Automated access detected" in page_source:
            print("\n✅ Bot detection error found in page!")
            bot_detected = True
        
        if bot_detected:
            print("\n" + "=" * 50)
            print("✅ TEST PASSED: Bot was successfully detected!")
            print("=" * 50)
        else:
            print("\n" + "=" * 50)
            print("⚠️  TEST RESULT: Bot detection may not be working")
            print("   Check server logs for backend detection")
            print("=" * 50)
    
    except TimeoutException:
        print("❌ Button not found within 5 seconds")
        print("   Make sure index.html is being served correctly")
    
    # Keep browser open for inspection
    print("\n⏸  Browser will stay open for 15 seconds for inspection...")
    time.sleep(15)

except UnexpectedAlertPresentException as e:
    print(f"🚨 Alert appeared: {e}")
    print("✅ Bot detection is working!")

except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()

finally:
    print("\n🔚 Closing browser...")
    driver.quit()
    print("=" * 50)
    print("Test complete!")
"""
Certivo Load Testing Script
Tests system performance under concurrent load

Run with:
    locust -f tests/load_test.py --host=http://127.0.0.1:8000
"""

from locust import HttpUser, task, between, events
import random
import time

# Track success/failure rates
success_count = 0
failure_count = 0
response_times = []


@events.request.add_listener
def on_request(request_type, name, response_time, response_length, exception, **kwargs):
    """Track request metrics"""
    global success_count, failure_count, response_times
    
    if exception:
        failure_count += 1
    else:
        success_count += 1
        response_times.append(response_time)


class VerificationUser(HttpUser):
    """
    Simulates a user performing verification challenges
    """
    
    # Wait 1-3 seconds between requests (simulates real user behavior)
    wait_time = between(1, 3)
    
    # Store device ID for this user session
    device_id = None
    
    def on_start(self):
        """Called when user starts - generate unique device ID"""
        self.device_id = f"load_test_device_{random.randint(1000, 9999)}"
        print(f"🔹 User started with device_id: {self.device_id}")
    
    """
    @task(5)  # Weight: 5 (runs 5x more often than other tasks)
    def get_challenge(self):
    
        TEST 1: Get Challenge
        Most common operation - should be fast
        
        with self.client.get(
            f"/v1/challenge?device_id={self.device_id}",
            catch_response=True,
            name="GET /v1/challenge"
        ) as response:
            if response.status_code == 200:
                data = response.json()
                if "challenges" in data:
                    response.success()
                else:
                    response.failure("No challenges in response")
            elif response.status_code == 429:
                # Rate limited - this is expected behavior
                response.success()
            else:
                response.failure(f"Status code: {response.status_code}")

        """
    
    @task(2)  # Weight: 2 (runs 2x more often than task(1))
    def get_device_stats(self):
        """
        TEST 2: Get Device Stats
        Database query - tests connection pooling
        """
        with self.client.get(
            f"/v1/device/{self.device_id}/stats",
            catch_response=True,
            name="GET /v1/device/stats"
        ) as response:
            if response.status_code in [200, 404]:
                # 404 is OK (device not found yet)
                response.success()
            else:
                response.failure(f"Status code: {response.status_code}")
    
    @task(1)  # Weight: 1 (runs least often)
    def admin_bot_stats(self):
        """
        TEST 3: Admin Bot Stats
        Heavy database query - tests system under load
        """
        with self.client.get(
            "/v1/admin/bot-stats",
            catch_response=True,
            name="GET /v1/admin/bot-stats"
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Status code: {response.status_code}")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Print summary when test stops"""
    print("\n" + "=" * 60)
    print("📊 LOAD TEST SUMMARY")
    print("=" * 60)
    print(f"✅ Successful requests: {success_count}")
    print(f"❌ Failed requests: {failure_count}")
    
    if response_times:
        avg_time = sum(response_times) / len(response_times)
        max_time = max(response_times)
        min_time = min(response_times)
        print(f"⏱️  Average response time: {avg_time:.2f}ms")
        print(f"⏱️  Max response time: {max_time:.2f}ms")
        print(f"⏱️  Min response time: {min_time:.2f}ms")
    
    total = success_count + failure_count
    if total > 0:
        success_rate = (success_count / total) * 100
        print(f"📈 Success rate: {success_rate:.2f}%")
    
    print("=" * 60)
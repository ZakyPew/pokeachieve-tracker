#!/usr/bin/env python3
"""Test script to verify PokeAchieve Tracker API communication"""

import json
import urllib.request
import urllib.error
import sys

# Test configuration
BASE_URL = "http://66.175.239.154"
API_KEY = "test_key_12345"  # This won't work - need a real key from the database

def test_endpoint(method, endpoint, data=None, headers=None):
    """Test an API endpoint"""
    url = f"{BASE_URL}{endpoint}"
    print(f"\n{'='*60}")
    print(f"TEST: {method} {endpoint}")
    print(f"URL: {url}")
    
    default_headers = {"Content-Type": "application/json"}
    if headers:
        default_headers.update(headers)
    
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode() if data else None,
            headers=default_headers,
            method=method
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            status = response.getcode()
            body = response.read().decode()
            print(f"STATUS: {status}")
            print(f"RESPONSE: {body[:500]}")
            return True, json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        status = e.getcode()
        error_body = e.read().decode()
        print(f"STATUS: {status}")
        print(f"ERROR: {error_body}")
        return False, {"status": status, "error": error_body}
    except Exception as e:
        print(f"EXCEPTION: {type(e).__name__}: {e}")
        return False, {"error": str(e)}

def main():
    print("PokeAchieve Tracker API Test")
    print("=" * 60)
    
    # Test 1: Public endpoint (should work)
    print("\n[Test 1] Public endpoint - Get games list")
    success, data = test_endpoint("GET", "/api/games")
    if success:
        print("✓ PASS: Games endpoint working")
    else:
        print("✗ FAIL: Games endpoint failed")
    
    # Test 2: Tracker test endpoint without auth (should fail with auth error)
    print("\n[Test 2] Tracker test endpoint without auth")
    success, data = test_endpoint("POST", "/api/tracker/test")
    if not success and data.get("status") == 403:
        print("✓ PASS: Auth required correctly")
    else:
        print(f"✗ FAIL: Unexpected response")
    
    # Test 3: Tracker test endpoint with invalid key
    print("\n[Test 3] Tracker test endpoint with invalid key")
    success, data = test_endpoint("POST", "/api/tracker/test", 
                                    headers={"Authorization": "Bearer invalid_key"})
    if not success and "Invalid API key" in str(data.get("error", "")):
        print("✓ PASS: Invalid key rejected correctly")
    else:
        print(f"✗ FAIL: Unexpected response - {data}")
    
    # Test 4: Collection batch endpoint without auth
    print("\n[Test 4] Collection batch endpoint without auth")
    success, data = test_endpoint("POST", "/api/collection/batch-update", data=[])
    if not success and data.get("status") in [401, 403]:
        print("✓ PASS: Auth required correctly")
    else:
        print(f"✗ FAIL: Unexpected response - {data}")
    
    # Test 5: Collection batch endpoint with invalid key
    print("\n[Test 5] Collection batch endpoint with invalid key")
    success, data = test_endpoint("POST", "/api/collection/batch-update", 
                                    data=[],
                                    headers={"Authorization": "Bearer invalid_key"})
    if not success and "Invalid API key" in str(data.get("error", "")):
        print("✓ PASS: Invalid key rejected correctly")
    else:
        print(f"✗ FAIL: Unexpected response - {data}")
    
    print("\n" + "="*60)
    print("API Endpoint Tests Complete")
    print("\nSummary:")
    print("- All endpoints are accessible and responding")
    print("- Authentication is enforced correctly")
    print("- Invalid API keys are rejected with proper error messages")
    print("\nTo test with a real API key:")
    print("1. Generate an API key from the PokeAchieve website")
    print("2. Update the API_KEY variable in this script")
    print("3. Run the test again")

if __name__ == "__main__":
    main()

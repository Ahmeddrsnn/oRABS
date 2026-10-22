"""
Generate Dummy Data Script
Populates the database with synthetic test records and audit logs for testing reporting features.
"""

import sys
import os
import sqlite3
import random
from datetime import datetime, timedelta
import hashlib
import json

# Add src to path to import core modules if needed, but we'll use direct SQL for simplicity ensuring speed
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

DB_PATH = "database/glove_test.db"

def create_connection():
    """Create database connection"""
    try:
        conn = sqlite3.connect(DB_PATH)
        return conn
    except Exception as e:
        print(f"Error connecting to database: {e}")
        return None

def generate_data():
    """Generate dummy data"""
    conn = create_connection()
    if not conn:
        return

    cursor = conn.cursor()
    
    print("Generating dummy data...")

    # 1. Generate Users (if not exist)
    # We assume 'admin' exists. Let's add an operator.
    # Password hash for 'Operator123!' (just a placeholder hash for demo)
    dummy_hash = b'$2b$12$K.X.X.X.X.X.X.X.X.X.X.X' 
    
    users = [
        ('operator1', dummy_hash, 'Operator One', 'Operator', 'op1@example.com', datetime.now(), 0, None),
        ('viewer1', dummy_hash, 'Viewer One', 'Viewer', 'view1@example.com', datetime.now(), 0, None)
    ]
    
    for user in users:
        try:
            cursor.execute('''
                INSERT INTO users (username, password_hash, full_name, role, email, created_at, failed_login_attempts, locked_until)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', user)
        except sqlite3.IntegrityError:
            pass # User already exists

    # 2. Generate Test Records
    glove_types = ['Nitrile', 'Latex', 'Vinyl', 'Neoprene']
    batch_prefixes = ['BATCH-A', 'BATCH-B', 'BATCH-C']
    
    # Generate records for the last 30 days
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)
    
    # Get user IDs
    cursor.execute("SELECT id, username FROM users")
    user_map = {row[1]: row[0] for row in cursor.fetchall()}
    admin_id = user_map.get('admin', 1)
    op1_id = user_map.get('operator1', admin_id)

    records_created = 0
    
    current_date = start_date
    while current_date <= end_date:
        # Generate 2-5 tests per day
        daily_tests = random.randint(2, 5)
        
        for _ in range(daily_tests):
            test_time = current_date + timedelta(hours=random.randint(8, 17), minutes=random.randint(0, 59))
            
            glove_type = random.choice(glove_types)
            batch_no = f"{random.choice(batch_prefixes)}-{random.randint(100, 999)}"
            
            # 80% pass rate
            passed = random.random() > 0.2
            
            target_pressure = 50.0
            duration = 300
            
            if passed:
                start_pressure = target_pressure + random.uniform(-0.5, 0.5)
                end_pressure = start_pressure - random.uniform(0.1, 1.0) # Small drop
                result = "PASS"
            else:
                start_pressure = target_pressure + random.uniform(-0.5, 0.5)
                end_pressure = start_pressure - random.uniform(5.0, 15.0) # Large drop
                result = "FAIL"
            
            temp_avg = 24.0 + random.uniform(-1.0, 1.0)
            
            # Create data hash
            data_str = f"{batch_no}{glove_type}{result}{test_time.isoformat()}"
            data_hash = hashlib.sha256(data_str.encode()).hexdigest()
            
            operator_id = random.choice([admin_id, op1_id])
            
            # Create unique test_id
            test_id = f"T-{test_time.strftime('%Y%m%d')}-{random.randint(1000, 9999)}"
            
            # Create JSON data for measurements
            data_json = json.dumps({
                "start_pressure": start_pressure,
                "end_pressure": end_pressure,
                "temperature_avg": temp_avg,
                "pressure_data": [start_pressure - (i*0.1) for i in range(10)], # Fake chart data
                "temperature_data": [temp_avg + (random.uniform(-0.1, 0.1)) for i in range(10)]
            })
            
            cursor.execute('''
                INSERT INTO test_records (
                    test_id, glove_batch_number, glove_type, target_pressure, target_temperature, test_duration,
                    test_result,
                    test_start_time, operator_id, data_hash, created_at, test_status, data_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                test_id,
                batch_no, glove_type, target_pressure, 25.0, duration,
                result,
                test_time.isoformat(), operator_id, data_hash, test_time.isoformat(), "COMPLETED", data_json
            ))
            records_created += 1
            
            # Log to audit trail
            cursor.execute('''
            INSERT INTO audit_trail (timestamp, username, action_type, description)
            VALUES (?, ?, ?, ?)
            ''', (
                test_time, 
                "admin" if operator_id == admin_id else "operator1",
                "TEST_COMPLETED",
                f"Test completed for Batch {batch_no} - Result: {result}"
            ))
            
        current_date += timedelta(days=1)

    conn.commit()
    print(f"Successfully generated {records_created} test records.")
    
    # Verify count
    cursor.execute("SELECT COUNT(*) FROM test_records")
    count = cursor.fetchone()[0]
    print(f"Total records in database: {count}")
    
    conn.close()

if __name__ == "__main__":
    generate_data()

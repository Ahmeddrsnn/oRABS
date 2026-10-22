"""
Test Data Hash Verification Tool
Validates PDF report integrity by comparing hash values
"""

import sys
import os
import hashlib
import json

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from core.database import Database


def calculate_test_hash(test_data):
    """Calculate SHA-256 hash of test data"""
    # Only include fields that were used in original hash
    data_for_hash = {
        'test_id': test_data.get('test_id'),
        'operator_id': test_data.get('operator_id'),
        'glove_batch_number': test_data.get('glove_batch_number'),
        'glove_type': test_data.get('glove_type'),
        'test_start_time': test_data.get('test_start_time'),
        'test_end_time': test_data.get('test_end_time'),
        'target_pressure': test_data.get('target_pressure'),
        'target_temperature': test_data.get('target_temperature'),
        'test_duration': test_data.get('test_duration'),
        'test_status': test_data.get('test_status'),
        'test_result': test_data.get('test_result'),
        'data_json': test_data.get('data_json')
    }
    
    # Convert to JSON string (sorted keys for consistency)
    data_str = json.dumps(data_for_hash, sort_keys=True, ensure_ascii=False)
    
    # Calculate SHA-256
    hash_object = hashlib.sha256(data_str.encode('utf-8'))
    return hash_object.hexdigest()


def verify_test_by_id(test_id, expected_hash=None):
    """
    Verify a test record by its ID
    
    Args:
        test_id: Test ID to verify
        expected_hash: Hash from PDF (optional, will use DB if not provided)
    
    Returns:
        bool: True if verified, False if mismatch
    """
    db = Database("database/glove_test.db")
    
    try:
        # Get test record from database
        conn = db.connect()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM test_records WHERE test_id = ?', (test_id,))
        row = cursor.fetchone()
        
        if not row:
            print(f"[X] Test ID '{test_id}' not found in database")
            return False
        
        # Convert to dict
        test_data = dict(row)
        
        # Get stored hash from database
        stored_hash = test_data.get('data_hash', '')
        
        # Calculate current hash
        calculated_hash = calculate_test_hash(test_data)
        
        # If expected_hash provided (from PDF), use that
        # Otherwise use the one stored in database
        hash_to_verify = expected_hash if expected_hash else stored_hash
        
        print("=" * 70)
        print(f" HASH VERIFICATION REPORT")
        print("=" * 70)
        print(f"Test ID: {test_id}")
        print(f"Glove Batch: {test_data.get('glove_batch_number')}")
        print(f"Test Result: {test_data.get('test_result')}")
        print(f"Test Date: {test_data.get('test_start_time')}")
        print("-" * 70)
        
        if expected_hash:
            print(f"Hash from PDF:    {expected_hash}")
        print(f"Hash from DB:     {stored_hash}")
        print(f"Calculated Hash:  {calculated_hash}")
        print("-" * 70)
        
        # Verify
        if calculated_hash == hash_to_verify:
            print("[OK] VERIFICATION SUCCESSFUL")
            print("   Data integrity confirmed - No tampering detected")
            print("   This record is valid and trustworthy")
            return True
        else:
            print("[FAIL] VERIFICATION FAILED")
            print("   WARNING: Data has been modified!")
            print("   This record may have been tampered with")
            print("   DO NOT trust this test result")
            return False
            
    finally:
        db.close()


def verify_all_tests():
    """Verify all test records in database"""
    db = Database("database/glove_test.db")
    
    try:
        conn = db.connect()
        cursor = conn.cursor()
        cursor.execute('SELECT test_id, data_hash FROM test_records')
        rows = cursor.fetchall()
        
        if not rows:
            print("No test records found in database")
            return
        
        print("=" * 70)
        print(f" VERIFYING {len(rows)} TEST RECORDS")
        print("=" * 70)
        
        verified = 0
        failed = 0
        
        for row in rows:
            test_id = row['test_id']
            stored_hash = row['data_hash']
            
            # Get full record
            cursor.execute('SELECT * FROM test_records WHERE test_id = ?', (test_id,))
            test_data = dict(cursor.fetchone())
            
            # Calculate hash
            calculated_hash = calculate_test_hash(test_data)
            
            # Compare
            if calculated_hash == stored_hash:
                print(f"[OK] {test_id}: VERIFIED")
                verified += 1
            else:
                print(f"[FAIL] {test_id}: FAILED (hash mismatch)")
                failed += 1
        
        print("=" * 70)
        print(f"Total: {len(rows)} | Verified: {verified} | Failed: {failed}")
        
        if failed == 0:
            print("[OK] All test records verified successfully!")
        else:
            print(f"[WARNING] {failed} record(s) failed verification!")
        
    finally:
        db.close()


def interactive_verify():
    """Interactive verification tool"""
    print("=" * 70)
    print("TEST DATA HASH VERIFICATION TOOL")
    print("21 CFR Part 11 Data Integrity Validator")
    print("=" * 70)
    print()
    print("Options:")
    print("1. Verify specific test by ID")
    print("2. Verify test with PDF hash")
    print("3. Verify all tests in database")
    print("4. Exit")
    print()
    
    while True:
        choice = input("Select option (1-4): ").strip()
        
        if choice == '1':
            test_id = input("Enter Test ID: ").strip()
            if test_id:
                verify_test_by_id(test_id)
            print()
            
        elif choice == '2':
            test_id = input("Enter Test ID: ").strip()
            pdf_hash = input("Enter Hash from PDF: ").strip()
            if test_id and pdf_hash:
                verify_test_by_id(test_id, pdf_hash)
            print()
            
        elif choice == '3':
            verify_all_tests()
            print()
            
        elif choice == '4':
            print("Exiting...")
            break
        else:
            print("Invalid option. Please select 1-4.")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Command line usage
        test_id = sys.argv[1]
        pdf_hash = sys.argv[2] if len(sys.argv) > 2 else None
        verify_test_by_id(test_id, pdf_hash)
    else:
        # Interactive mode
        interactive_verify()

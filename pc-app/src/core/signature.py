"""
Electronic Signature Module
Implements 21 CFR Part 11 compliant electronic signatures
"""

from datetime import datetime
from typing import Optional, Dict, Any
import hashlib
import json


class SignatureManager:
    """Manages electronic signatures for records"""
    
    def __init__(self, database, auth_manager, audit_manager):
        self.db = database
        self.auth = auth_manager
        self.audit = audit_manager
    
    def create_signature(self, record_type: str, record_id: int, 
                        meaning: str, password: str) -> tuple[bool, str]:
        """
        Create electronic signature for a record
        
        21 CFR Part 11 Requirements:
        - Two components: user ID and password
        - Meaning of signature (e.g., "Reviewed by", "Approved by")
        - Cryptographic binding to signed data
        - Non-repudiation
        
        Args:
            record_type: Type of record (e.g., "test_record")
            record_id: ID of record being signed
            meaning: Meaning of signature
            password: User's password for verification
        
        Returns:
            (success, message)
        """
        if not self.auth.current_user:
            return False, "No user logged in"
        
        # Verify user's password (two-factor authentication)
        user = self.db.get_user_by_username(self.auth.current_user['username'])
        if not user:
            return False, "User not found in database"
        if not self.auth.verify_password(password, user['password_hash']):
            self.audit.log_action(
                'SIGNATURE_FAILED',
                description=f'Failed signature attempt for {record_type} ID {record_id}'
            )
            return False, "Invalid password"
        
        # Get record data and calculate hash
        data_hash = self._get_record_hash(record_type, record_id)
        if not data_hash:
            return False, "Record not found or hash calculation failed"
        
        # Create signature record
        try:
            sig_id = self.db.add_signature(
                record_type=record_type,
                record_id=record_id,
                user_id=user['id'],
                meaning=meaning,
                data_hash=data_hash
            )
            
            # Log signature in audit trail
            self.audit.log_signature(record_type, record_id, meaning)
            
            return True, f"Signature applied: {meaning}"
        
        except Exception as e:
            return False, f"Error creating signature: {str(e)}"
    
    def _get_record_hash(self, record_type: str, record_id: int) -> Optional[str]:
        """Calculate hash of record data for signature binding"""
        conn = self.db.connect()
        cursor = conn.cursor()
        
        try:
            if record_type == 'test_record':
                cursor.execute('SELECT * FROM test_records WHERE id = ?', (record_id,))
            else:
                return None
            
            row = cursor.fetchone()
            if not row:
                return None
            
            # Create hash of record data
            record_data = dict(row)
            data_str = json.dumps(record_data, sort_keys=True)
            data_hash = hashlib.sha256(data_str.encode('utf-8')).hexdigest()
            
            return data_hash
        
        finally:
            self.db.close()
    
    def verify_signature(self, signature_id: int) -> tuple[bool, str]:
        """
        Verify electronic signature integrity
        Ensures the signed data hasn't been modified
        """
        conn = self.db.connect()
        cursor = conn.cursor()
        
        try:
            cursor.execute('SELECT * FROM electronic_signatures WHERE id = ?', (signature_id,))
            sig_row = cursor.fetchone()
            
            if not sig_row:
                return False, "Signature not found"
            
            sig = dict(sig_row)
            
            # Recalculate hash of current record data
            current_hash = self._get_record_hash(sig['record_type'], sig['record_id'])
            
            if not current_hash:
                return False, "Cannot verify - record not found"
            
            # Compare hashes
            if current_hash == sig['signed_data_hash']:
                return True, "Signature valid - data integrity confirmed"
            else:
                return False, "WARNING: Data has been modified after signature was applied"
        
        finally:
            self.db.close()
    
    def get_signatures_for_record(self, record_type: str, record_id: int) -> list:
        """Get all signatures for a specific record"""
        conn = self.db.connect()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT es.*, u.full_name, u.username
            FROM electronic_signatures es
            JOIN users u ON es.user_id = u.id
            WHERE es.record_type = ? AND es.record_id = ?
            ORDER BY es.signature_timestamp DESC
        ''', (record_type, record_id))
        
        rows = cursor.fetchall()
        self.db.close()
        
        return [dict(row) for row in rows]
    
    def signature_required_for_action(self, action: str, role: str) -> bool:
        """
        Determine if electronic signature is required for an action
        
        Typical requirements:
        - Test approval/review
        - Data modification
        - Report finalization
        """
        signature_rules = {
            'TEST_APPROVE': ['Operator', 'Admin'],
            'TEST_REVIEW': ['Admin'],
            'DATA_MODIFY': ['Admin'],
            'REPORT_FINALIZE': ['Operator', 'Admin']
        }
        
        return role in signature_rules.get(action, [])

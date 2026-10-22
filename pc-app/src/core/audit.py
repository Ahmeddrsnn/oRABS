"""
Audit Trail Module
Provides comprehensive logging of all user actions and system events
"""

import inspect
from datetime import datetime
from typing import Optional, Dict, Any, List


# Module → category mapping prefixes used by _infer_category.
# Caller's __name__ is matched against these prefixes (longest-prefix wins
# implicitly because the list is checked in declared order).
_CATEGORY_RULES = (
    # USER scope: anything related to identity / access
    ('core.auth',             'USER'),
    ('gui.user_management',   'USER'),
    ('gui.login_dialog',      'USER'),
    ('gui.force_password',    'USER'),
    # ORAPS scope: any module starting with oraps_ in gui or core
    ('gui.oraps',             'ORAPS'),
    ('core.oraps',            'ORAPS'),
    # LAF scope: Laminar Air Flow monitoring (Faz-5)
    ('oraps.laf_panel',       'LAF'),
    ('core.laf_manager',      'LAF'),
    ('core.laf_worker',       'LAF'),
    # Weidmüller IO under ORAPS (Faz-6a)
    ('oraps.io_panel',         'ORAPS'),
    ('core.weidmuller_manager','ORAPS'),
    ('core.weidmuller_worker', 'ORAPS'),
    # GLT scope: all GLT panels and supporting core modules
    ('gui.esp_now',           'GLT'),
    ('gui.layout',            'GLT'),
    ('gui.batch_panel',       'GLT'),
    ('gui.recipe',            'GLT'),
    ('gui.report',            'GLT'),
    ('gui.log_panel',         'GLT'),
    ('gui.rfid',              'GLT'),
    ('gui.test_control',      'GLT'),
    ('gui.monitoring',        'GLT'),
    ('gui.device',            'GLT'),
    ('gui.port_',             'GLT'),
    ('core.signature',        'GLT'),
    ('core.esp32',            'GLT'),
    ('core.pdf',              'GLT'),
)


class AuditManager:
    """Manages audit trail logging for 21 CFR Part 11 compliance"""
    
    def __init__(self, database, auth_manager):
        self.db = database
        self.auth = auth_manager

    @staticmethod
    def _infer_category() -> str:
        """Walk the call stack to find the first caller outside this module
        and map its module name to a category.

        Default: 'SYSTEM' (covers main_window shutdown, untagged callers, etc).
        """
        try:
            stack = inspect.stack()
            # Skip frames inside this audit module itself
            for frame_info in stack[1:]:
                mod_name = frame_info.frame.f_globals.get('__name__', '')
                if mod_name.startswith('core.audit'):
                    continue
                for prefix, category in _CATEGORY_RULES:
                    if mod_name.startswith(prefix):
                        return category
                # First non-audit caller found, no rule matched
                return 'SYSTEM'
        except Exception:
            pass
        return 'SYSTEM'
    
    def log_action(self, action_type: str, table_name: Optional[str] = None,
                   record_id: Optional[int] = None, field_name: Optional[str] = None,
                   old_value: Optional[str] = None, new_value: Optional[str] = None,
                   description: str = "", category: Optional[str] = None):
        """
        Log user action to audit trail
        
        Args:
            action_type: Type of action (LOGIN, LOGOUT, CREATE, MODIFY, DELETE, etc.)
            table_name: Database table affected
            record_id: ID of record affected
            field_name: Field that was modified
            old_value: Previous value
            new_value: New value
            description: Description of action
            category: 'USER' | 'GLT' | 'ORAPS' | 'SYSTEM'. If None, auto-detected
                      from the caller's module name.
        """
        if category is None:
            category = self._infer_category()

        # Faz-13: alarm kodu kataloğu — tanımlı action_type'ların
        # açıklamasına `[KP-01]` biçiminde kod eklenir (tek merkezden).
        try:
            from core.alarm_codes import prefix_description
            description = prefix_description(action_type, description)
        except Exception:
            pass

        user_id = None
        username = "SYSTEM"

        if self.auth.current_user:
            user_id = self.auth.current_user['id']
            username = self.auth.current_user['username']

        # Plan B (2026-06-16): single-shot lock-protected INSERT via Database.
        # Previously this method opened/closed the shared connection itself,
        # which raced with concurrent callers once the DB became thread-safe.
        self.db.add_audit_entry(
            timestamp=datetime.now().isoformat(),
            user_id=user_id,
            username=username,
            action_type=action_type,
            table_name=table_name,
            record_id=record_id,
            field_name=field_name,
            old_value=old_value,
            new_value=new_value,
            description=description,
            category=category,
        )
    
    def log_test_action(self, action: str, test_id: str, details: str = ""):
        """Log test-related action"""
        self.log_action(
            action_type=f"TEST_{action}",
            table_name="test_records",
            description=f"Test {test_id}: {details}"
        )
    
    def log_data_modification(self, table: str, record_id: int, 
                            field: str, old_val: Any, new_val: Any):
        """Log data modification with before/after values"""
        self.log_action(
            action_type="DATA_MODIFY",
            table_name=table,
            record_id=record_id,
            field_name=field,
            old_value=str(old_val),
            new_value=str(new_val),
            description=f"Modified {field} in {table}"
        )
    
    def log_signature(self, record_type: str, record_id: int, meaning: str):
        """Log electronic signature"""
        self.log_action(
            action_type="SIGNATURE",
            table_name=record_type,
            record_id=record_id,
            description=f"Electronic signature: {meaning}"
        )
    
    def log_system_event(self, event_type: str, severity: str, 
                        message: str, details: str = ""):
        """Log system event"""
        # Plan B: delegate to thread-safe Database writer.
        self.db.add_system_event(
            timestamp=datetime.now().isoformat(),
            event_type=event_type,
            severity=severity,
            message=message,
            details=details,
        )
    
    def get_audit_trail(self, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Retrieve audit trail with optional filtering
        
        Args:
            filters: Optional dict with keys: user_id, action_type, date_from, date_to,
                     table_name, categories (list of str)
        """
        query = 'SELECT * FROM audit_trail'
        params: List[Any] = []
        
        if filters:
            conditions = []
            
            if 'user_id' in filters:
                conditions.append('user_id = ?')
                params.append(filters['user_id'])
            
            if 'action_type' in filters:
                conditions.append('action_type = ?')
                params.append(filters['action_type'])
            
            if 'date_from' in filters:
                conditions.append('timestamp >= ?')
                params.append(filters['date_from'])
            
            if 'date_to' in filters:
                conditions.append('timestamp <= ?')
                params.append(filters['date_to'])
            
            if 'table_name' in filters:
                conditions.append('table_name = ?')
                params.append(filters['table_name'])
            
            if 'categories' in filters and filters['categories']:
                cats = filters['categories']
                placeholders = ','.join(['?'] * len(cats))
                conditions.append(f'category IN ({placeholders})')
                params.extend(cats)
            
            if conditions:
                query += ' WHERE ' + ' AND '.join(conditions)
        
        query += ' ORDER BY timestamp DESC'
        
        # Plan B: SELECT runs inside the shared DB lock via query_audit_trail.
        return self.db.query_audit_trail(query, tuple(params))
    
    def get_record_history(self, table_name: str, record_id: int) -> List[Dict[str, Any]]:
        """Get complete audit history for a specific record"""
        return self.get_audit_trail({
            'table_name': table_name,
            'record_id': record_id
        })

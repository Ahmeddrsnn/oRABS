"""
Authentication and authorization module
Implements user login, password management, and role-based access control
"""

import bcrypt
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import re


class AuthManager:
    """Manages user authentication and authorization"""
    
    def __init__(self, database):
        self.db = database
        self.audit = None # Will be set by set_audit_manager
        self.current_user = None
        self.session_start = None
        self.password_policy = {
            'min_length': 8,
            'require_uppercase': True,
            'require_lowercase': True,
            'require_digit': True,
            'require_special': True
        }
    
    def validate_password_policy(self, password: str) -> tuple[bool, str]:
        """Validate password against policy"""
        if len(password) < self.password_policy['min_length']:
            return False, f"Password must be at least {self.password_policy['min_length']} characters"
        
        if self.password_policy['require_uppercase'] and not re.search(r'[A-Z]', password):
            return False, "Password must contain at least one uppercase letter"
        
        if self.password_policy['require_lowercase'] and not re.search(r'[a-z]', password):
            return False, "Password must contain at least one lowercase letter"
        
        if self.password_policy['require_digit'] and not re.search(r'\d', password):
            return False, "Password must contain at least one digit"
        
        if self.password_policy['require_special'] and not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
            return False, "Password must contain at least one special character"
        
        return True, "Password meets policy requirements"
    
    def hash_password(self, password: str) -> str:
        """Hash password using bcrypt"""
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    def verify_password(self, password: str, password_hash: str) -> bool:
        """Verify password against hash"""
        return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))
    
    def is_account_locked(self, user: Dict[str, Any]) -> bool:
        """Check if account is locked due to failed login attempts"""
        if not user.get('locked_until'):
            return False
        
        locked_until = datetime.fromisoformat(user['locked_until'])
        return datetime.now() < locked_until
    
    def set_audit_manager(self, audit_manager):
        """Inject audit manager to avoid circular dependency in main.py"""
        self.audit = audit_manager
    
    def login(self, username: str, password: str) -> tuple[bool, str, Optional[Dict]]:
        """
        Authenticate user
        Returns: (success, message, user_data)
        """
        user = self.db.get_user_by_username(username)
        
        if not user:
            if self.audit:
                self.audit.log_action('LOGIN_FAILED', description=f'User {username} not found')
            return False, "Invalid username or password", None
        
        if not user['is_active']:
            if self.audit:
                self.audit.log_action('LOGIN_FAILED', description=f'Account {username} is inactive')
            return False, "Hesabınız pasif durumda.\nLütfen yöneticinize danışın.", None
        
        if self.is_account_locked(user):
            locked_until = datetime.fromisoformat(user['locked_until'])
            minutes_remaining = int((locked_until - datetime.now()).total_seconds() / 60)
            if self.audit:
                self.audit.log_action('LOGIN_FAILED', description=f'Account {username} is locked')
            return False, f"Account is locked. Try again in {minutes_remaining} minutes.", None
        
        if not self.verify_password(password, user['password_hash']):
            failed_count = user['failed_login_attempts'] + 1
            self._handle_failed_login(user)
            if self.audit:
                self.audit.log_action('LOGIN_FAILED', description=f'Invalid password for {username} (attempt {failed_count})')
            if failed_count >= 3 and user['role'] != 'Admin':
                return False, "3 başarısız giriş denemesi!\nHesabınız pasif duruma alındı.\nLütfen yöneticinize danışın.", None
            remaining = 3 - failed_count
            return False, f"Yanlış şifre. Kalan deneme hakkı: {remaining}", None
        
        # Successful login
        self._reset_failed_attempts(user)
        # Periyodik şifre değiştirme kontrolü: password_changed_at üzerinden
        # geçen süre ayardaki ay sayısını aştıysa `must_change_password=1`
        # yaz ve user dict'e yansıt. main.py / main_window.py flow'u bu
        # bayrağı görüp ForcePasswordChangeDialog gösterir.
        try:
            if self._is_password_expired(user):
                self._mark_password_expired(user['id'])
                user['must_change_password'] = 1
        except Exception:
            pass
        self.current_user = user
        self.session_start = datetime.now()
        
        if self.audit:
            self.audit.log_action('LOGIN_SUCCESS', description='User logged in successfully')
        
        return True, "Login successful", user
    
    def _handle_failed_login(self, user: Dict[str, Any]):
        """Handle failed login attempt - 3 başarısız deneme hesabı pasif yapar"""
        conn = self.db.connect()
        cursor = conn.cursor()
        
        failed_attempts = user['failed_login_attempts'] + 1
        
        if failed_attempts >= 3 and user['role'] != 'Admin':
            # 3 başarısız giriş → hesabı pasif yap (admin hariç)
            cursor.execute('''
                UPDATE users 
                SET failed_login_attempts = ?, is_active = 0
                WHERE id = ?
            ''', (failed_attempts, user['id']))
            conn.commit()
            self.db.close()
            if self.audit:
                self.audit.log_action('ACCOUNT_DEACTIVATED', 
                    description=f'Account {user["username"]} deactivated after {failed_attempts} failed attempts')
            return
        else:
            cursor.execute('''
                UPDATE users 
                SET failed_login_attempts = ?
                WHERE id = ?
            ''', (failed_attempts, user['id']))
        
        conn.commit()
        self.db.close()
    
    def _reset_failed_attempts(self, user: Dict[str, Any]):
        """Reset failed login attempts after successful login"""
        conn = self.db.connect()
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE users 
            SET failed_login_attempts = 0, locked_until = NULL
            WHERE id = ?
        ''', (user['id'],))
        
        conn.commit()
        self.db.close()

    # ── Periyodik şifre değiştirme kontrolü ─────────────────────
    def _password_interval_months(self) -> int:
        """system_settings.password_change_interval_months (3/6/9/12).
        Geçersiz/eksik değer → 3 ay (default)."""
        try:
            raw = str(self.db.get_setting(
                'password_change_interval_months', '3'
            )).strip()
        except Exception:
            return 3
        try:
            m = int(raw)
        except (TypeError, ValueError):
            return 3
        return m if m in (3, 6, 9, 12) else 3

    def _is_password_expired(self, user: Dict[str, Any]) -> bool:
        """User'ın `password_changed_at` alanı ayarlanan periyottan eski
        mi? Ay hesaplaması yaklaşık 30 gün üzerinden yapılır."""
        raw = user.get('password_changed_at') or user.get('created_at')
        if not raw:
            return False
        try:
            changed = datetime.fromisoformat(str(raw))
        except (TypeError, ValueError):
            return False
        months = self._password_interval_months()
        limit = timedelta(days=int(months) * 30)
        return (datetime.now() - changed) >= limit

    def _mark_password_expired(self, user_id: int):
        """DB'de must_change_password=1 setle. audit log da düş."""
        conn = self.db.connect()
        cursor = conn.cursor()
        try:
            cursor.execute(
                'UPDATE users SET must_change_password = 1 WHERE id = ?',
                (int(user_id),)
            )
            conn.commit()
        finally:
            self.db.close()
        if self.audit:
            try:
                self.audit.log_action(
                    'PASSWORD_EXPIRED',
                    description=(
                        'Şifre süresi doldu; kullanıcıdan yeni şifre isteniyor.'
                    ),
                )
            except Exception:
                pass
    
    def logout(self):
        """Log out current user"""
        if self.current_user and self.audit:
            self.audit.log_action(
                'LOGOUT',
                description='User logged out'
            )
        
        self.current_user = None
        self.session_start = None
    
    # Role hierarchy: Admin > Supervisor > Operator (Viewer is implicit 0)
    ROLE_HIERARCHY = {'Admin': 3, 'Supervisor': 2, 'Operator': 1}

    def has_permission(self, required_role: str) -> bool:
        """
        Check if current user has required permission.
        Role hierarchy: Admin > Supervisor > Operator > Viewer
        """
        if not self.current_user:
            return False

        user_level = self.ROLE_HIERARCHY.get(self.current_user['role'], 0)
        required_level = self.ROLE_HIERARCHY.get(required_role, 0)

        return user_level >= required_level

    def is_admin(self) -> bool:
        """True only if currently logged in user is Admin."""
        return bool(self.current_user) and self.current_user.get('role') == 'Admin'

    def is_supervisor_or_above(self) -> bool:
        """True if Admin or Supervisor."""
        return self.has_permission('Supervisor')

    def is_operator_or_above(self) -> bool:
        """True if Admin, Supervisor or Operator."""
        return self.has_permission('Operator')
    
    def create_user(self, username: str, password: str, full_name: str, 
                   role: str, email: Optional[str] = None) -> tuple[bool, str]:
        """Create new user (Admin only)"""
        if not self.has_permission('Admin'):
            return False, "Insufficient permissions"
        
        # Validate password
        valid, message = self.validate_password_policy(password)
        if not valid:
            return False, message
        
        # Check if username already exists
        existing = self.db.get_user_by_username(username)
        if existing:
            return False, "Username already exists"
        
        # Create user
        conn = self.db.connect()
        cursor = conn.cursor()
        
        password_hash = self.hash_password(password)
        
        try:
            cursor.execute('''
                INSERT INTO users 
                (username, password_hash, full_name, role, email, created_at, created_by,
                 password_changed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (username, password_hash, full_name, role, email,
                  datetime.now().isoformat(), self.current_user['username'],
                  datetime.now().isoformat()))
            
            conn.commit()
            
            if self.audit:
                self.audit.log_action(
                    'USER_CREATED',
                    description=f'Created user: {username}'
                )
            
            return True, "User created successfully"
        
        except Exception as e:
            return False, f"Error creating user: {str(e)}"
        
        finally:
            self.db.close()
    
    def get_current_user_role(self) -> str:
        """Get role of currently logged in user"""
        if self.current_user:
            return self.current_user.get('role', 'Visitor')
        return 'Visitor'

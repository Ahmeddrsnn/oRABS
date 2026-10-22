# Glove Test Control System

## 21 CFR Part 11 Compliant PC Software for Glove Testing Devices

A comprehensive Windows application for controlling glove testing devices via ESP32 communication, with full compliance to 21 CFR Part 11 regulations.

### Features

#### Core Functionality
- **ESP32 Communication**: Serial communication with ESP32-based test devices
- **Real-Time Monitoring**: Live pressure, temperature, and leak detection monitoring
- **Test Control**: Configure and execute glove integrity tests
- **Data Logging**: Automatic logging of all test data with timestamps
- **Report Generation**: PDF reports with electronic signatures

#### 21 CFR Part 11 Compliance
- **User Authentication**: Secure login with password policies
- **Role-Based Access Control**: Admin, Operator, and Viewer roles
- **Electronic Signatures**: Two-factor signatures with cryptographic binding
- **Audit Trails**: Complete logging of all user actions and system events
- **Data Integrity**: SHA-256 hashing for tamper detection
- **Account Security**: Failed login lockout, password complexity requirements

### Installation

1. **Install Python** (3.8 or higher)
   Download from https://www.python.org/downloads/

2. **Install Dependencies**
   ```powershell
   cd pc-app
   pip install -r requirements.txt
   ```

3. **Run Application**
   ```powershell
   python src/main.py
   ```

### Default Credentials

**First Login:**
- Username: `admin`
- Password: `Admin123!`

**IMPORTANT:** Change the default admin password immediately after first login.

### System Requirements

- **OS**: Windows 10/11
- **Python**: 3.8+
- **RAM**: 4GB minimum
- **Storage**: 500MB for application and data
- **COM Port**: Available serial port for ESP32 connection

### Project Structure

```
pc-app/
├── src/
│   ├── main.py                    # Application entry point
│   ├── core/                      # Core modules
│   │   ├── database.py            # SQLite database handler
│   │   ├── auth.py                # Authentication system
│   │   ├── audit.py               # Audit trail logging
│   │   ├── signature.py           # Electronic signatures
│   │   └── esp32_comm.py          # ESP32 communication
│   ├── gui/                       # GUI components
│   │   ├── main_window.py         # Main application window
│   │   ├── login_dialog.py        # Login interface
│   │   ├── test_control.py        # Test control panel
│   │   ├── monitoring_panel.py    # Real-time monitoring
│   │   └── report_viewer.py       # Reports and data
│   └── utils/                     # Utilities
│       └── pdf_generator.py       # PDF report generation
├── config/
│   └── settings.json              # Application settings
├── database/                      # SQLite database files
├── reports/                       # Generated PDF reports
└── logs/                          # Application logs
```

### Usage Guide

#### 1. Login
- Launch application
- Enter username and password
- System validates credentials and creates audit log entry

#### 2. Connect to ESP32 Device
- Go to "Test Control" tab
- Select COM port from dropdown
- Click "Connect"
- Wait for connection confirmation

#### 3. Run a Test
- Enter glove batch number
- Select glove type
- Set test parameters (pressure, temperature, duration)
- Click "Start Test"
- Monitor real-time data in "Real-Time Monitoring" tab

#### 4. View Results
- Go to "Reports & Data" tab
- Search for test records by ID or date range
- View detailed test information
- Generate PDF reports
- Apply electronic signatures

#### 5. Electronic Signatures
- Select a test record
- Click "Apply Electronic Signature"
- Enter signature meaning (e.g., "Reviewed by", "Approved by")
- Re-enter password for verification
- Signature is cryptographically bound to data

### ESP32 Communication Protocol

The system uses JSON-based serial communication with ESP32:

#### Commands Sent to ESP32:
```json
{"cmd": "START_TEST", "params": {"pressure": 50.0, "temperature": 25.0, "duration": 300}}
{"cmd": "STOP_TEST"}
{"cmd": "GET_STATUS"}
{"cmd": "SET_PARAMS", "params": {...}}
```

#### Expected Responses from ESP32:
```json
// Command Response
{"status": "OK", "message": "Test started"}

// Real-time Data
{"type": "data", "pressure": 50.5, "temperature": 25.3, "leak_detected": false, "timestamp": "..."}

// Status Update
{"type": "status", "status": "RUNNING", "timestamp": "..."}
```

### 21 CFR Part 11 Compliance Details

#### § 11.10 - Electronic Records
- ✅ System validation and access controls
- ✅ Audit trails for all operations
- ✅ Authority checks and permissions
- ✅ Data integrity verification (SHA-256)
- ✅ Secure, tamper-proof storage

#### § 11.50 - Electronic Signatures
- ✅ Unique user identification
- ✅ Password verification (two-factor)
- ✅ Signature meaning association
- ✅ Cryptographic data binding

#### § 11.70 - Signature Manifestations
- ✅ Signed data, signer name, date/time
- ✅ Meaning of signature displayed
- ✅ Included in all relevant records

### User Roles

1. **Admin**
   - Create/manage users
   - View all audit trails
   - Apply signatures
   - Full system access

2. **Operator**
   - Run tests
   - View test results
   - Generate reports
   - Apply signatures to own tests

3. **Viewer**
   - View test results
   - Generate reports (read-only)
   - No modification permissions

### Troubleshooting

**Cannot connect to ESP32:**
- Check COM port selection
- Verify ESP32 is powered on
- Ensure correct baud rate (115200)
- Check USB cable connection

**Login fails:**
- Verify username/password
- Check if account is locked (wait 15 minutes)
- Contact administrator for password reset

**PDF generation fails:**
- Check "reports" folder permissions
- Ensure sufficient disk space
- Verify ReportLab installation

### Data Backup

Regular backups of the database file are recommended:
```powershell
# Backup database
Copy-Item database\glove_test.db database\backups\glove_test_$(Get-Date -Format 'yyyyMMdd_HHmmss').db
```

### Security Best Practices

1. Change default admin password immediately
2. Use strong passwords (min 8 chars, mixed case, numbers, symbols)
3. Regularly review audit trails
4. Limit user permissions to necessary roles
5. Backup database regularly
6. Keep system updated

### Support

For technical support or compliance questions, refer to:
- 21 CFR Part 11 regulations
- Application documentation
- System administrator

### License

Proprietary software - All rights reserved

---

**Version:** 1.0.0  
**Last Updated:** 2026-01-26  
**Compliance:** 21 CFR Part 11

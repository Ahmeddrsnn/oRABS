"""
Test script for PDF graph generation
Creates a sample test report with visualization
"""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from core.database import Database
from utils.pdf_generator import PDFReportGenerator
from datetime import datetime
import json

def create_test_pdf():
    """Generate a test PDF with sample data and graphs"""
    
    # Initialize database and PDF generator
    db = Database("database/glove_test.db")
    pdf_gen = PDFReportGenerator(db, "reports")
    
    # Create sample test data with time series
    test_data = {
        'test_id': 'TEST_GRAPH_DEMO_001',
        'operator_id': 1,
        'glove_batch_number': 'BATCH-2024-001',
        'glove_type': 'Nitrile',
        'test_start_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'test_end_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'target_pressure': 500.0,
        'target_temperature': 25.0,
        'test_duration': 60,
        'test_status': 'COMPLETED',
        'test_result': 'PASS',
        'data_hash': 'abc123def456',
    }
    
    # Generate realistic time series data
    time_points = list(range(0, 61, 2))  # 0 to 60 seconds, every 2 seconds
    
    # Simulate pressure readings (starting at 0, ramping up to target, then stable)
    pressure_readings = []
    for t in time_points:
        if t < 10:  # Inflation phase
            pressure = t * 50  # Ramp up
        elif t < 20:  # Stabilization
            pressure = 500 - (20 - t) * 5
        else:  # Measurement phase
            pressure = 500 + (t % 3) * 2 - 2  # Small fluctuations around target
        pressure_readings.append(pressure)
    
    # Simulate temperature readings
    temperature_readings = []
    for t in time_points:
        temp = 24.0 + (t / 60) * 2 + (t % 5) * 0.2  # Gradual rise with small variations
        temperature_readings.append(round(temp, 1))
    
    # Create data_json with test measurements
    test_measurements = {
        'pressure_readings': pressure_readings,
        'temperature_readings': temperature_readings,
        'time_points': time_points,
        'final_pressure': pressure_readings[-1],
        'avg_pressure': sum(pressure_readings) / len(pressure_readings),
        'final_temperature': temperature_readings[-1],
        'avg_temperature': sum(temperature_readings) / len(temperature_readings),
        'recipe_id': 1
    }
    
    test_data['data_json'] = json.dumps(test_measurements)
    
    # Sample signatures
    signatures = [
        {
            'full_name': 'Test Operator',
            'signature_meaning': 'Test Performed By',
            'signature_timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        },
        {
            'full_name': 'Test Supervisor',
            'signature_meaning': 'Reviewed By',
            'signature_timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
    ]
    
    # Generate PDF
    print(">> Generating test PDF with graphs...")
    pdf_path = pdf_gen.generate_test_report(test_data, signatures, "Test Company Ltd.")
    
    print(f">> PDF generated successfully!")
    print(f">> Location: {pdf_path}")
    print(f"\n>> The PDF includes:")
    print(f"   - Test information")
    print(f"   - Test parameters")
    print(f"   - [GRAPH] PRESSURE vs TIME")
    print(f"   - [GRAPH] TEMPERATURE vs TIME")
    print(f"   - Electronic signatures")
    print(f"   - Data integrity hash")
    
    return pdf_path

def create_summary_test_pdf():
    """Generate a test PDF with summary graph (no time series)"""
    
    db = Database("database/glove_test.db")
    pdf_gen = PDFReportGenerator(db, "reports")
    
    # Create sample test data WITHOUT time series
    test_data = {
        'test_id': 'TEST_SUMMARY_DEMO_002',
        'operator_id': 1,
        'glove_batch_number': 'BATCH-2024-002',
        'glove_type': 'Latex',
        'test_start_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'test_end_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'target_pressure': 450.0,
        'target_temperature': 24.0,
        'test_duration': 30,
        'test_status': 'COMPLETED',
        'test_result': 'PASS',
        'data_hash': 'xyz789uvw012',
    }
    
    # Only summary data (no time series)
    test_measurements = {
        'final_pressure': 455.0,
        'avg_pressure': 452.0,
        'final_temperature': 24.8,
        'avg_temperature': 24.5
    }
    
    test_data['data_json'] = json.dumps(test_measurements)
    
    signatures = [
        {
            'full_name': 'Summary Test Operator',
            'signature_meaning': 'Test Performed By',
            'signature_timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
    ]
    
    print("\n>> Generating summary chart PDF...")
    pdf_path = pdf_gen.generate_test_report(test_data, signatures, "Test Company Ltd.")
    
    print(f">> PDF generated successfully!")
    print(f">> Location: {pdf_path}")
    print(f"\n>> The PDF includes:")
    print(f"   - Test information")
    print(f"   - Test parameters")
    print(f"   - [CHART] SUMMARY BAR CHART (Target vs Measured)")
    print(f"   - Electronic signatures")
    
    return pdf_path

if __name__ == "__main__":
    print("=" * 60)
    print("PDF GRAPH TEST - Generating Sample Reports")
    print("=" * 60)
    
    try:
        # Test 1: Time series graph
        path1 = create_test_pdf()
        
        # Test 2: Summary graph
        path2 = create_summary_test_pdf()
        
        print("\n" + "=" * 60)
        print(">> Both test PDFs generated successfully!")
        print("=" * 60)
        print("\nYou can now open the PDFs to see the graphs:")
        print(f"1. {path1}")
        print(f"2. {path2}")
        
    except Exception as e:
        print(f"\n>> Error: {e}")
        import traceback
        traceback.print_exc()

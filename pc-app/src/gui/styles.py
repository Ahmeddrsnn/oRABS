"""
UI Styles and Themes
Centralized CSS definitions for the application
"""

class Styles:
    # Colors
    PRIMARY = "#3B82F6"      # Blue
    PRIMARY_HOVER = "#2563EB"
    SECONDARY = "#6B7280"    # Gray
    SECONDARY_HOVER = "#4B5563"
    SUCCESS = "#10B981"      # Green
    DANGER = "#EF4444"       # Red
    WARNING = "#F59E0B"      # Amber
    SURFACE = "#FFFFFF"
    BACKGROUND = "#F3F4F6"
    TEXT = "#1F2937"
    BORDER = "#E5E7EB"

    @staticmethod
    def get_button_style(role="secondary"):
        """Get stylesheet for buttons based on role"""
        
        base_style = """
            QPushButton {
                border-radius: 6px;
                padding: 6px 12px;
                font-family: 'Segoe UI', sans-serif;
                font-size: 13px;
                font-weight: 500;
                border: 1px solid transparent;
            }
            QPushButton:disabled {
                background-color: #E5E7EB;
                color: #9CA3AF;
            }
        """
        
        if role == "primary":
            return base_style + f"""
                QPushButton {{
                    background-color: {Styles.PRIMARY};
                    color: white;
                }}
                QPushButton:hover {{
                    background-color: {Styles.PRIMARY_HOVER};
                }}
            """
        elif role == "success":
            return base_style + f"""
                QPushButton {{
                    background-color: {Styles.SUCCESS};
                    color: white;
                }}
                QPushButton:hover {{
                    background-color: #059669;
                }}
            """
        elif role == "danger":
            return base_style + f"""
                QPushButton {{
                    background-color: {Styles.DANGER};
                    color: white;
                }}
                QPushButton:hover {{
                    background-color: #DC2626;
                }}
            """
        else: # secondary/default
            return base_style + f"""
                QPushButton {{
                    background-color: {Styles.SURFACE};
                    border: 1px solid {Styles.BORDER};
                    color: {Styles.TEXT};
                }}
                QPushButton:hover {{
                    background-color: {Styles.BACKGROUND};
                    border-color: #D1D5DB;
                }}
            """
            
    GROUP_BOX = """
        QGroupBox {
            background-color: white;
            border: 1px solid #E5E7EB;
            border-radius: 8px;
            margin-top: 1ex;
            font-family: 'Segoe UI', sans-serif;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            padding: 0 5px;
            color: #374151;
            font-weight: bold;
        }
    """

    TABLE = """
        QTableWidget {
            border: 1px solid #E5E7EB;
            border-radius: 6px;
            gridline-color: #F3F4F6;
            background-color: white;
            font-family: 'Segoe UI', sans-serif;
        }
        QHeaderView::section {
            background-color: #F9FAFB;
            padding: 8px;
            border: none;
            border-bottom: 2px solid #E5E7EB;
            font-weight: 600;
            color: #4B5563;
        }
        QTableWidget::item:selected {
            background-color: #EFF6FF;
            color: #1E40AF;
        }
    """

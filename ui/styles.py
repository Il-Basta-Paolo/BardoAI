"""
Stili, palette colori e fogli di stile (QSS) moderni per l'interfaccia PySide6 di Bardo AI.
Autore: Paolo Basta (https://github.com/Il-Basta-Paolo/BardoAI)
"""

__author__ = "Paolo Basta"

DARK_THEME_QSS = """
/* Stile globale */
QWidget {
    background-color: #0b0f19;
    color: #f1f5f9;
    font-family: 'Segoe UI', 'Inter', -apple-system, sans-serif;
    font-size: 13px;
    selection-background-color: #3b82f6;
    selection-color: #ffffff;
}

/* Card e Container */
QFrame#card {
    background-color: #151c2c;
    border: 1px solid #1e293b;
    border-radius: 10px;
}

QFrame#surface {
    background-color: #111827;
    border: 1px solid #1f2937;
    border-radius: 8px;
}

/* Header e Titoli */
QLabel#headerTitle {
    font-size: 18px;
    font-weight: 700;
    color: #f8fafc;
    letter-spacing: 0.5px;
}

QLabel#sectionTitle {
    font-size: 14px;
    font-weight: 600;
    color: #94a3b8;
    text-transform: uppercase;
    letter-spacing: 1px;
}

QLabel#subtitle {
    font-size: 12px;
    color: #64748b;
}

/* Bottoni */
QPushButton {
    background-color: #1e293b;
    border: 1px solid #334155;
    border-radius: 6px;
    color: #f1f5f9;
    padding: 7px 14px;
    font-weight: 500;
}

QPushButton:hover {
    background-color: #334155;
    border-color: #475569;
}

QPushButton:pressed {
    background-color: #0f172a;
}

QPushButton#primaryBtn {
    background-color: #3b82f6;
    border: 1px solid #2563eb;
    color: #ffffff;
    font-weight: 600;
}

QPushButton#primaryBtn:hover {
    background-color: #2563eb;
}

QPushButton#dangerBtn {
    background-color: #dc2626;
    border: 1px solid #b91c1c;
    color: #ffffff;
}

QPushButton#dangerBtn:hover {
    background-color: #b91c1c;
}

QPushButton#lockBtn {
    background-color: #1e293b;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 6px 12px;
}

QPushButton#lockBtn:checked {
    background-color: #ea580c;
    border-color: #f97316;
    color: #ffffff;
    font-weight: 600;
}

/* Tab Bar */
QTabBar::tab {
    background: #111827;
    color: #94a3b8;
    border: 1px solid #1f2937;
    border-bottom: none;
    padding: 8px 16px;
    margin-right: 4px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    font-weight: 500;
}

QTabBar::tab:selected {
    background: #1e293b;
    color: #38bdf8;
    border-bottom: 2px solid #38bdf8;
}

QTabBar::tab:hover:!selected {
    background: #1f2937;
    color: #e2e8f0;
}

/* ComboBox */
QComboBox {
    background-color: #151c2c;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 6px 12px;
    color: #f8fafc;
    min-width: 140px;
}

QComboBox:hover {
    border-color: #475569;
}

QComboBox::drop-down {
    border: none;
    width: 24px;
}

QComboBox QAbstractItemView {
    background-color: #151c2c;
    border: 1px solid #334155;
    selection-background-color: #3b82f6;
    selection-color: #ffffff;
    padding: 4px;
}

/* Sliders */
QSlider::groove:horizontal {
    height: 6px;
    background: #1e293b;
    border-radius: 3px;
}

QSlider::sub-page:horizontal {
    background: #3b82f6;
    border-radius: 3px;
}

QSlider::handle:horizontal {
    background: #f8fafc;
    border: 2px solid #3b82f6;
    width: 14px;
    margin-top: -4px;
    margin-bottom: -4px;
    border-radius: 7px;
}

QSlider::handle:horizontal:hover {
    background: #60a5fa;
}

/* ScrollBar */
QScrollBar:vertical {
    background: #0b0f19;
    width: 8px;
    margin: 0;
    border-radius: 4px;
}

QScrollBar::handle:vertical {
    background: #334155;
    min-height: 24px;
    border-radius: 4px;
}

QScrollBar::handle:vertical:hover {
    background: #475569;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

/* LineEdit e TextEdit */
QLineEdit, QTextEdit {
    background-color: #151c2c;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 6px 10px;
    color: #f8fafc;
}

QLineEdit:focus, QTextEdit:focus {
    border-color: #3b82f6;
}

/* Tooltip */
QToolTip {
    background-color: #1e293b;
    color: #f8fafc;
    border: 1px solid #475569;
    border-radius: 4px;
    padding: 6px;
    font-size: 12px;
}
"""

"""
Отчёты.

Модули:
- report_generator: Генератор отчётов по статьям и системе
"""

from .report_generator import (
    PaperReport,
    SystemMetricsReport,
    ReportGenerator,
    generate_paper_report,
    generate_system_report,
)

__all__ = [
    "PaperReport",
    "SystemMetricsReport",
    "ReportGenerator",
    "generate_paper_report",
    "generate_system_report",
]

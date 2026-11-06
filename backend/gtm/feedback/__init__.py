"""Structured feedback capture (lost-deal review) and verified extraction. See README.md."""
from .service import (LOST_REASONS, INJECTION_RX, save_lost_deal_review, extract_feedback, feedback_summary, mock_feedback_extract,
                      register_mocks, build_graphs)

__all__ = ["LOST_REASONS", "INJECTION_RX", "save_lost_deal_review", "extract_feedback", "feedback_summary", "mock_feedback_extract",
           "register_mocks", "build_graphs"]

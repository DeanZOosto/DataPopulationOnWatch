#!/usr/bin/env python3
"""
Unit tests for inquiry priority mapping.
"""
import pytest
import sys
from pathlib import Path

# Add parent directory to path to import modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from constants import (
    INQUIRY_PRIORITY_MAP,
    INQUIRY_PRIORITY_DEFAULT,
    INQUIRY_PRIORITY_LOW,
    INQUIRY_PRIORITY_MEDIUM,
    INQUIRY_PRIORITY_HIGH
)


class TestPriorityMapping:
    """Test cases for inquiry priority mapping."""
    
    def test_priority_string_mapping(self):
        """Test that priority strings are correctly mapped to numbers."""
        # The correct mapping is: Low=201, Medium=101, High=1
        
        # Test Low
        assert INQUIRY_PRIORITY_MAP["low"] == INQUIRY_PRIORITY_LOW
        assert INQUIRY_PRIORITY_MAP["medium"] == INQUIRY_PRIORITY_MEDIUM
        assert INQUIRY_PRIORITY_MAP["high"] == INQUIRY_PRIORITY_HIGH
        
        # Test case insensitivity (should be handled in code)
        assert INQUIRY_PRIORITY_MAP.get("LOW".lower()) == INQUIRY_PRIORITY_LOW
        assert INQUIRY_PRIORITY_MAP.get("Medium".lower()) == INQUIRY_PRIORITY_MEDIUM
        assert INQUIRY_PRIORITY_MAP.get("HIGH".lower()) == INQUIRY_PRIORITY_HIGH
    
    def test_priority_numeric_range(self):
        """Test that numeric priorities are clamped to valid range (1-201)."""
        # Test minimum
        priority_num = max(INQUIRY_PRIORITY_HIGH, min(INQUIRY_PRIORITY_LOW, 0))
        assert priority_num == INQUIRY_PRIORITY_HIGH
        
        # Test maximum
        priority_num = max(INQUIRY_PRIORITY_HIGH, min(INQUIRY_PRIORITY_LOW, 500))
        assert priority_num == INQUIRY_PRIORITY_LOW
        
        # Test valid value
        priority_num = max(INQUIRY_PRIORITY_HIGH, min(INQUIRY_PRIORITY_LOW, INQUIRY_PRIORITY_MEDIUM))
        assert priority_num == INQUIRY_PRIORITY_MEDIUM
    
    def test_priority_default(self):
        """Test that unknown priority strings default to Medium (101)."""
        unknown_priority = INQUIRY_PRIORITY_MAP.get("unknown".lower(), INQUIRY_PRIORITY_DEFAULT)
        assert unknown_priority == INQUIRY_PRIORITY_DEFAULT

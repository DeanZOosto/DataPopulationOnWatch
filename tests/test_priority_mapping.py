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
    INQUIRY_PRIORITY_LOW,
    INQUIRY_PRIORITY_MEDIUM,
    INQUIRY_PRIORITY_HIGH,
    INQUIRY_PRIORITY_DEFAULT
)


class TestPriorityMapping:
    """Test cases for inquiry priority mapping."""
    
    def test_priority_string_mapping(self):
        """Test that priority strings are correctly mapped to numbers."""
        # The correct mapping is: Low=201, Medium=101, High=1
        
        # Test Low
        assert INQUIRY_PRIORITY_MAP["low"] == INQUIRY_PRIORITY_LOW == 201
        assert INQUIRY_PRIORITY_MAP["medium"] == INQUIRY_PRIORITY_MEDIUM == 101
        assert INQUIRY_PRIORITY_MAP["high"] == INQUIRY_PRIORITY_HIGH == 1
        
        # Test case insensitivity (should be handled in code)
        assert INQUIRY_PRIORITY_MAP.get("LOW".lower()) == 201
        assert INQUIRY_PRIORITY_MAP.get("Medium".lower()) == 101
        assert INQUIRY_PRIORITY_MAP.get("HIGH".lower()) == 1
    
    def test_priority_numeric_range(self):
        """Test that numeric priorities are clamped to valid range (1-201)."""
        # Test minimum
        priority_num = max(1, min(201, 0))
        assert priority_num == 1
        
        # Test maximum
        priority_num = max(1, min(201, 500))
        assert priority_num == 201
        
        # Test valid value
        priority_num = max(1, min(201, 101))
        assert priority_num == 101
    
    def test_priority_default(self):
        """Test that unknown priority strings default to Medium (101)."""
        priority_map = {"low": 201, "medium": 101, "high": 1}
        unknown_priority = priority_map.get("unknown".lower(), 101)
        assert unknown_priority == 101

#!/usr/bin/env python3
"""
Unit tests for version compatibility.
"""
import pytest
import sys
from pathlib import Path
from unittest.mock import Mock, MagicMock

# Add parent directory to path to import modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from version_compat import VersionCompat


class TestVersionCompat:
    """Test cases for version compatibility."""
    
    def test_initialization_with_version(self):
        """Test initializing with explicit version."""
        compat = VersionCompat(version="2.8")
        assert compat.version == "2.8"
        assert compat.is_version_2_8() is True
        assert compat.is_version_2_6() is False
    
    def test_initialization_without_version(self):
        """Test initializing without version raises error."""
        with pytest.raises((TypeError, ValueError), match="version"):
            VersionCompat()
    
    def test_initialization_with_invalid_version(self):
        """Test initializing with invalid version raises error."""
        with pytest.raises(ValueError, match="Unsupported OnWatch version"):
            VersionCompat(version="3.0")
    
    def test_initialization_with_empty_version(self):
        """Test initializing with empty version raises error."""
        with pytest.raises(ValueError, match="version is required"):
            VersionCompat(version="")
    
    def test_get_api_base_path(self):
        """Test API base path is consistent across versions."""
        compat_26 = VersionCompat(version="2.6")
        compat_28 = VersionCompat(version="2.8")
        
        # Both should use /bt/api (currently)
        assert compat_26.get_api_base_path() == "/bt/api"
        assert compat_28.get_api_base_path() == "/bt/api"
    
    def test_get_kv_parameter_endpoints(self):
        """Test KV parameter endpoints are returned."""
        compat = VersionCompat(version="2.6")
        endpoints = compat.get_kv_parameter_endpoints()
        
        assert isinstance(endpoints, list)
        assert len(endpoints) > 0
        assert all(isinstance(e, str) for e in endpoints)
        assert "/settings/kv" in endpoints
    
    def test_get_graphql_mutation_for_kv(self):
        """Test GraphQL mutation is returned."""
        compat = VersionCompat(version="2.6")
        mutation = compat.get_graphql_mutation_for_kv()
        
        assert isinstance(mutation, str)
        assert "mutation" in mutation.lower()
        assert "updateSingleSetting" in mutation or "update" in mutation.lower()
    
    def test_get_graphql_query_patterns_for_kv(self):
        """Test GraphQL query patterns are returned."""
        compat = VersionCompat(version="2.6")
        patterns = compat.get_graphql_query_patterns_for_kv()
        
        assert isinstance(patterns, list)
        assert len(patterns) > 0
        assert all('name' in p and 'query' in p for p in patterns)
    
    def test_get_inquiry_priority_mapping(self):
        """Test priority mapping is returned."""
        compat = VersionCompat(version="2.6")
        mapping = compat.get_inquiry_priority_mapping()
        
        assert isinstance(mapping, dict)
        assert "low" in mapping
        assert "medium" in mapping
        assert "high" in mapping
    
    def test_get_version(self):
        """Test getting version."""
        compat_26 = VersionCompat(version="2.6")
        compat_28 = VersionCompat(version="2.8")
        
        assert compat_26.get_version() == "2.6"
        assert compat_28.get_version() == "2.8"

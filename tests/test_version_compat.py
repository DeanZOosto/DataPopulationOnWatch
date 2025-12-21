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
        """Test initializing without version (auto-detect)."""
        compat = VersionCompat()
        assert compat.version is None
        # Should default to 2.6 when no client_api provided
        assert compat.get_version() == "2.6"
    
    def test_version_parsing(self):
        """Test version string parsing."""
        compat = VersionCompat()
        
        # Test various version string formats
        assert compat._parse_version("2.6.0") == "2.6"
        assert compat._parse_version("2.8.1") == "2.8"
        assert compat._parse_version("v2.6") == "2.6"
        assert compat._parse_version("OnWatch 2.8.0") == "2.8"
        assert compat._parse_version("invalid") is None
        assert compat._parse_version("3.0") is None  # Not supported
    
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
    
    def test_version_detection_with_mock(self):
        """Test version detection with mocked API."""
        compat = VersionCompat()
        
        # Create mock client_api
        mock_client = Mock()
        mock_client.session = Mock()
        mock_client.url = "https://10.1.1.1/bt/api"
        mock_client.headers = {}
        
        # Mock successful version detection
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"version": "2.8.0"}
        mock_client.session.get.return_value = mock_response
        
        detected = compat.detect_version(mock_client)
        assert detected == "2.8"
    
    def test_version_detection_fallback(self):
        """Test version detection falls back to default."""
        compat = VersionCompat()
        
        # Create mock client_api that fails detection
        mock_client = Mock()
        mock_client.session = Mock()
        mock_client.url = "https://10.1.1.1/bt/api"
        mock_client.headers = {}
        
        # Mock failed detection
        mock_client.session.get.side_effect = Exception("Connection failed")
        
        detected = compat.detect_version(mock_client)
        # Should default to 2.6
        assert detected == "2.6"

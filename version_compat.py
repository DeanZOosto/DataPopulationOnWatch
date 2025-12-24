#!/usr/bin/env python3
"""
Version compatibility layer for OnWatch 2.6 and 2.8.

Provides version-specific API endpoints, GraphQL queries, and behavior differences.
Version must be manually specified in config.yaml.
"""
import logging
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)


class VersionCompat:
    """Handles version compatibility between OnWatch 2.6 and 2.8."""
    
    # Supported versions
    VERSION_2_6 = "2.6"
    VERSION_2_8 = "2.8"
    SUPPORTED_VERSIONS = [VERSION_2_6, VERSION_2_8]
    
    def __init__(self, version: str):
        """
        Initialize version compatibility.
        
        Args:
            version: OnWatch version ("2.6" or "2.8"). Required.
            
        Raises:
            ValueError: If version is not provided or not supported.
        """
        if not version:
            raise ValueError("OnWatch version is required. Set 'onwatch.version' in config.yaml (e.g., '2.6' or '2.8')")
        
        if version not in self.SUPPORTED_VERSIONS:
            raise ValueError(f"Unsupported OnWatch version: {version}. Supported versions: {', '.join(self.SUPPORTED_VERSIONS)}")
        
        self.version = version
    
    def get_version(self) -> str:
        """
        Get OnWatch version.
        
        Returns:
            Version string ("2.6" or "2.8")
        """
        return self.version
    
    def is_version_2_8(self) -> bool:
        """Check if version is 2.8."""
        return self.version == self.VERSION_2_8
    
    def is_version_2_6(self) -> bool:
        """Check if version is 2.6."""
        return self.version == self.VERSION_2_6
    
    def get_api_base_path(self) -> str:
        """
        Get API base path (may differ between versions).
        
        Returns:
            API base path (e.g., "/bt/api" for both versions currently)
        """
        # Both 2.6 and 2.8 use /bt/api currently
        # This can be extended if 2.8 changes the path
        return "/bt/api"
    
    def get_kv_parameter_endpoints(self) -> List[str]:
        """
        Get list of KV parameter REST endpoints to try (in order).
        
        Returns:
            List of endpoint paths (relative to base URL)
        """
        # Both versions use similar endpoints, but order might matter
        if self.is_version_2_8():
            # 2.8 might prefer different endpoints
            return [
                "/settings/kv",
                "/key-value-settings",
                "/settings/key-value",
                "/kv-parameters",
            ]
        else:
            # 2.6 default order
            return [
                "/settings/kv",
                "/key-value-settings",
                "/kv-parameters",
                "/settings/key-value",
            ]
    
    def get_graphql_mutation_for_kv(self) -> str:
        """
        Get GraphQL mutation for setting KV parameters.
        
        Returns:
            GraphQL mutation string
        """
        # Both versions use the same mutation currently
        # This can be version-specific if needed
        return """
        mutation updateSingleSetting($key: String!, $value: String!) {
          updateSingleSetting(key: $key, value: $value) {
            key
            value
          }
        }
        """
    
    def get_graphql_query_patterns_for_kv(self) -> List[Dict[str, str]]:
        """
        Get list of GraphQL query patterns to try for reading KV parameters.
        
        Returns:
            List of dicts with 'name' and 'query' keys
        """
        # Both versions support similar queries, but some patterns might work better
        patterns = [
            {
                "name": "settings.keyValueSettings",
                "query": """
                query {
                  settings {
                    keyValueSettings {
                      key
                      value
                    }
                  }
                }
                """
            },
            {
                "name": "direct keyValueSettings",
                "query": """
                query {
                  keyValueSettings {
                    key
                    value
                  }
                }
                """
            },
            {
                "name": "getSingleSetting",
                "query": """
                query getSingleSetting($key: String!) {
                  getSingleSetting(key: $key) {
                    key
                    value
                  }
                }
                """
            }
        ]
        
        # Version 2.8 might prefer different order
        if self.is_version_2_8():
            # Reorder if needed
            pass
        
        return patterns
    
    def get_inquiry_priority_mapping(self) -> Dict[str, int]:
        """
        Get priority mapping for inquiry cases (may differ between versions).
        
        Returns:
            Dict mapping priority strings to numeric values
        """
        # Both versions use the same mapping currently
        # This can be version-specific if needed
        from constants import INQUIRY_PRIORITY_MAP
        return INQUIRY_PRIORITY_MAP
    
    def should_use_alternative_endpoint(self, endpoint_name: str) -> bool:
        """
        Check if an alternative endpoint should be used for this version.
        
        Args:
            endpoint_name: Name of the endpoint/feature
            
        Returns:
            True if alternative endpoint should be used
        """
        # Add version-specific endpoint logic here as needed
        # For now, both versions use the same endpoints
        return False
    
    def get_alternative_endpoint(self, endpoint_name: str) -> Optional[str]:
        """
        Get alternative endpoint path for this version.
        
        Args:
            endpoint_name: Name of the endpoint/feature
            
        Returns:
            Alternative endpoint path or None if not applicable
        """
        # Add version-specific endpoint mappings here as needed
        return None

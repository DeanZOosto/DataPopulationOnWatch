#!/usr/bin/env python3
"""
Version compatibility layer for OnWatch 2.6 and 2.8.

Handles version detection and provides version-specific API endpoints,
GraphQL queries, and behavior differences.
"""
import logging
import re
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)


class VersionCompat:
    """Handles version compatibility between OnWatch 2.6 and 2.8."""
    
    # Supported versions
    VERSION_2_6 = "2.6"
    VERSION_2_8 = "2.8"
    SUPPORTED_VERSIONS = [VERSION_2_6, VERSION_2_8]
    
    def __init__(self, version: Optional[str] = None):
        """
        Initialize version compatibility.
        
        Args:
            version: OnWatch version ("2.6" or "2.8"). If None, will auto-detect.
        """
        self.version = version
        self._detected_version = None
    
    def detect_version(self, client_api) -> str:
        """
        Attempt to detect OnWatch version from API.
        
        Args:
            client_api: ClientApi instance (must be logged in)
            
        Returns:
            Detected version string ("2.6" or "2.8")
        """
        if self._detected_version:
            return self._detected_version
        
        # Try to detect from system settings or API info endpoint
        try:
            # Try /api/info or /bt/api/info endpoint (if available)
            try:
                response = client_api.session.get(
                    f"{client_api.url}/info",
                    headers=client_api.headers
                )
                if response.status_code == 200:
                    data = response.json()
                    version_str = data.get('version', '')
                    if version_str:
                        detected = self._parse_version(version_str)
                        if detected:
                            self._detected_version = detected
                            logger.info(f"Detected OnWatch version: {detected}")
                            return detected
            except Exception:
                pass
            
            # Try /api/system/info or similar
            try:
                response = client_api.session.get(
                    f"{client_api.url}/system/info",
                    headers=client_api.headers
                )
                if response.status_code == 200:
                    data = response.json()
                    version_str = data.get('version', '') or data.get('systemVersion', '')
                    if version_str:
                        detected = self._parse_version(version_str)
                        if detected:
                            self._detected_version = detected
                            logger.info(f"Detected OnWatch version: {detected}")
                            return detected
            except Exception:
                pass
            
            # Try to infer from GraphQL schema (if available)
            try:
                response = client_api.session.post(
                    f"{client_api.url}/graphql",
                    headers=client_api.headers,
                    json={"query": "query { __schema { queryType { name } } }"}
                )
                if response.status_code == 200:
                    # If GraphQL works, likely 2.6+ (both versions support it)
                    # Default to 2.6 if we can't determine
                    logger.info("Could not determine exact version, defaulting to 2.6")
                    self._detected_version = self.VERSION_2_6
                    return self.VERSION_2_6
            except Exception:
                pass
            
        except Exception as e:
            logger.debug(f"Version detection failed: {e}")
        
        # Default to 2.6 if detection fails (backward compatible)
        logger.warning("Could not auto-detect OnWatch version, defaulting to 2.6")
        logger.warning("  → Set 'onwatch.version' in config.yaml to specify version explicitly")
        self._detected_version = self.VERSION_2_6
        return self.VERSION_2_6
    
    def _parse_version(self, version_str: str) -> Optional[str]:
        """Parse version string to extract major.minor version."""
        # Try to extract version like "2.6.0" or "2.8.1" or "v2.6"
        match = re.search(r'(\d+)\.(\d+)', str(version_str))
        if match:
            major, minor = match.groups()
            version = f"{major}.{minor}"
            if version in self.SUPPORTED_VERSIONS:
                return version
        return None
    
    def get_version(self, client_api=None) -> str:
        """
        Get OnWatch version (from config, detection, or default).
        
        Args:
            client_api: Optional ClientApi instance for auto-detection
            
        Returns:
            Version string ("2.6" or "2.8")
        """
        if self.version:
            return self.version
        
        if client_api:
            return self.detect_version(client_api)
        
        # Default to 2.6 if no version specified and no client_api provided
        return self.VERSION_2_6
    
    def is_version_2_8(self, client_api=None) -> bool:
        """Check if version is 2.8."""
        return self.get_version(client_api) == self.VERSION_2_8
    
    def is_version_2_6(self, client_api=None) -> bool:
        """Check if version is 2.6."""
        return self.get_version(client_api) == self.VERSION_2_6
    
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

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
        
        Tries multiple endpoints and searches recursively in responses.
        
        Args:
            client_api: ClientApi instance (must be logged in)
            
        Returns:
            Detected version string ("2.6" or "2.8")
        """
        if self._detected_version:
            return self._detected_version
        
        logger.debug("Starting version detection...")
        
        # Method 1: Try /settings endpoint first (most likely - UI shows version on settings page)
        try:
            logger.debug("Trying /settings endpoint for version detection...")
            response = client_api.session.get(
                f"{client_api.url}/settings",
                headers=client_api.headers
            )
            logger.debug(f"/settings endpoint response: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                # Recursively search for version in the response
                version_str = self._find_version_in_data(data)
                if version_str:
                    detected = self._parse_version(version_str)
                    if detected:
                        self._detected_version = detected
                        logger.info(f"Detected OnWatch version from /settings: {detected}")
                        return detected
                else:
                    logger.debug("No version found in /settings response")
        except Exception as e:
            logger.debug(f"Version detection via /settings failed: {e}")
        
        # Method 2: Try /info endpoint
        try:
            logger.debug("Trying /info endpoint for version detection...")
            response = client_api.session.get(
                f"{client_api.url}/info",
                headers=client_api.headers
            )
            logger.debug(f"/info endpoint response: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                version_str = data.get('version', '') or self._find_version_in_data(data)
                if version_str:
                    detected = self._parse_version(version_str)
                    if detected:
                        self._detected_version = detected
                        logger.info(f"Detected OnWatch version from /info: {detected}")
                        return detected
        except Exception as e:
            logger.debug(f"Version detection via /info failed: {e}")
        
        # Method 3: Try /system/info endpoint
        try:
            logger.debug("Trying /system/info endpoint for version detection...")
            response = client_api.session.get(
                f"{client_api.url}/system/info",
                headers=client_api.headers
            )
            logger.debug(f"/system/info endpoint response: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                version_str = data.get('version', '') or data.get('systemVersion', '') or self._find_version_in_data(data)
                if version_str:
                    detected = self._parse_version(version_str)
                    if detected:
                        self._detected_version = detected
                        logger.info(f"Detected OnWatch version from /system/info: {detected}")
                        return detected
        except Exception as e:
            logger.debug(f"Version detection via /system/info failed: {e}")
        
        # Method 4: Try /version endpoint
        try:
            logger.debug("Trying /version endpoint for version detection...")
            response = client_api.session.get(
                f"{client_api.url}/version",
                headers=client_api.headers
            )
            logger.debug(f"/version endpoint response: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                version_str = data.get('version', '') or self._find_version_in_data(data)
                if version_str:
                    detected = self._parse_version(version_str)
                    if detected:
                        self._detected_version = detected
                        logger.info(f"Detected OnWatch version from /version: {detected}")
                        return detected
        except Exception as e:
            logger.debug(f"Version detection via /version failed: {e}")
        
        # Method 5: Try GraphQL query for version
        try:
            logger.debug("Trying GraphQL query for version detection...")
            graphql_queries = [
                "query { system { version } }",
                "query { version }",
                "query { settings { version } }",
            ]
            for query in graphql_queries:
                try:
                    response = client_api.session.post(
                        f"{client_api.url}/graphql",
                        headers=client_api.headers,
                        json={"query": query}
                    )
                    if response.status_code == 200:
                        result = response.json()
                        if 'data' in result:
                            version_str = self._find_version_in_data(result['data'])
                            if version_str:
                                detected = self._parse_version(version_str)
                                if detected:
                                    self._detected_version = detected
                                    logger.info(f"Detected OnWatch version from GraphQL: {detected}")
                                    return detected
                except Exception:
                    continue
        except Exception as e:
            logger.debug(f"Version detection via GraphQL failed: {e}")
        
        # Default to 2.6 if detection fails (backward compatible)
        logger.warning("Could not auto-detect OnWatch version, defaulting to 2.6")
        logger.warning("  → Set 'onwatch.version' in config.yaml to specify version explicitly")
        logger.debug("  → Tried endpoints: /settings, /info, /system/info, /version, GraphQL")
        self._detected_version = self.VERSION_2_6
        return self.VERSION_2_6
    
    def _parse_version(self, version_str: str) -> Optional[str]:
        """Parse version string to extract major.minor version."""
        if not version_str:
            return None
        
        version_str = str(version_str).strip()
        
        # Handle formats like "2.8.0-0", "2.8.0", "v2.8.0", "Version 2.8.0-0"
        # Extract major.minor (e.g., "2.8" from "2.8.0-0" or "Version 2.8.0-0")
        match = re.search(r'(\d+)\.(\d+)', version_str)
        if match:
            major, minor = match.groups()
            version = f"{major}.{minor}"
            if version in self.SUPPORTED_VERSIONS:
                return version
        return None
    
    def _find_version_in_data(self, data, max_depth=5, current_depth=0):
        """
        Recursively search for version strings in nested dictionaries and lists.
        
        Args:
            data: Data structure to search (dict, list, or primitive)
            max_depth: Maximum recursion depth
            current_depth: Current recursion depth
            
        Returns:
            Version string if found, None otherwise
        """
        if current_depth >= max_depth:
            return None
        
        if isinstance(data, dict):
            # Check common version field names first
            for key in ['version', 'systemVersion', 'appVersion', 'onwatchVersion', 'productVersion']:
                if key in data:
                    value = data[key]
                    if value and isinstance(value, str):
                        parsed = self._parse_version(value)
                        if parsed:
                            logger.debug(f"Found version in field '{key}': {value} -> {parsed}")
                            return parsed
            
            # Recursively search all values
            for value in data.values():
                result = self._find_version_in_data(value, max_depth, current_depth + 1)
                if result:
                    return result
        elif isinstance(data, list):
            # Search each item in the list
            for item in data:
                result = self._find_version_in_data(item, max_depth, current_depth + 1)
                if result:
                    return result
        elif isinstance(data, str):
            # Check if the string itself looks like a version
            parsed = self._parse_version(data)
            if parsed:
                logger.debug(f"Found version in string: {data} -> {parsed}")
                return parsed
        
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

"""
Rancher API client for managing Kubernetes workload environment variables.

This module provides a REST API client for Rancher v3 API to:
- Authenticate with Rancher (token-based or basic auth)
- Retrieve workload configurations
- Update environment variables in Kubernetes workloads

The client supports both token-based authentication and basic authentication
as fallback for different Rancher versions.
"""
import requests
from urllib3.exceptions import InsecureRequestWarning
import urllib3
import logging

# Disable SSL warnings for self-signed certificates
urllib3.disable_warnings(InsecureRequestWarning)

logger = logging.getLogger(__name__)


class RancherApi:
    """Rancher API client for managing workloads."""
    
    def __init__(self, base_url, username, password):
        """
        Initialize Rancher API client.
        
        Args:
            base_url: Base URL of Rancher (e.g., https://10.1.71.14:9443)
            username: Rancher username
            password: Rancher password
        """
        self.base_url = base_url.rstrip('/')
        self.username = username
        self.password = password
        self.token = None
        self.session = requests.Session()
        self.session.verify = False
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
    
    def login(self):
        """
        Authenticate with Rancher API.
        
        Attempts token-based authentication first, then falls back to basic auth
        if token authentication fails. This supports different Rancher versions
        that may use different authentication methods.
        
        Raises:
            ValueError: If both authentication methods fail
            requests.exceptions.RequestException: If API request fails
        """
        auth = (self.username, self.password)
        
        # Try token-based login endpoint
        login_url = f"{self.base_url}/v3-public/localProviders/local?action=login"
        payload = {
            "username": self.username,
            "password": self.password
        }
        
        try:
            # Attempt token-based authentication
            response = self.session.post(login_url, json=payload, headers=self.headers, auth=auth)
            response.raise_for_status()
            
            response_json = response.json()
            # Extract token from response (format may vary by Rancher version)
            if "token" in response_json:
                self.token = response_json["token"]
            elif "data" in response_json and "token" in response_json["data"]:
                self.token = response_json["data"]["token"]
            else:
                # Token not found, try basic auth as fallback
                logger.info("Token not found in response, trying basic auth...")
                self.session.auth = auth
                test_url = f"{self.base_url}/v3/projects"
                test_response = self.session.get(test_url, headers=self.headers)
                if test_response.status_code == 200:
                    logger.info("Basic auth successful")
                    return response
                else:
                    raise ValueError(f"No token in login response and basic auth failed: {response.text}")
            
            # Set Bearer token in headers if token was obtained
            if self.token:
                self.headers["Authorization"] = f"Bearer {self.token}"
                self.session.headers.update(self.headers)
            
            logger.info("Successfully logged in to Rancher API")
            return response
            
        except requests.exceptions.RequestException as e:
            # Token-based login failed, try basic auth as fallback
            logger.debug(f"Token-based login failed: {e}, trying basic auth...")
            try:
                self.session.auth = auth
                test_url = f"{self.base_url}/v3/projects"
                test_response = self.session.get(test_url, headers=self.headers)
                if test_response.status_code == 200:
                    logger.info("Basic auth successful")
                    return test_response
                else:
                    raise ValueError(f"Both token and basic auth failed: {test_response.text}")
            except Exception as e2:
                error_msg = f"Rancher login failed for {self.base_url}"
                if hasattr(e, 'response') and e.response is not None:
                    status_code = e.response.status_code
                    if status_code == 401:
                        error_msg += ": Authentication failed (401 Unauthorized)"
                        error_msg += "\n  → Check username and password in config.yaml (rancher section)"
                        error_msg += "\n  → Verify credentials are correct for this Rancher instance"
                    else:
                        error_msg += f": HTTP {status_code} - {e.response.text[:200]}"
                else:
                    error_msg += f": {str(e)}"
                    error_msg += "\n  → Check network connectivity to Rancher"
                    error_msg += f"\n  → Verify Rancher is accessible at {self.base_url}"
                logger.error(error_msg)
                raise Exception(error_msg) from e
    
    def get_workload(self, workload_id="statefulset:default:cv-engine", project_id="local:p-p6l45"):
        """
        Get workload configuration.
        
        Args:
            workload_id: Workload ID (e.g., "statefulset:default:cv-engine")
            project_id: Project ID (e.g., "local:p-p6l45")
        
        Returns:
            Workload configuration as dict
        """
        url = f"{self.base_url}/v3/project/{project_id}/workloads/{workload_id}"
        
        try:
            response = self.session.get(url, headers=self.headers)
            response.raise_for_status()
            workload = response.json()
            logger.info(f"Successfully retrieved workload: {workload_id}")
            return workload
        except requests.exceptions.RequestException as e:
            error_msg = f"Failed to get Rancher workload: {workload_id}"
            if hasattr(e, 'response') and e.response is not None:
                status_code = e.response.status_code
                if status_code == 404:
                    error_msg += ": Workload not found (404)"
                    error_msg += f"\n  → Check workload_id '{workload_id}' is correct"
                    error_msg += f"\n  → Verify project_id '{project_id}' is correct"
                else:
                    error_msg += f": HTTP {status_code} - {e.response.text[:200]}"
            else:
                error_msg += f": {str(e)}"
            error_msg += f"\n  → URL: {url}"
            logger.error(error_msg)
            raise Exception(error_msg) from e
    
    def update_workload_environment_variables(self, env_vars, workload_id="statefulset:default:cv-engine", project_id="local:p-p6l45"):
        """
        Update environment variables for a Kubernetes workload.
        
        This method:
        1. Retrieves the current workload configuration
        2. Finds the main container (skips init containers)
        3. Updates/adds environment variables in the main container
        4. Saves the updated configuration via PUT request
        
        Args:
            env_vars: Dictionary of environment variable key-value pairs to set
            workload_id: Workload ID in format "type:namespace:name" 
                       (e.g., "statefulset:default:cv-engine")
            project_id: Rancher project ID (e.g., "local:p-p6l45")
        
        Returns:
            Updated workload configuration as dict
        
        Raises:
            ValueError: If main container cannot be found
            requests.exceptions.RequestException: If API request fails
        """
        # Retrieve current workload configuration
        workload = self.get_workload(workload_id, project_id)
        
        # Find the main application container (exclude init containers)
        containers = workload.get("containers", [])
        main_container = None
        for container in containers:
            if not container.get("initContainer", False):
                main_container = container
                break
        
        if not main_container:
            raise ValueError("Could not find main container in workload")
        
        # Initialize environment dict if it doesn't exist
        if "environment" not in main_container:
            main_container["environment"] = {}
        
        # Add or update environment variables
        # Note: Existing variables with the same key will be overwritten
        for key, value in env_vars.items():
            main_container["environment"][key] = str(value)
            logger.info(f"Setting environment variable: {key} = {value}")
        
        # Update the workload via PUT request
        url = f"{self.base_url}/v3/project/{project_id}/workloads/{workload_id}"
        
        try:
            response = self.session.put(url, json=workload, headers=self.headers)
            response.raise_for_status()
            updated_workload = response.json()
            logger.info(f"Successfully updated workload environment variables")
            return updated_workload
        except requests.exceptions.RequestException as e:
            error_msg = f"Failed to update Rancher workload environment variables: {workload_id}"
            if hasattr(e, 'response') and e.response is not None:
                status_code = e.response.status_code
                if status_code == 404:
                    error_msg += ": Workload not found (404)"
                    error_msg += f"\n  → Check workload_id '{workload_id}' is correct"
                elif status_code == 403:
                    error_msg += ": Permission denied (403)"
                    error_msg += "\n  → Verify Rancher user has permissions to update workloads"
                else:
                    error_msg += f": HTTP {status_code} - {e.response.text[:200]}"
            else:
                error_msg += f": {str(e)}"
            error_msg += f"\n  → Environment variables attempted: {list(env_vars.keys())}"
            logger.error(error_msg)
            raise Exception(error_msg) from e


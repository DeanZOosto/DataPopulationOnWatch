"""
OnWatch Client API wrapper for interacting with the OnWatch system via REST API.
Based on the existing testing code pattern.
"""
import requests
from urllib3.exceptions import InsecureRequestWarning
import urllib3
import logging
import mimetypes
import os
from datetime import datetime, timedelta
from constants import (
    INQUIRY_PRIORITY_MAP,
    INQUIRY_PRIORITY_DEFAULT,
    INQUIRY_PRIORITY_LOW,
    INQUIRY_PRIORITY_HIGH,
    KV_PARAMETER_ENDPOINTS
)
from version_compat import VersionCompat

# Disable SSL warnings for self-signed certificates
urllib3.disable_warnings(InsecureRequestWarning)

logger = logging.getLogger(__name__)

# Add support for additional image types
mimetypes.add_type('image/jpeg', '.jfif')


class MassImportAlreadyExists(Exception):
    """Exception raised when mass import with same name already exists."""
    pass


class AcknowledgeActionAlreadyExists(Exception):
    """Exception raised when acknowledge action with same title already exists."""
    pass


class InquiryCaseAlreadyExists(Exception):
    """Exception raised when inquiry case with same name already exists."""
    pass


class ClientApi:
    """Client API for interacting with OnWatch system."""
    
    def __init__(self, ip_address, username, password, version=None):
        """
        Initialize the ClientApi.
        
        Args:
            ip_address: IP address of the OnWatch system
            username: Username for authentication
            password: Password for authentication
            version: OnWatch version ("2.6" or "2.8"). Required.
            
        Raises:
            ValueError: If version is not provided or not supported.
        """
        if not version:
            raise ValueError("OnWatch version is required. Set 'onwatch.version' in config.yaml (e.g., '2.6' or '2.8')")
        
        self.ip_address = ip_address
        self.username = username
        self.password = password
        self.url = f"https://{ip_address}/bt/api"
        self.headers = {"accept": "application/json"}
        self.token = ""
        self.session = requests.Session()
        # Make SSL verification configurable via environment variable
        verify_ssl = os.getenv('ONWATCH_VERIFY_SSL', 'false').lower() == 'true'
        self.session.verify = verify_ssl
        if not verify_ssl:
            # Only disable warnings if SSL verification is disabled
            urllib3.disable_warnings(InsecureRequestWarning)
        self._settings_cache = None  # Cache for /settings endpoint response
        
        # Initialize version compatibility
        self.version_compat = VersionCompat(version=version)
        
    def login(self):
        """Login to the OnWatch system and set authentication headers."""
        login_url = f"{self.url}/login"  # This will be /bt/api/login
        payload = {
            "username": self.username,
            "password": self.password
        }
        
        try:
            response = self.session.post(login_url, headers=self.headers, json=payload)
            response.raise_for_status()
            
            # Extract token from response
            response_json = response.json()
            if "token" not in response_json:
                raise ValueError(f"No token in login response: {response.text}")
            
            self.token = response_json["token"]
            self.headers["authorization"] = f"Bearer {self.token}"
            
            # Update session headers
            self.session.headers.update(self.headers)
            
            logger.info(f"Successfully logged in to the OnWatch server at IP: {self.ip_address}")
            logger.info(f"OnWatch version: {self.version_compat.get_version()}")
            return response
            
        except requests.exceptions.RequestException as e:
            error_msg = f"Login failed to OnWatch system at {self.ip_address}"
            if hasattr(e, 'response') and e.response is not None:
                status_code = e.response.status_code
                if status_code == 401:
                    error_msg += ": Authentication failed (401 Unauthorized)"
                    error_msg += "\n  → Check username and password in config.yaml (onwatch section)"
                    error_msg += "\n  → Verify credentials are correct for this OnWatch system"
                elif status_code == 404:
                    error_msg += f": Login endpoint not found (404 Not Found)"
                    error_msg += f"\n  → Check if OnWatch API is accessible at {login_url}"
                    error_msg += "\n  → Verify IP address and network connectivity"
                else:
                    error_msg += f": HTTP {status_code} - {e.response.text[:200]}"
            else:
                error_msg += f": {str(e)}"
                error_msg += "\n  → Check network connectivity to OnWatch system"
                error_msg += f"\n  → Verify IP address {self.ip_address} is correct"
            logger.error(error_msg)
            raise Exception(error_msg) from e
    
    def extract_faces_from_image(self, image_path):
        """
        Extract face features from an image.
        
        Args:
            image_path: Path to the image file
            
        Returns:
            Response object with extracted face data
        """
        # External functions endpoint uses /api prefix
        extract_url = f"{self.url}/external-functions/extract-faces-from-image"  # /bt/api/external-functions/extract-faces-from-image
        
        try:
            filename = os.path.basename(image_path)
            content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
            
            with open(image_path, 'rb') as f:
                # Match the format from FeaturesApi: (filename, file_object, content_type)
                files = {
                    "file": (filename, f, content_type)
                }
                response = self.session.post(extract_url, files=files, headers=self.headers)
                response.raise_for_status()
                return response
        except FileNotFoundError:
            error_msg = f"Image file not found: {image_path}"
            error_msg += "\n  → Verify the file path in config.yaml is correct"
            error_msg += "\n  → Check if file exists and is readable"
            error_msg += "\n  → Ensure path is relative to project root or absolute"
            logger.error(error_msg)
            raise FileNotFoundError(error_msg)
        except requests.exceptions.RequestException as e:
            error_msg = f"Failed to extract faces from image: {os.path.basename(image_path)}"
            if hasattr(e, 'response') and e.response is not None:
                error_msg += f"\n  → API returned: {e.response.status_code} - {e.response.text[:200]}"
            else:
                error_msg += f"\n  → Error: {str(e)}"
            error_msg += f"\n  → Endpoint: {extract_url}"
            error_msg += "\n  → Check if OnWatch API is accessible and authentication is valid"
            logger.error(error_msg)
            raise Exception(error_msg) from e
    
    def add_subject_from_image(self, name, pic, group_id):
        """
        Add a subject to the watch list from an image.
        
        Args:
            name: Subject name
            pic: Path to the image file
            group_id: Group ID to assign the subject to (can be None)
            
        Returns:
            Response object
        """
        try:
            extract_response = self.extract_faces_from_image(pic)
            extract_data = extract_response.json()
            
            # Handle different response formats
            if "items" in extract_data:
                items = extract_data["items"]
            elif isinstance(extract_data, list):
                items = extract_data
            else:
                items = [extract_data]
            
            if not items:
                raise ValueError("No face data returned from extract_faces_from_image")
            
            data = items[0]
            
            # Build payload - only include groups if group_id is provided
            payload = {
                "name": name,
                "images": [
                    {
                        "objectType": data["objectType"],
                        "isPrimary": True,
                        "featuresQuality": data["featuresQuality"],
                        "url": data["url"],
                        "features": data["features"],
                        "landmarkScore": data["landmarkScore"]
                    }
                ]
            }
            
            # Only add groups if group_id is provided and not None
            if group_id:
                payload["groups"] = [group_id]
            
            response = self.session.post(
                f"{self.url}/subjects",
                headers=self.headers,
                json=payload
            )
            
            # Better error logging
            if response.status_code != 201:
                error_msg = f"Failed to add subject '{name}' to watch list"
                error_msg += f"\n  → HTTP Status: {response.status_code}"
                error_msg += f"\n  → Response: {response.text[:300]}"
                if response.status_code == 400:
                    error_msg += "\n  → Check subject name format and image file validity"
                    error_msg += "\n  → Verify group_id is valid (or set to null)"
                elif response.status_code == 409:
                    error_msg += "\n  → Subject may already exist (this should be handled by duplicate check)"
                logger.error(error_msg)
                logger.debug(f"Payload sent: {payload}")
            
            response.raise_for_status()
            return response
            
        except ConnectionError as ce:
            logger.error(f"Connection error: {ce}")
            raise
        except (IndexError, KeyError, ValueError) as ie:
            logger.error(f"The system was unable to extract features from the file: {pic}. Error: {ie}")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Error adding subject: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response text: {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error adding subject: {e}")
            raise
    
    def update_subject(self, subject_id, **kwargs):
        """
        Update a subject with provided fields.
        
        Args:
            subject_id: ID of the subject
            **kwargs: Fields to update (e.g., images, name, description)
            
        Returns:
            Response object
        """
        payload = {
            "isProduceSocket": True,
        }
        payload.update(kwargs)
        
        response = self.session.patch(
            f"{self.url}/subjects/{subject_id}",
            headers=self.headers,
            json=payload
        )
        
        if response.status_code != 200:
            logger.error(f"Failed to update subject. Status: {response.status_code}, Response: {response.text}")
            logger.error(f"Payload sent: {payload}")
        
        response.raise_for_status()
        return response
    
    def add_image_to_subject(self, subject_id, image_path, first_image_data=None):
        """
        Add an additional image to an existing subject.
        
        Args:
            subject_id: ID of the subject
            image_path: Path to the image file
            first_image_data: Optional first image data from subject creation (to avoid losing it)
            
        Returns:
            Response object
        """
        try:
            # Extract face features from the image
            extract_response = self.extract_faces_from_image(image_path)
            extract_data = extract_response.json()
            
            # Handle different response formats
            if "items" in extract_data:
                items = extract_data["items"]
            elif isinstance(extract_data, list):
                items = extract_data
            else:
                items = [extract_data]
            
            if not items:
                raise ValueError("No face data returned from extract_faces_from_image")
            
            data = items[0]
            
            # Get current subject to append to existing images
            subject_response = self.session.get(
                f"{self.url}/subjects/{subject_id}",
                headers=self.headers
            )
            subject_response.raise_for_status()
            current_subject = subject_response.json()
            
            # Get existing images
            existing_images = current_subject.get("images", [])
            
            # If no existing images found but we have first_image_data, use it
            if not existing_images and first_image_data:
                logger.info("Using first_image_data fallback: API didn't return images yet")
                # Ensure first image is marked as primary
                first_image = first_image_data.copy()
                first_image["isPrimary"] = True
                existing_images = [first_image]
            elif not existing_images and not first_image_data:
                logger.warning("No existing images found and no first_image_data provided - first image may be lost!")
            
            # Log existing images status for debugging
            logger.debug(f"Fetched existing images: {len(existing_images)} image(s)")
            for i, img in enumerate(existing_images):
                logger.debug(f"  Image {i}: isPrimary={img.get('isPrimary', 'NOT SET')}, url={img.get('url', 'unknown')[:50]}...")
            
            # Ensure exactly one existing image is marked as primary
            # Count how many existing images have isPrimary: True
            primary_count = sum(1 for img in existing_images if img.get("isPrimary", False) is True)
            
            if existing_images:
                if primary_count == 0:
                    # No primary image found - mark the first one as primary
                    logger.info(f"No primary image found in existing images, marking first image as primary")
                    # Ensure the key exists and set it to True
                    if "isPrimary" not in existing_images[0]:
                        existing_images[0]["isPrimary"] = True
                    else:
                        existing_images[0]["isPrimary"] = True
                    logger.debug(f"Set first image isPrimary to: {existing_images[0].get('isPrimary')}")
                elif primary_count > 1:
                    # Multiple primary images found - keep only the first one as primary
                    logger.warning(f"Found {primary_count} primary images, keeping only the first one as primary")
                    for i, img in enumerate(existing_images):
                        img["isPrimary"] = (i == 0)
                else:
                    # Exactly one primary image - log for debugging
                    primary_url = next((img.get("url", "unknown") for img in existing_images if img.get("isPrimary", False) is True), "unknown")
                    logger.debug(f"Found existing primary image: {primary_url}")
            else:
                logger.warning("No existing images found when trying to add additional image")
            
            # Build new image in the format expected by API
            # Based on user's example: includes backup, attributes, etc.
            new_image = {
                "url": data.get("url"),
                "featuresQuality": data.get("featuresQuality", 0),
                "features": data.get("features", []),
                "isPrimary": False,  # Additional images are not primary
                "featuresId": data.get("featuresId", ""),
                "objectType": data.get("objectType", 1)
            }
            
            # Add backup field if present in extract response
            if "backup" in data:
                new_image["backup"] = data["backup"]
            
            # Add attributes if present
            if "attributes" in data:
                new_image["attributes"] = data["attributes"]
            
            # Add landmarkScore if present
            if "landmarkScore" in data:
                new_image["landmarkScore"] = data["landmarkScore"]
            
            # Add feNetwork if present
            if "feNetwork" in data:
                new_image["feNetwork"] = data["feNetwork"]
            
            existing_images.append(new_image)
            
            # Validate that exactly one image is marked as primary before sending
            # Use explicit True check to avoid issues with truthy values
            final_primary_count = sum(1 for img in existing_images if img.get("isPrimary", False) is True)
            
            # Log all images before validation for debugging
            logger.debug(f"Final images before validation: {len(existing_images)} image(s)")
            for i, img in enumerate(existing_images):
                logger.debug(f"  Image {i}: isPrimary={img.get('isPrimary', 'NOT SET')}, url={img.get('url', 'unknown')[:50]}...")
            
            if final_primary_count != 1:
                # Last attempt: if no primary, force first one to be primary
                if final_primary_count == 0 and existing_images:
                    logger.warning("No primary image found in final list, forcing first image to be primary")
                    existing_images[0]["isPrimary"] = True
                    # Verify it was set
                    if existing_images[0].get("isPrimary") is True:
                        logger.info("Successfully set first image as primary")
                        final_primary_count = 1
                    else:
                        error_msg = f"Failed to set primary image: found {final_primary_count} primary images, expected exactly 1"
                        logger.error(error_msg)
                        logger.error(f"Images status: {[(img.get('url', 'unknown')[:50], img.get('isPrimary', 'NOT SET')) for img in existing_images]}")
                        raise ValueError(error_msg)
                elif final_primary_count > 1:
                    # Multiple primaries - keep only first
                    logger.warning(f"Found {final_primary_count} primary images, keeping only the first one")
                    for i, img in enumerate(existing_images):
                        img["isPrimary"] = (i == 0)
                    final_primary_count = 1
                else:
                    error_msg = f"Invalid primary image configuration: found {final_primary_count} primary images, expected exactly 1"
                    logger.error(error_msg)
                    logger.error(f"Images status: {[(img.get('url', 'unknown')[:50], img.get('isPrimary', 'NOT SET')) for img in existing_images]}")
                    raise ValueError(error_msg)
            
            # Log which image is primary for debugging
            primary_image = next((img for img in existing_images if img.get("isPrimary", False)), None)
            if primary_image:
                logger.debug(f"Primary image: {primary_image.get('url', 'unknown')}")
            
            # Update subject with all images - use update_subject pattern
            payload = {
                "isProduceSocket": True,
                "images": existing_images
            }
            
            response = self.session.patch(
                f"{self.url}/subjects/{subject_id}",
                headers=self.headers,
                json=payload
            )
            
            if response.status_code != 200:
                logger.error(f"Failed to add image to subject. Status: {response.status_code}, Response: {response.text}")
                logger.error(f"Payload sent: {payload}")
            
            response.raise_for_status()
            return response
            
        except Exception as e:
            logger.error(f"Error adding image to subject: {e}")
            raise
    
    def get_groups(self, limit=None, offset=None, search=None, with_subjects_count=True):
        """
        Get all groups. Returns list of groups or dict with 'items' key.
        
        Args:
            limit: Maximum number of groups to return
            offset: Offset for pagination
            search: Search query string
            with_subjects_count: Include subject count in response
        """
        try:
            params = {}
            if limit is not None:
                params['limit'] = limit
            if offset is not None:
                params['offset'] = offset
            if search:
                params['search'] = search
            if with_subjects_count:
                params['withSubjectsCount'] = 'true'
            
            response = self.session.get(
                f"{self.url}/groups",
                headers=self.headers,
                params=params
            )
            response.raise_for_status()
            data = response.json()
            # Handle both formats: direct list or {"items": [...]}
            if isinstance(data, list):
                return data
            elif isinstance(data, dict) and 'items' in data:
                return data['items']
            else:
                return data
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get groups: {e}")
            raise
    
    def create_group(self, name):
        """Create a new group (legacy method - use create_subject_group for full control)."""
        try:
            payload = {"name": name}
            response = self.session.post(
                f"{self.url}/groups",
                headers=self.headers,
                json=payload
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to create group: {e}")
            raise
    
    def _get_alert_level_by_visibility(self, visibility):
        """
        Get alertLevel UUID by matching visibility string.
        Fetches existing groups and tries to match visibility.
        
        Args:
            visibility: Visibility string ("Silent", "Visible", "Loud")
        
        Returns:
            alertLevel UUID string or None if not found
        """
        try:
            groups = self.get_groups()
            if not isinstance(groups, list):
                groups = groups.get('items', []) if isinstance(groups, dict) else []
            
            # Try to find a group that might match the visibility
            # Since we don't have direct visibility in response, we'll use a mapping approach
            # Based on user info: "Loud" (test), "Silent" (OnPatrol), "Visible" (Cardholders)
            visibility_lower = visibility.lower() if visibility else ""
            
            # Look for known group patterns that match visibility
            for group in groups:
                if not isinstance(group, dict):
                    continue
                
                title = group.get('title', '').lower()
                alert_level = group.get('alertLevel')
                
                # Try to match based on known patterns
                if visibility_lower == 'silent':
                    # OnPatrol subjects are typically "Silent"
                    if 'onpatrol' in title or 'patrol' in title:
                        return alert_level
                elif visibility_lower == 'visible':
                    # Cardholders are typically "Visible"
                    if 'cardholder' in title or 'card' in title:
                        return alert_level
                elif visibility_lower == 'loud':
                    # Test groups might be "Loud"
                    if 'test' in title:
                        return alert_level
            
            # If no match found, try to get a default based on type
            # For "Silent" or "Visible", try to find any group with matching characteristics
            if visibility_lower in ['silent', 'visible']:
                for group in groups:
                    if isinstance(group, dict) and group.get('alertLevel'):
                        # Use first available alertLevel as fallback
                        return group.get('alertLevel')
            
            logger.warning(f"Could not find alertLevel for visibility '{visibility}', using default")
            # Return a default UUID if available, or None
            return None
        except Exception as e:
            logger.warning(f"Error fetching alertLevel for visibility '{visibility}': {e}")
            return None
    
    def create_subject_group(self, name, authorization, visibility, priority=0, description="", color="#D20300", camera_groups=None):
        """
        Create a subject group with full configuration.
        
        Args:
            name: Group name (title)
            authorization: "Always Authorized" or "Always Unauthorized"
            visibility: "Silent", "Visible", or "Loud"
            priority: Priority/threshold value (default: 0)
            description: Group description (default: empty string)
            color: Hex color code (default: "#D20300")
            camera_groups: List of camera group IDs (required if priority > 0)
        
        Returns:
            Created group data
        """
        try:
            # Map authorization to type
            # 0 = "Always Unauthorized", 1 = "Always Authorized"
            if authorization.lower() == "always authorized":
                group_type = 1
            else:  # "Always Unauthorized" or default
                group_type = 0
            
            # Get alertLevel UUID based on visibility
            # Try to fetch from existing groups first, but if none exist (clean system), use defaults
            alert_level = self._get_alert_level_by_visibility(visibility)
            if not alert_level:
                # Use default alertLevel UUIDs based on visibility for clean system
                # These are common defaults - may need adjustment based on your system
                visibility_lower = visibility.lower() if visibility else ""
                if visibility_lower == 'silent':
                    alert_level = "00000000-0200-48f3-b728-10de4c0a906f"  # Default Silent
                elif visibility_lower == 'visible':
                    alert_level = "00000000-0200-40e7-a33e-5f290f69366e"  # Default Visible
                elif visibility_lower == 'loud':
                    alert_level = "00000000-0200-4a4b-a663-8a64251b0437"  # Default Loud
                else:
                    # Fallback to Silent if unknown
                    alert_level = "00000000-0200-48f3-b728-10de4c0a906f"
                    logger.warning(f"Unknown visibility '{visibility}', using default Silent alertLevel")
                logger.info(f"Using default alertLevel for visibility '{visibility}' (clean system)")
            
            # If priority > 0, camera groups are required
            # If no camera groups provided and priority > 0, set priority to 0
            if priority > 0 and (not camera_groups or len(camera_groups) == 0):
                logger.warning(f"Priority > 0 requires camera groups. Setting priority to 0 for group '{name}'")
                priority = 0
            
            camera_groups_list = camera_groups if camera_groups else []
            
            payload = {
                "title": name,
                "description": description,
                "th": priority,
                "alertLevel": alert_level,
                "type": group_type,
                "color": color,
                "authRules": [],
                "cameraGroups": camera_groups_list
            }
            
            response = self.session.post(
                f"{self.url}/groups",
                headers=self.headers,
                json=payload
            )
            response.raise_for_status()
            result = response.json()
            logger.info(f"Created subject group: {name} (id: {result.get('id')})")
            return result
        except requests.exceptions.RequestException as e:
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Failed to create subject group '{name}': {e}")
                logger.error(f"Response status: {e.response.status_code}")
                logger.error(f"Response body: {e.response.text}")
            else:
                logger.error(f"Failed to create subject group '{name}': {e}")
            raise
    
    def get_subjects(self, limit=None, offset=None, fetch_all=True):
        """
        Get all subjects.
        
        Args:
            limit: Maximum number of subjects to return per request (for pagination)
            offset: Offset for pagination
            fetch_all: If True, fetch all subjects by paginating through results (default: True)
            
        Returns:
            List of subjects or dict with 'items' key, depending on API response format
        """
        try:
            all_subjects = []
            current_offset = offset or 0
            page_size = limit or 1000  # Default page size for pagination (2.8 uses 1000)
            
            # OnWatch 2.8 uses POST /subjects/search, 2.6 uses GET /subjects
            if self.version_compat.is_version_2_8():
                # Use POST /subjects/search endpoint for 2.8
                while True:
                    params = {
                        'limit': page_size,
                        'offset': current_offset
                    }
                    
                    response = self.session.post(
                        f"{self.url}/subjects/search",
                        headers=self.headers,
                        params=params
                    )
                    response.raise_for_status()
                    data = response.json()
                    
                    # Handle response format
                    if isinstance(data, list):
                        page_subjects = data
                        all_subjects.extend(page_subjects)
                        # If we got fewer than page_size, we've reached the end
                        if not fetch_all or len(page_subjects) < page_size:
                            break
                        current_offset += page_size
                    elif isinstance(data, dict):
                        if 'items' in data:
                            page_subjects = data['items']
                            all_subjects.extend(page_subjects)
                            # Check if there are more pages
                            total = data.get('total', len(page_subjects))
                            if not fetch_all or current_offset + len(page_subjects) >= total or len(page_subjects) < page_size:
                                break
                            current_offset += page_size
                        elif 'data' in data:
                            page_subjects = data['data'] if isinstance(data['data'], list) else [data['data']]
                            all_subjects.extend(page_subjects)
                            if not fetch_all or len(page_subjects) < page_size:
                                break
                            current_offset += page_size
                        else:
                            # Unknown dict format
                            if not fetch_all:
                                return data
                            logger.warning(f"Unexpected response format from get_subjects (2.8): {list(data.keys())}")
                            break
                    else:
                        if not fetch_all:
                            return data
                        logger.warning(f"Unexpected response type from get_subjects (2.8): {type(data)}")
                        break
            else:
                # Use GET /subjects endpoint for 2.6
                while True:
                    params = {}
                    if limit is not None or fetch_all:
                        params['limit'] = page_size
                        params['offset'] = current_offset
                    
                    response = self.session.get(
                        f"{self.url}/subjects",
                        headers=self.headers,
                        params=params if params else None
                    )
                    response.raise_for_status()
                    data = response.json()
                    
                    # Handle different response formats
                    if isinstance(data, list):
                        # Direct list response
                        page_subjects = data
                        all_subjects.extend(page_subjects)
                        # If we got fewer than page_size, we've reached the end
                        if not fetch_all or len(page_subjects) < page_size:
                            break
                        current_offset += page_size
                    elif isinstance(data, dict):
                        # Dict response - could have 'items', 'data', or pagination info
                        if 'items' in data:
                            page_subjects = data['items']
                            all_subjects.extend(page_subjects)
                            # Check if there are more pages
                            total = data.get('total', len(page_subjects))
                            if not fetch_all or current_offset + len(page_subjects) >= total or len(page_subjects) < page_size:
                                break
                            current_offset += page_size
                        elif 'data' in data:
                            page_subjects = data['data'] if isinstance(data['data'], list) else [data['data']]
                            all_subjects.extend(page_subjects)
                            if not fetch_all or len(page_subjects) < page_size:
                                break
                            current_offset += page_size
                        else:
                            # Unknown dict format - return as-is
                            if not fetch_all:
                                return data
                            # Try to extract items if possible
                            logger.warning(f"Unexpected response format from get_subjects (2.6): {list(data.keys())}")
                            break
                    else:
                        # Unknown format - return as-is
                        if not fetch_all:
                            return data
                        logger.warning(f"Unexpected response type from get_subjects (2.6): {type(data)}")
                        break
            
            # Return in the same format as the original API response
            if fetch_all and all_subjects:
                # Return as list if we fetched all, or as dict with 'items' if original was dict
                return all_subjects
            elif not fetch_all:
                return data
            else:
                return all_subjects if all_subjects else []
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get subjects: {e}")
            raise
    
    def get_roles(self):
        """
        Get all roles. Returns list of roles with id and title.
        """
        try:
            response = self.session.get(
                f"{self.url}/roles",
                headers=self.headers
            )
            response.raise_for_status()
            data = response.json()
            # Handle both formats: direct list or {"items": [...]}
            if isinstance(data, list):
                return data
            elif isinstance(data, dict) and 'items' in data:
                return data['items']
            else:
                return data
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get roles: {e}")
            raise
    
    def create_user_group(self, title, subject_groups=None, camera_groups=None):
        """
        Create a user group.
        
        Args:
            title: User group name/title
            subject_groups: List of subject group IDs (optional)
            camera_groups: List of camera group IDs (optional)
        
        Returns:
            Response object
        """
        payload = {
            "title": title,
            "cameraGroups": camera_groups or [],
            "subjectGroups": subject_groups or []
        }
        
        response = self.session.post(
            f"{self.url}/user-groups",
            headers=self.headers,
            json=payload
        )
        response.raise_for_status()
        return response
    
    def get_user_groups(self):
        """
        Get all user groups. Returns list of user groups with id and title.
        """
        try:
            response = self.session.get(
                f"{self.url}/user-groups",
                headers=self.headers
            )
            response.raise_for_status()
            data = response.json()
            # Handle both formats: direct list or {"items": [...]}
            if isinstance(data, list):
                return data
            elif isinstance(data, dict) and 'items' in data:
                return data['items']
            else:
                return data
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get user groups: {e}")
            raise
    
    def get_users(self):
        """
        Get all users. Returns list of users.
        """
        try:
            response = self.session.get(
                f"{self.url}/users",
                headers=self.headers
            )
            response.raise_for_status()
            data = response.json()
            # Handle both formats: direct list or {"items": [...]}
            if isinstance(data, list):
                return data
            elif isinstance(data, dict) and 'items' in data:
                return data['items']
            else:
                return data
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get users: {e}")
            raise
    
    def create_user(self, username, first_name, last_name, email, role_id, user_group_id, password=None):
        """
        Create a new user.
        
        Args:
            username: Username
            first_name: First name
            last_name: Last name
            email: Email address (can be None)
            role_id: Role ID (UUID)
            user_group_id: User group ID (UUID)
            password: Password (optional, if None, password field is skipped)
        
        Returns:
            Created user data
        """
        try:
            payload = {
                "username": username,
                "firstName": first_name,
                "lastName": last_name,
                "roleId": role_id,
                "userGroupId": user_group_id
            }
            
            # Add email if provided
            if email:
                payload["email"] = email
            
            # Add password if provided (skip if None)
            if password:
                payload["password"] = password
            
            response = self.session.post(
                f"{self.url}/users",
                headers=self.headers,
                json=payload
            )
            response.raise_for_status()
            result = response.json()
            logger.info(f"Created user: {username} (id: {result.get('id')})")
            return result
        except requests.exceptions.RequestException as e:
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Failed to create user '{username}': {e}")
                logger.error(f"Response status: {e.response.status_code}")
                logger.error(f"Response body: {e.response.text}")
            else:
                logger.error(f"Failed to create user '{username}': {e}")
            raise
    
    def set_kv_parameter(self, key, value):
        """
        Set a KV parameter using GraphQL mutation.
        
        Args:
            key: Parameter key
            value: Parameter value
        """
        try:
            # GraphQL mutation endpoint
            graphql_url = f"{self.url}/graphql"  # This will be /bt/api/graphql
            
            # Get version-specific mutation
            mutation_query = self.version_compat.get_graphql_mutation_for_kv().strip()
            
            # Build payload based on version
            if self.version_compat.is_version_2_8():
                # OnWatch 2.8 uses KeyValueSettingInput object
                payload = {
                    "operationName": "updateSingleSetting",
                    "variables": {
                        "settingInput": {
                            "key": key,
                            "value": str(value)  # Convert to string as API expects
                        }
                    },
                    "query": mutation_query
                }
            else:
                # OnWatch 2.6 uses separate key and value parameters
                payload = {
                    "operationName": "updateSingleSetting",
                    "variables": {
                        "key": key,
                        "value": str(value)  # Convert to string as API expects
                    },
                    "query": mutation_query
                }
            
            response = self.session.post(
                graphql_url,
                headers=self.headers,
                json=payload
            )
            response.raise_for_status()
            
            # Check GraphQL response for errors
            result = response.json()
            if 'errors' in result:
                errors = result['errors']
                # Check if error is "already exists" or "no change needed"
                error_messages = [str(err).lower() for err in errors]
                if any(phrase in msg for msg in error_messages for phrase in ['already exists', 'already set', 'no change', 'unchanged']):
                    logger.debug(f"KV parameter {key} already has correct value or already exists")
                    return response  # Success - no change needed
                logger.error(f"GraphQL errors for {key}: {errors}")
                raise Exception(f"GraphQL error: {errors}")
            
            logger.info(f"Successfully set KV parameter: {key} = {value}")
            return response
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to set KV parameter {key}: {e}")
            raise
    
    def update_system_settings(self, settings):
        """
        Update system settings via API.
        All settings sections (general, map, engine, interface) use the same endpoint.
        
        Args:
            settings: Dictionary with sections: general, map, system_interface, engine
        """
        try:
            payload = {}
            
            # General settings
            if 'general' in settings:
                general = settings['general']
                if 'default_face_threshold' in general:
                    payload['defaultFaceThreshold'] = float(general['default_face_threshold'])
                if 'default_body_threshold' in general:
                    payload['defaultBodyThreshold'] = float(general['default_body_threshold'])
                if 'default_liveness_threshold' in general:
                    payload['cameraDefaultLivenessTh'] = float(general['default_liveness_threshold'])
                if 'body_image_retention_period' in general:
                    retention = general['body_image_retention_period']
                    if isinstance(retention, str):
                        import re
                        match = re.search(r'(\d+)', retention)
                        if match:
                            payload['bodyImageTtlH'] = int(match.group(1))
                    else:
                        payload['bodyImageTtlH'] = int(retention)
                # Note: privacyMode and gdprMode are intentionally NOT modified
            
            # Map settings
            if 'map' in settings:
                map_settings = settings['map']
                payload['map'] = {}
                
                # Seed location - API expects [long, lat] array
                if 'seed_location' in map_settings:
                    seed = map_settings['seed_location']
                    payload['map']['center'] = [
                        float(seed.get('long', 0)),
                        float(seed.get('lat', 0))
                    ]
                
                # Note: masks_access_control is intentionally NOT modified
                # Note: 'acknowledge' and 'action_title' are handled separately via acknowledge-actions endpoints
            
            # Engine settings - note: API uses "Xd" format (e.g., "6d", "8d")
            if 'engine' in settings:
                engine = settings['engine']
                if 'video_storage' in engine:
                    vs = engine['video_storage']
                    if 'all_videos_days' in vs:
                        payload['videoTtl'] = f"{int(vs['all_videos_days'])}d"
                    if 'videos_with_detections_days' in vs:
                        payload['videosWithoutRecognitionsTtl'] = f"{int(vs['videos_with_detections_days'])}d"
                if 'detection_storage_days' in engine:
                    payload['detectionTtl'] = f"{int(engine['detection_storage_days'])}d"
                if 'alert_storage_days' in engine:
                    payload['recognitionTtl'] = f"{int(engine['alert_storage_days'])}d"
                if 'inquiry_storage_days' in engine:
                    payload['inquiryTtl'] = f"{int(engine['inquiry_storage_days'])}d"
            
            # System interface settings
            if 'system_interface' in settings:
                interface = settings['system_interface']
                if 'product_name' in interface:
                    if 'whiteLabel' not in payload:
                        payload['whiteLabel'] = {}
                    payload['whiteLabel']['productName'] = interface['product_name']
                # Note: Logo uploads are handled separately via upload_logo method
                # Note: Translation file upload requires manual bash script (no API endpoint)
            
            if not payload:
                logger.warning("No system settings to update")
                return None
            
            response = self.session.patch(
                f"{self.url}/settings",  # This will be /bt/api/settings
                headers=self.headers,
                json=payload
            )
            response.raise_for_status()
            
            logger.info(f"Successfully updated system settings")
            return response
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to update system settings: {e}")
            raise
    
    def enable_acknowledge_actions(self, enabled=True):
        """
        Enable or disable acknowledge actions.
        
        Args:
            enabled: Boolean to enable/disable acknowledge actions
        """
        try:
            response = self.session.patch(
                f"{self.url}/acknowledge-actions/action-enforcement",
                headers=self.headers,
                json={"isEnabled": enabled}
            )
            response.raise_for_status()
            logger.info(f"Set acknowledge actions enabled: {enabled}")
            return response
        except requests.exceptions.RequestException as e:
            # Log the response body for debugging
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Failed to set acknowledge actions enabled: {e}")
                logger.error(f"Response status: {e.response.status_code}")
                logger.error(f"Response body: {e.response.text}")
            else:
                logger.error(f"Failed to set acknowledge actions enabled: {e}")
            raise
    
    def create_acknowledge_action(self, title, description=""):
        """
        Create an acknowledge action.
        
        Args:
            title: Action title
            description: Action description (optional)
        
        Raises:
            AcknowledgeActionAlreadyExists: If action with same title already exists (409)
        """
        try:
            payload = {
                "title": title,
                "description": description
            }
            response = self.session.post(
                f"{self.url}/acknowledge-actions",
                headers=self.headers,
                json=payload
            )
            
            # Check if action already exists (409 Conflict)
            if response.status_code == 409:
                try:
                    error_data = response.json()
                    if error_data.get('code') == 'ERR_ACTION_ALREADY_EXISTS':
                        raise AcknowledgeActionAlreadyExists(f"Acknowledge action '{title}' already exists: {error_data.get('message', '')}")
                except ValueError:
                    pass  # Not JSON, continue with normal error handling
            
            response.raise_for_status()
            result = response.json()
            logger.info(f"Created acknowledge action: {title} (id: {result.get('id')})")
            return result
        except AcknowledgeActionAlreadyExists:
            raise  # Re-raise as-is
        except requests.exceptions.RequestException as e:
            # Log the response body for debugging
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Failed to create acknowledge action: {e}")
                logger.error(f"Response status: {e.response.status_code}")
                logger.error(f"Response body: {e.response.text}")
            else:
                logger.error(f"Failed to create acknowledge action: {e}")
            raise
    
    def upload_logo(self, logo_path, folder_name):
        """
        Upload logo file (company, sidebar, or favicon) using two-step process.
        
        Args:
            logo_path: Path to the logo image file
            folder_name: Folder name - "company", "sidebar", or "favicon"
        """
        try:
            filename = os.path.basename(logo_path)
            content_type = mimetypes.guess_type(filename)[0] or "image/jpeg"
            
            # Step 1: Prepare upload
            prepare_payload = {
                "staticFilesType": "logos",
                "folders": [{"folderName": folder_name, "fileName": filename}],
                "shouldOverrideFolders": True
            }
            
            prepare_response = self.session.post(
                f"{self.url}/upload/prepare/static-files",
                headers=self.headers,
                json=prepare_payload
            )
            prepare_response.raise_for_status()
            prepare_result = prepare_response.json()
            
            # Extract UUID from response
            upload_uuid = None
            if isinstance(prepare_result, list) and len(prepare_result) > 0:
                upload_uuid = prepare_result[0].get('id')
            elif isinstance(prepare_result, dict):
                upload_uuid = prepare_result.get('id') or prepare_result.get('uploadId')
            
            if not upload_uuid:
                raise ValueError(f"Could not extract upload UUID from prepare response: {prepare_result}")
            
            # Step 2: Upload file
            # Read file content to ensure it's properly sent
            with open(logo_path, 'rb') as f:
                file_content = f.read()
            
            # The API expects "files" as the field name (confirmed via testing)
            files = {
                "files": (filename, file_content, content_type)
            }
            # Remove Content-Type from headers to let requests set it automatically for multipart/form-data
            upload_headers = {k: v for k, v in self.headers.items() if k.lower() != 'content-type'}
            
            response = self.session.post(
                f"{self.url}/upload/static-files/{upload_uuid}",
                headers=upload_headers,
                files=files
            )
            response.raise_for_status()
            result = response.json()
            # Log the upload result for verification
            upload_info = None
            file_location = None
            if isinstance(result, list) and len(result) > 0:
                upload_info = result[0]
                file_location = upload_info.get('location', '')
                logger.info(f"Uploaded {folder_name} logo: {filename} -> {file_location}")
            else:
                logger.info(f"Uploaded {folder_name} logo: {filename}")
            
            # After file upload, call GraphQL mutation to register the logo
            if file_location:
                try:
                    # Map folder names to whiteLabel field names
                    logo_field_map = {
                        "company": "companyLogo",
                        "sidebar": "sidebarLogo",
                        "favicon": "favicon"
                    }
                    
                    logo_field = logo_field_map.get(folder_name)
                    if logo_field:
                        # Get current whiteLabel settings first to preserve productName
                        current_settings = self._get_current_white_label_settings()
                        
                        # Update the specific logo field
                        white_label_update = current_settings.copy() if current_settings else {}
                        white_label_update[logo_field] = f"/storage/{file_location}"
                        
                        # Call GraphQL mutation to update white label settings
                        self._update_white_label(white_label_update)
                        logger.info(f"✓ Registered {folder_name} logo via GraphQL")
                    else:
                        logger.warning(f"Unknown folder name: {folder_name}, skipping GraphQL update")
                except Exception as e:
                    logger.warning(f"Could not register {folder_name} logo via GraphQL: {e}")
                    logger.warning("Logo file uploaded but may not appear in UI until registered")
            
            return response
        except FileNotFoundError:
            logger.error(f"Logo file not found: {logo_path}")
            raise
        except requests.exceptions.RequestException as e:
            # Log the response body for debugging
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Failed to upload {folder_name} logo: {e}")
                logger.error(f"Response status: {e.response.status_code}")
                logger.error(f"Response body: {e.response.text}")
            else:
                logger.error(f"Failed to upload {folder_name} logo: {e}")
            raise
    
    def _get_current_white_label_settings(self):
        """
        Get current white label settings to preserve existing values.
        Returns dict with whiteLabel fields or None if not available.
        
        Uses REST /bt/api/settings endpoint instead of GraphQL for better compatibility.
        """
        try:
            # Use REST endpoint instead of GraphQL (more reliable across versions)
            settings_url = f"{self.url}/settings"
            
            # Use cached settings if available
            if self._settings_cache is None:
                response = self.session.get(settings_url, headers=self.headers)
                response.raise_for_status()
                self._settings_cache = response.json()
            
            settings_data = self._settings_cache
            
            # Extract whiteLabel from settings
            if isinstance(settings_data, dict) and 'whiteLabel' in settings_data:
                return settings_data['whiteLabel']
            
            return {}
        except Exception as e:
            logger.debug(f"Could not get current white label settings: {e}")
            return {}
    
    def get_camera_groups(self):
        """
        Get all camera groups. Returns list of camera groups.
        """
        try:
            response = self.session.get(
                f"{self.url}/cameras/groups",
                headers=self.headers
            )
            response.raise_for_status()
            data = response.json()
            # Handle response format: {"cameraGroups": [...]}
            if isinstance(data, dict) and 'cameraGroups' in data:
                return data['cameraGroups']
            elif isinstance(data, list):
                return data
            else:
                return data
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get camera groups: {e}")
            raise
    
    def get_cameras(self, camera_id=""):
        """
        Get cameras. If camera_id is provided, get specific camera, otherwise get all cameras.
        
        Args:
            camera_id: Optional camera ID (empty string for all cameras)
        
        Returns:
            List of cameras or single camera object
        """
        try:
            url = f"{self.url}/cameras/{camera_id}" if camera_id else f"{self.url}/cameras"
            response = self.session.get(
                url,
                headers=self.headers
            )
            response.raise_for_status()
            data = response.json()
            # Handle response format: {"items": [...]} or direct list
            if isinstance(data, dict) and 'items' in data:
                return data['items']
            elif isinstance(data, list):
                return data
            elif isinstance(data, dict):
                return [data]  # Single camera
            else:
                return data
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get cameras: {e}")
            raise
    
    def create_camera_group(self, name, description="", alert_level=None):
        """
        Create a camera group.
        
        Args:
            name: Camera group name (title)
            description: Description (optional)
            alert_level: Alert level UUID (optional, uses default if not provided)
        
        Returns:
            Created camera group data
        """
        try:
            if not alert_level:
                # Use default alert level (Visible)
                alert_level = "00000000-0200-40e7-a33e-5f290f69366e"
            
            payload = {
                "title": name,
                "description": description,
                "alertLevel": alert_level,
                "isRestrictedGroup": False
            }
            
            response = self.session.post(
                f"{self.url}/cameras/groups",
                headers=self.headers,
                json=payload
            )
            response.raise_for_status()
            result = response.json()
            logger.info(f"Created camera group: {name} (id: {result.get('id')})")
            return result
        except requests.exceptions.RequestException as e:
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Failed to create camera group '{name}': {e}")
                logger.error(f"Response status: {e.response.status_code}")
                logger.error(f"Response body: {e.response.text}")
            else:
                logger.error(f"Failed to create camera group '{name}': {e}")
            raise
    
    def create_camera(self, name, video_url, camera_group_id, threshold, location=None, 
                     calibration=None, security_access=None, camera_mode=1, pipe=None):
        """
        Create a camera using GraphQL mutation.
        
        Args:
            name: Camera name (title)
            video_url: RTSP video URL
            camera_group_id: Camera group ID (UUID)
            threshold: Detection threshold
            location: [longitude, latitude] array or None
            calibration: Dict with calibration settings
            security_access: Dict with security access settings
            camera_mode: Camera mode (default: 1)
            pipe: Pipe name (optional)
        
        Returns:
            Created camera data
        """
        try:
            graphql_url = f"{self.url}/graphql"
            
            # Build configuration object
            configuration = {
                "cameraMode": [camera_mode],
                "cameraPadding": {
                    "top": "0",
                    "left": "0",
                    "right": "0",
                    "bottom": "0"
                },
                "frameRotation": -1,
                "frameSkip": {
                    "autoSkipEnabled": True,
                    "percent": 0
                },
                "livenessThreshold": 0.55,
                "detectionMaxBodySize": -1,
                "detectionMaxFaceSize": -1,
                "detectionMinBodySize": 20,
                "detectionMinFaceSize": 48,
                "ffmpegOptions": "",
                "trackBodyMaxLengthSec": 10,
                "trackBodyMinLengthSec": 0.2,
                "trackFaceMaxLengthSec": 10,
                "trackFaceMinLengthSec": 0.2,
                "trackerBodySeekTimeOutSec": 3,
                "trackerFaceSeekTimeOutSec": 3
            }
            
            # Apply calibration settings if provided
            if calibration:
                if 'tracker' in calibration:
                    configuration["trackerFaceSeekTimeOutSec"] = calibration['tracker']
                    configuration["trackerBodySeekTimeOutSec"] = calibration['tracker']
                
                if 'face_track_length' in calibration:
                    face_track = calibration['face_track_length']
                    if 'min' in face_track:
                        configuration["trackFaceMinLengthSec"] = face_track['min']
                    if 'max' in face_track:
                        configuration["trackFaceMaxLengthSec"] = face_track['max']
                
                if 'calibration_tool' in calibration:
                    cal_tool = calibration['calibration_tool']
                    if 'padding' in cal_tool:
                        padding = cal_tool['padding']
                        configuration["cameraPadding"] = {
                            "top": str(padding.get('top', 0)),
                            "left": str(padding.get('left', 0)),
                            "right": str(padding.get('right', 0)),
                            "bottom": str(padding.get('bottom', 0))
                        }
                    
                    if 'detection_min_size' in cal_tool:
                        configuration["detectionMinFaceSize"] = cal_tool['detection_min_size']
                        configuration["detectionMinBodySize"] = cal_tool['detection_min_size']
            
            # Apply security access settings if provided
            additional_settings = {
                "livenessEnabled": False,
                "maskClassifier": {
                    "access": False,
                    "defaultMaskAlertLevel": "Visible",
                    "enable": False,
                    "notification": True,
                    "shouldMaskOverrideHigherAlertLevel": False,
                    "threshold": 0.7
                }
            }
            
            if security_access:
                if 'liveness' in security_access:
                    additional_settings["livenessEnabled"] = security_access['liveness']
                
                if 'liveness_threshold' in security_access:
                    configuration["livenessThreshold"] = security_access['liveness_threshold']
            
            # Build location array [longitude, latitude]
            # Default location: lat: 51.50773019946536, long: -0.1279208857166907
            DEFAULT_LAT = 51.50773019946536
            DEFAULT_LONG = -0.1279208857166907
            
            location_array = None
            if location:
                if isinstance(location, dict):
                    location_name = location.get('name', '').lower()
                    # If location name is "default" or coordinates are missing, use defaults
                    if location_name == 'default' or (not location.get('long') and not location.get('lat')):
                        location_array = [DEFAULT_LONG, DEFAULT_LAT]
                    else:
                        long_val = location.get('long', DEFAULT_LONG)
                        lat_val = location.get('lat', DEFAULT_LAT)
                        location_array = [float(long_val), float(lat_val)]
                elif isinstance(location, list):
                    location_array = [float(location[0]), float(location[1])]
            else:
                # No location provided, use default
                location_array = [DEFAULT_LONG, DEFAULT_LAT]
            
            # Build camera input
            camera_input = {
                "isEnabled": True,
                "title": name,
                "cameraGroupId": camera_group_id,
                "pipe": pipe if pipe else "",
                "description": "",
                "threshold": float(threshold),
                "alternativeThreshold": None,
                "isAlternativeThresholdEnabled": False,
                "timeProfileId": None,
                "videoUrl": video_url,
                "configuration": configuration,
                "additionalSettings": additional_settings,
                "location": location_array,  # Always set location (default if not provided)
                "timezone": "",
                "streamType": 0,
                "isLoadBalancingEnabled": True
            }
            
            # GraphQL mutation
            mutation = """
            mutation createCamera($cameraInput: CameraObjectInput!) {
              createCamera(cameraInput: $cameraInput) {
                id
                title
                cameraGroup {
                  id
                  title
                }
                videoUrl
                threshold
                location
                isEnabled
              }
            }
            """
            
            payload = {
                "operationName": "createCamera",
                "variables": {
                    "cameraInput": camera_input
                },
                "query": mutation
            }
            
            response = self.session.post(
                graphql_url,
                headers=self.headers,
                json=payload
            )
            response.raise_for_status()
            
            result = response.json()
            if 'errors' in result:
                logger.error(f"GraphQL errors for createCamera: {result['errors']}")
                raise Exception(f"GraphQL error: {result['errors']}")
            
            camera_data = result.get('data', {}).get('createCamera', {})
            logger.info(f"Created camera: {name} (id: {camera_data.get('id')})")
            return camera_data
        except requests.exceptions.RequestException as e:
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Failed to create camera '{name}': {e}")
                logger.error(f"Response status: {e.response.status_code}")
                logger.error(f"Response body: {e.response.text}")
            else:
                logger.error(f"Failed to create camera '{name}': {e}")
            raise
    
    def get_inquiry_cases(self):
        """
        Get list of all inquiry cases.
        
        Returns:
            List of inquiry cases with their names and IDs
        """
        try:
            response = self.session.get(
                f"{self.url}/inquiry",
                headers=self.headers
            )
            response.raise_for_status()
            result = response.json()
            # Handle both list and dict with 'data' key
            if isinstance(result, list):
                return result
            elif isinstance(result, dict) and 'data' in result:
                return result['data']
            else:
                return []
        except requests.exceptions.RequestException as e:
            logger.debug(f"Failed to get inquiry cases: {e}")
            return []
    
    def create_inquiry_case(self, case_name, priority=None):
        """
        Create an inquiry case.
        
        Args:
            case_name: Name of the inquiry case
            priority: Priority level (optional, e.g., "Medium", "High", "Low", or numeric 1-1000)
        
        Returns:
            Created inquiry case data with 'id'
        
        Raises:
            InquiryCaseAlreadyExists: If case with same name already exists (409)
        """
        try:
            payload = {"name": case_name}
            
            # Add priority if provided (map string to number)
            if priority is not None:
                if isinstance(priority, str):
                    priority_lower = priority.lower()
                    if priority_lower in INQUIRY_PRIORITY_MAP:
                        payload["priority"] = INQUIRY_PRIORITY_MAP[priority_lower]
                    else:
                        logger.warning(f"Unknown priority string '{priority}', using default {INQUIRY_PRIORITY_DEFAULT} (Medium)")
                        payload["priority"] = INQUIRY_PRIORITY_DEFAULT
                elif isinstance(priority, (int, float)):
                    # Ensure it's in valid range (1-201 based on actual API values)
                    priority_num = max(INQUIRY_PRIORITY_HIGH, min(INQUIRY_PRIORITY_LOW, int(priority)))
                    payload["priority"] = priority_num
            
            response = self.session.post(
                f"{self.url}/inquiry",
                headers=self.headers,
                json=payload
            )
            
            # Check if case already exists (409 Conflict)
            if response.status_code == 409:
                try:
                    error_data = response.json()
                    if error_data.get('code') == 'ERR_CASE_NAME_ALREADY_EXISTS':
                        raise InquiryCaseAlreadyExists(f"Inquiry case '{case_name}' already exists: {error_data.get('message', '')}")
                except ValueError:
                    pass  # Not JSON, continue with normal error handling
            
            response.raise_for_status()
            result = response.json()
            inquiry_id = result.get("id")
            if not inquiry_id:
                raise ValueError(f"No 'id' returned in response: {result}")
            logger.info(f"Created inquiry case: {case_name} (id: {inquiry_id})")
            return result
        except InquiryCaseAlreadyExists:
            raise  # Re-raise as-is
        except requests.exceptions.RequestException as e:
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Failed to create inquiry case '{case_name}': {e}")
                logger.error(f"Response status: {e.response.status_code}")
                logger.error(f"Response body: {e.response.text}")
            else:
                logger.error(f"Failed to create inquiry case '{case_name}': {e}")
            raise
    
    def update_inquiry_case(self, inquiry_id, name=None, priority=None):
        """
        Update an inquiry case.
        
        Args:
            inquiry_id: Inquiry case ID
            name: New name (optional)
            priority: Priority level (optional, e.g., "Medium", "High", "Low", or numeric 1-1000)
        """
        try:
            data_to_update = {}
            if name is not None:
                data_to_update["name"] = name
            if priority is not None:
                # Map priority strings to numbers using constants
                if isinstance(priority, str):
                    priority_lower = priority.lower()
                    if priority_lower in INQUIRY_PRIORITY_MAP:
                        data_to_update["priority"] = INQUIRY_PRIORITY_MAP[priority_lower]
                    else:
                        logger.warning(f"Unknown priority string '{priority}', using default {INQUIRY_PRIORITY_DEFAULT} (Medium)")
                        data_to_update["priority"] = INQUIRY_PRIORITY_DEFAULT
                elif isinstance(priority, (int, float)):
                    # Ensure it's in valid range (1-201 based on actual API values)
                    priority_num = max(INQUIRY_PRIORITY_HIGH, min(INQUIRY_PRIORITY_LOW, int(priority)))
                    data_to_update["priority"] = priority_num
                else:
                    logger.warning(f"Invalid priority type '{type(priority)}', using default {INQUIRY_PRIORITY_DEFAULT} (Medium)")
                    data_to_update["priority"] = INQUIRY_PRIORITY_DEFAULT
            
            if not data_to_update:
                logger.warning("No fields to update in inquiry case")
                return
            
            payload = {"dataToUpdate": data_to_update}
            logger.debug(f"Updating inquiry case {inquiry_id} with payload: {payload}")
            response = self.session.patch(
                f"{self.url}/inquiry/{inquiry_id}",
                headers=self.headers,
                json=payload
            )
            response.raise_for_status()
            result = response.json()
            logger.info(f"Updated inquiry case {inquiry_id}: {data_to_update}")
            logger.debug(f"Update response: {result}")
            return result
        except requests.exceptions.RequestException as e:
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Failed to update inquiry case '{inquiry_id}': {e}")
                logger.error(f"Response status: {e.response.status_code}")
                logger.error(f"Response body: {e.response.text}")
            else:
                logger.error(f"Failed to update inquiry case '{inquiry_id}': {e}")
            raise
    
    def prepare_forensic_upload(self, file_name, with_analysis=True):
        """
        Prepare forensic file upload.
        
        Args:
            file_name: Name of the file to upload
            with_analysis: Whether to perform analysis (default: True)
        
        Returns:
            Response with upload ID
        """
        try:
            payload = {
                "name": file_name,
                "withAnalysis": with_analysis
            }
            response = self.session.post(
                f"{self.url}/upload/prepare/forensic",
                headers=self.headers,
                json=payload
            )
            response.raise_for_status()
            result = response.json()
            upload_id = result.get("id") or result.get("uploadId")
            if not upload_id:
                raise ValueError(f"No upload ID in response: {result}")
            logger.info(f"Prepared forensic upload: {file_name} (upload_id: {upload_id})")
            return result
        except requests.exceptions.RequestException as e:
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Failed to prepare forensic upload '{file_name}': {e}")
                logger.error(f"Response status: {e.response.status_code}")
                logger.error(f"Response body: {e.response.text}")
            else:
                logger.error(f"Failed to prepare forensic upload '{file_name}': {e}")
            raise
    
    def upload_forensic_file(self, file_path, upload_id):
        """
        Upload forensic file to the prepared upload ID.
        
        Args:
            file_path: Path to the file to upload
            upload_id: Upload ID from prepare_forensic_upload
        
        Returns:
            Upload response
        """
        try:
            filename = os.path.basename(file_path)
            file_extension = filename.split(".")[-1].lower() if "." in filename else ""
            
            # Determine file type
            image_extensions = ("jpg", "jpeg", "png", "bmp", "jfif", "tiff")
            filetype = "image" if file_extension in image_extensions else "video"
            
            # Get MIME type
            content_type = mimetypes.guess_type(filename)[0] or f"{filetype}/{file_extension}"
            
            # Read file content
            with open(file_path, 'rb') as f:
                file_content = f.read()
            
            files = {
                'file': (filename, file_content, content_type)
            }
            
            response = self.session.post(
                f"{self.url}/upload/file/{upload_id}?type={filetype}",
                headers=self.headers,
                files=files
            )
            response.raise_for_status()
            logger.info(f"Uploaded forensic file: {filename} (type: {filetype})")
            # Upload endpoint may return empty response - that's OK, upload succeeded
            # If response is empty or not JSON, that's fine - the upload succeeded (status 200)
            try:
                response_text = response.text.strip()
                if response_text:
                    try:
                        return response.json()
                    except (ValueError, TypeError) as json_error:
                        # Response is not valid JSON, but upload succeeded
                        logger.debug(f"Upload response is not JSON (this is OK): {response_text[:100]}")
                        return {"status": "success", "upload_id": upload_id}
                else:
                    # Empty response - upload succeeded
                    return {"status": "success", "upload_id": upload_id}
            except Exception as e:
                # Any other error parsing response - but upload succeeded (status 200)
                logger.debug(f"Could not parse upload response (this is OK): {e}")
                return {"status": "success", "upload_id": upload_id}
        except requests.exceptions.RequestException as e:
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Failed to upload forensic file '{file_path}': {e}")
                logger.error(f"Response status: {e.response.status_code}")
                logger.error(f"Response body: {e.response.text}")
            else:
                logger.error(f"Failed to upload forensic file '{file_path}': {e}")
            raise
    
    def add_file_to_inquiry_case(self, case_id, upload_id, filename, threshold=0.5):
        """
        Add uploaded file to inquiry case.
        
        Args:
            case_id: Inquiry case ID
            upload_id: Upload ID from prepare_forensic_upload
            filename: Name of the file
            threshold: Detection threshold (default: 0.5)
        
        Returns:
            Response with file ID
        """
        try:
            # Determine file type
            file_extension = filename.split(".")[-1].lower() if "." in filename else ""
            image_extensions = ("jpg", "jpeg", "png", "bmp", "jfif", "tiff")
            logical_file_type = 2 if file_extension in image_extensions else 1
            
            mimetype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
            
            # Get actual file size if file path is available
            # Note: We don't have file path here, so we'll use 0 and let API calculate
            file_size = 0
            
            payload = {
                "files": [
                    {
                        "uploadId": upload_id,
                        "filename": filename,
                        "captureDate": "2021-10-03T09:18:19.629Z",  # Default date, can be updated
                        "fileType": logical_file_type,
                        "size": file_size,
                        "mimeType": mimetype
                    }
                ],
                "threshold": threshold,
                "configuration": {
                    "cameraMode": [1]
                }
            }
            
            response = self.session.post(
                f"{self.url}/inquiry/{case_id}/add-files",
                headers=self.headers,
                json=payload
            )
            response.raise_for_status()
            # Endpoint may return empty response - that's OK, file was added
            try:
                response_text = response.text.strip()
                if response_text:
                    try:
                        result = response.json()
                        logger.info(f"Added file to inquiry case: {filename}")
                        return result
                    except (ValueError, TypeError) as json_error:
                        # Response is not valid JSON, but operation succeeded
                        logger.debug(f"Add file response is not JSON (this is OK): {response_text[:100]}")
                        return {"status": "success", "case_id": case_id, "upload_id": upload_id}
                else:
                    # Empty response - operation succeeded
                    logger.info(f"Added file to inquiry case: {filename}")
                    return {"status": "success", "case_id": case_id, "upload_id": upload_id}
            except Exception as e:
                # Any other error parsing response - but operation succeeded (status 200)
                logger.debug(f"Could not parse add file response (this is OK): {e}")
                logger.info(f"Added file to inquiry case: {filename}")
                return {"status": "success", "case_id": case_id, "upload_id": upload_id}
        except requests.exceptions.RequestException as e:
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Failed to add file to inquiry case: {e}")
                logger.error(f"Response status: {e.response.status_code}")
                logger.error(f"Response body: {e.response.text}")
            else:
                logger.error(f"Failed to add file to inquiry case: {e}")
            raise
    
    def get_inquiry_case_files(self, case_id):
        """
        Get files in an inquiry case via GraphQL.
        
        Args:
            case_id: Inquiry case ID
        
        Returns:
            List of files with their IDs
        """
        try:
            graphql_url = f"{self.url}/graphql"
            
            query = """
            query getCase($id: ID!) {
              getCase(id: $id) {
                id
                files {
                  uploadId
                  caseId
                  fileName
                  fileType
                  status
                  analysisProgress
                  cameraId
                  storagePath
                }
              }
            }
            """
            
            payload = {
                "operationName": "getCase",
                "variables": {"id": case_id},
                "query": query
            }
            
            response = self.session.post(
                graphql_url,
                headers=self.headers,
                json=payload
            )
            response.raise_for_status()
            result = response.json()
            if 'errors' in result:
                logger.error(f"GraphQL errors for getCase: {result['errors']}")
                raise Exception(f"GraphQL error: {result['errors']}")
            
            case_data = result.get('data', {}).get('getCase', {})
            files = case_data.get('files', [])
            return files
        except requests.exceptions.RequestException as e:
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Failed to get inquiry case files: {e}")
                logger.error(f"Response status: {e.response.status_code}")
                logger.error(f"Response body: {e.response.text}")
            else:
                logger.error(f"Failed to get inquiry case files: {e}")
            raise
    
    def update_file_media_data(self, file_id, threshold=None, camera_padding=None, pipe=None):
        """
        Update file media data via GraphQL mutation.
        Used to configure ROI (Region of Interest) and threshold for specific files.
        
        Args:
            file_id: File ID (uploadId from get_inquiry_case_files)
            threshold: Recognition sensitive threshold (optional)
            camera_padding: Dict with {top, left, right, bottom} for ROI (optional)
            pipe: Pipe name (optional, usually "cv-engine-0.cv-engine.default:9970")
        
        Returns:
            Update response
        """
        try:
            graphql_url = f"{self.url}/graphql"
            
            # Build dataToUpdate object - matching the UI payload structure
            default_pipe = pipe if pipe else "cv-engine-0.cv-engine.default:9970"
            
            # Use current timestamp for captureDate (matching second UI example)
            current_date = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            
            data_to_update = {
                "fileType": 1,  # Video file
                "captureDate": current_date,  # Current date (matching UI format)
                "threshold": float(threshold) if threshold is not None else 0.5,
                "pipe": default_pipe,
                "configuration": {
                    "frameSkip": {
                        "percent": 0,
                        "autoSkipEnabled": False
                    },
                    "cameraPadding": {
                        "top": str(camera_padding.get('top', 0)) if camera_padding else "0",
                        "left": str(camera_padding.get('left', 0)) if camera_padding else "0",
                        "right": str(camera_padding.get('right', 0)) if camera_padding else "0",
                        "bottom": str(camera_padding.get('bottom', 0)) if camera_padding else "0"
                    },
                    "webRTC": False,
                    "preview": False,
                    "ffmpegOptions": "",
                    "frameRotation": -1,
                    "livenessThreshold": 0.55,
                    "enableFrameStorage": True,
                    "trackBodyMaxLengthSec": 10,
                    "trackBodyMinLengthSec": 0.2,
                    "trackFaceMaxLengthSec": 10,
                    "trackFaceMinLengthSec": 0.2,
                    "trackerBodySeekTimeOutSec": 3,
                    "trackerFaceSeekTimeOutSec": 3,
                    "detectionMaxBodySize": -1,
                    "detectionMaxFaceSize": -1,
                    "detectionMinBodySize": 20,
                    "detectionMinFaceSize": 48,
                    "cameraMode": [1],
                    "startSeconds": 0,
                    "stopSeconds": 293,  # Can be null or a number - using 293 as default
                    "pipe": default_pipe
                }
            }
            
            mutation = """
            mutation updateFileMediaData($id: ID!, $dataToUpdate: UpdateFileMediaData!) {
              updateFileMediaData(id: $id, dataToUpdate: $dataToUpdate) {
                code
              }
            }
            """
            
            payload = {
                "operationName": "updateFileMediaData",
                "variables": {
                    "id": file_id,
                    "dataToUpdate": data_to_update
                },
                "query": mutation
            }
            
            response = self.session.post(
                graphql_url,
                headers=self.headers,
                json=payload
            )
            response.raise_for_status()
            
            result = response.json()
            if 'errors' in result:
                logger.error(f"GraphQL errors for updateFileMediaData: {result['errors']}")
                raise Exception(f"GraphQL error: {result['errors']}")
            
            logger.info(f"Updated file media data: {file_id}")
            return result
        except requests.exceptions.RequestException as e:
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Failed to update file media data '{file_id}': {e}")
                logger.error(f"Response status: {e.response.status_code}")
                logger.error(f"Response body: {e.response.text}")
            else:
                logger.error(f"Failed to update file media data '{file_id}': {e}")
            raise
    
    def start_analyze_files_case(self, case_id, file_ids):
        """
        Start or restart analysis for files in an inquiry case.
        
        Args:
            case_id: Inquiry case ID
            file_ids: List of file IDs (cameraId/uploadId) to analyze
        
        Returns:
            Analysis start response
        """
        try:
            graphql_url = f"{self.url}/graphql"
            
            # Build entitiesData array
            entities_data = []
            for file_id in file_ids:
                entities_data.append({
                    "cameraId": file_id,
                    "fileType": 1  # Video file
                })
            
            mutation = """
            mutation startAnalyzeFilesCase($id: ID!, $entitiesData: [CamerasDataUpdate!]) {
              startAnalyzeFilesCase(id: $id, entitiesData: $entitiesData) {
                updateFailedFilesIds
                updatedFiles {
                  status
                  cameraId
                  analysisProgress
                }
              }
            }
            """
            
            payload = {
                "operationName": "startAnalyzeFilesCase",
                "variables": {
                    "id": case_id,
                    "entitiesData": entities_data
                },
                "query": mutation
            }
            
            response = self.session.post(
                graphql_url,
                headers=self.headers,
                json=payload
            )
            response.raise_for_status()
            
            result = response.json()
            if 'errors' in result:
                logger.error(f"GraphQL errors for startAnalyzeFilesCase: {result['errors']}")
                raise Exception(f"GraphQL error: {result['errors']}")
            
            logger.info(f"Started analysis for {len(file_ids)} file(s) in case")
            return result
        except requests.exceptions.RequestException as e:
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Failed to start analysis: {e}")
                logger.error(f"Response status: {e.response.status_code}")
                logger.error(f"Response body: {e.response.text}")
            else:
                logger.error(f"Failed to start analysis: {e}")
            raise
    
    def check_subjects_quota(self):
        """
        Check subjects quota before uploading mass import.
        
        Returns:
            Quota information
        """
        try:
            response = self.session.get(
                f"{self.url}/app-licensing/validation/quota/subjects",
                headers=self.headers
            )
            response.raise_for_status()
            result = response.json()
            logger.debug(f"Subjects quota check: {result}")
            return result
        except requests.exceptions.RequestException as e:
            logger.warning(f"Could not check subjects quota: {e}")
            # Don't fail if quota check fails, just log warning
            return None
    
    def prepare_mass_import_upload(self, name, subject_group_ids, is_search_backwards=False, duplication_threshold=0.61):
        """
        Prepare mass import upload.
        
        Args:
            name: Name for the mass import
            subject_group_ids: List of subject group IDs to attach the import to
            is_search_backwards: Whether to search backwards (default: False)
            duplication_threshold: Duplication threshold (default: 0.61)
        
        Returns:
            Response with upload ID
        """
        try:
            payload = {
                "name": name,
                "subjectGroups": subject_group_ids,
                "isSearchBackwards": is_search_backwards,
                "duplicationThreshold": duplication_threshold
            }
            response = self.session.post(
                f"{self.url}/upload/prepare/mass-import",
                headers=self.headers,
                json=payload
            )
            response.raise_for_status()
            result = response.json()
            upload_id = result.get("id") or result.get("uploadId")
            if not upload_id:
                raise ValueError(f"No upload ID in response: {result}")
            logger.info(f"Prepared mass import upload: {name} (upload_id: {upload_id})")
            return result
        except requests.exceptions.RequestException as e:
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Failed to prepare mass import upload '{name}': {e}")
                logger.error(f"Response status: {e.response.status_code}")
                logger.error(f"Response body: {e.response.text}")
            else:
                logger.error(f"Failed to prepare mass import upload '{name}': {e}")
            raise
    
    def upload_mass_import_file(self, file_path, upload_id):
        """
        Upload mass import tar file to the prepared upload ID.
        
        Args:
            file_path: Path to the tar file to upload
            upload_id: Upload ID from prepare_mass_import_upload
        
        Returns:
            Upload response
        """
        try:
            filename = os.path.basename(file_path)
            file_extension = filename.split(".")[-1].lower() if "." in filename else ""
            
            # Determine file type from extension (tar, zip, etc.)
            filetype = file_extension if file_extension else "tar"  # Default to tar if no extension
            
            # MIME type format: application/{filetype} (e.g., application/tar, application/zip)
            content_type = f"application/{filetype}"
            
            # Read file content
            with open(file_path, 'rb') as f:
                file_content = f.read()
            
            files = {
                'file': (filename, file_content, content_type)
            }
            
            # Use /upload/extract/{upload_id} endpoint (not /upload/file/{upload_id})
            response = self.session.post(
                f"{self.url}/upload/extract/{upload_id}",
                headers=self.headers,
                files=files
            )
            
            # Check if mass import already exists (should be treated as skip, not error)
            if response.status_code == 400:
                try:
                    error_data = response.json()
                    if error_data.get('code') == 'ERR_MASS_IMPORT_IN_PROGRESS_OR_WITH_ISSUES':
                        # Mass import with same name already exists - this is a skip, not an error
                        raise MassImportAlreadyExists(f"Mass import with the same name already exists: {error_data.get('message', '')}")
                except ValueError:
                    pass  # Not JSON, continue with normal error handling
            
            response.raise_for_status()
            logger.info(f"Uploaded mass import file: {filename}")
            # Upload endpoint may return empty response - that's OK
            try:
                if response.text.strip():
                    return response.json()
                else:
                    return {"status": "success", "upload_id": upload_id}
            except ValueError:
                return {"status": "success", "upload_id": upload_id}
        except MassImportAlreadyExists:
            # Re-raise as-is (will be caught and handled as skip)
            raise
        except requests.exceptions.RequestException as e:
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Failed to upload mass import file '{file_path}': {e}")
                logger.error(f"Response status: {e.response.status_code}")
                logger.error(f"Response body: {e.response.text}")
            else:
                logger.error(f"Failed to upload mass import file '{file_path}': {e}")
            raise
    
    def get_mass_import_status(self, mass_import_id):
        """
        Get mass import status via GraphQL query.
        
        Args:
            mass_import_id: Mass import ID (from prepare response)
        
        Returns:
            Mass import data with status, progress, and metadata
        """
        try:
            graphql_url = f"{self.url}/graphql"
            
            query = """
            query getMassImportLists($offset: Int, $limit: Int, $sortOrder: String, $withJobFileMetrics: Boolean, $filters: [Filter]) {
              getMassImportLists(
                offset: $offset
                limit: $limit
                sortOrder: $sortOrder
                withJobFileMetrics: $withJobFileMetrics
                filters: $filters
              ) {
                items {
                  id
                  name
                  status
                  progress
                  reportUrl
                  metadata {
                    isIssuesResolved
                    initialIssueCount
                    initialSubjectsCount
                  }
                }
                total
              }
            }
            """
            
            # Get current date range (last 30 days to current)
            from_date = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            to_date = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            
            payload = {
                "operationName": "getMassImportLists",
                "variables": {
                    "offset": 0,
                    "limit": 200,
                    "sortOrder": "desc",
                    "withJobFileMetrics": True,
                    "filters": [
                        {"field": "from", "value": from_date},
                        {"field": "to", "value": to_date}
                    ]
                },
                "query": query
            }
            
            response = self.session.post(
                graphql_url,
                headers=self.headers,
                json=payload
            )
            response.raise_for_status()
            result = response.json()
            if 'errors' in result:
                logger.error(f"GraphQL errors for getMassImportLists: {result['errors']}")
                raise Exception(f"GraphQL error: {result['errors']}")
            
            # Find the mass import by ID
            items = result.get('data', {}).get('getMassImportLists', {}).get('items', [])
            for item in items:
                if item.get('id') == mass_import_id:
                    return item
            
            return None
        except requests.exceptions.RequestException as e:
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Failed to get mass import status: {e}")
                logger.error(f"Response status: {e.response.status_code}")
                logger.error(f"Response body: {e.response.text}")
            else:
                logger.error(f"Failed to get mass import status: {e}")
            raise
    
    def _update_white_label(self, white_label_updates):
        """
        Update white label settings via REST PATCH endpoint (preferred) or GraphQL mutation (fallback).
        
        Args:
            white_label_updates: Dict with whiteLabel fields to update
                e.g., {"productName": "...", "favicon": "...", "companyLogo": "...", "sidebarLogo": "..."}
        """
        # Log what we're trying to update
        logger.debug(f"Updating white label with: {white_label_updates}")
        
        # Try REST PATCH first (more reliable, especially for 2.8)
        try:
            settings_url = f"{self.url}/settings"
            payload = {
                "whiteLabel": white_label_updates
            }
            
            logger.debug(f"Updating white label via REST PATCH: {payload}")
            
            response = self.session.patch(
                settings_url,
                headers=self.headers,
                json=payload
            )
            response.raise_for_status()
            
            # Verify the update by getting the settings back
            verify_response = self.session.get(settings_url, headers=self.headers)
            verify_response.raise_for_status()
            updated_settings = verify_response.json()
            
            # Clear cache so next GET gets fresh data
            self._settings_cache = None
            
            updated_white_label = updated_settings.get('whiteLabel', {})
            logger.debug(f"Updated white label settings from REST response: {updated_white_label}")
            
            # Verify the update actually worked
            for key, expected_value in white_label_updates.items():
                actual_value = updated_white_label.get(key)
                if actual_value != expected_value:
                    logger.warning(f"White label field '{key}' mismatch: expected '{expected_value}', got '{actual_value}'")
                else:
                    logger.debug(f"White label field '{key}' updated correctly: '{actual_value}'")
            
            logger.info("✓ White label settings updated via REST PATCH")
            return updated_settings
            
        except Exception as rest_error:
            logger.debug(f"REST PATCH failed for white label update: {rest_error}, trying GraphQL fallback...")
            
            # Fallback to GraphQL mutation
            try:
                graphql_url = f"{self.url}/graphql"
                
                # GraphQL mutation - matches what the browser sends
                mutation = """
                mutation updateWhiteLabel($applicationSettings: ApplicationSettingsInput) {
                  updateSettings(applicationSettings: $applicationSettings) {
                    defaultLanguage
                    whiteLabel {
                      productName
                      companyLogo
                      sidebarLogo
                      favicon
                    }
                  }
                }
                """
                
                payload = {
                    "operationName": "updateWhiteLabel",
                    "variables": {
                        "applicationSettings": {
                            "whiteLabel": white_label_updates
                        }
                    },
                    "query": mutation
                }
                
                # Log the payload for debugging
                logger.debug(f"White label GraphQL payload (fallback): {payload}")
                
                response = self.session.post(
                    graphql_url,
                    headers=self.headers,
                    json=payload
                )
                response.raise_for_status()
                
                result = response.json()
                if 'errors' in result:
                    logger.error(f"GraphQL errors for updateWhiteLabel: {result['errors']}")
                    # Log full error details
                    logger.error(f"Full error response: {result}")
                    raise Exception(f"GraphQL error: {result['errors']}")
                
                # Log the response for debugging
                logger.debug(f"White label update response (GraphQL): {result}")
                if 'data' in result and 'updateSettings' in result['data']:
                    updated_white_label = result['data']['updateSettings'].get('whiteLabel', {})
                    logger.debug(f"Updated white label settings from GraphQL response: {updated_white_label}")
                    # Verify the update actually worked
                    for key, expected_value in white_label_updates.items():
                        actual_value = updated_white_label.get(key)
                        if actual_value != expected_value:
                            logger.warning(f"White label field '{key}' mismatch: expected '{expected_value}', got '{actual_value}'")
                        else:
                            logger.debug(f"White label field '{key}' updated correctly: '{actual_value}'")
                
                logger.info("✓ White label settings updated via GraphQL (fallback)")
                return result
            except Exception as graphql_error:
                logger.error(f"Both REST PATCH and GraphQL failed for white label update")
                logger.error(f"REST error: {rest_error}")
                logger.error(f"GraphQL error: {graphql_error}")
                raise Exception(f"Failed to update white label settings via both REST and GraphQL: REST={rest_error}, GraphQL={graphql_error}")
    
    def _get_kv_parameter_via_rest(self, key):
        """
        Try to get KV parameter via REST endpoints.
        
        Args:
            key: Parameter key
            
        Returns:
            Parameter value as string, or None if not found
        """
        logger.debug(f"Trying REST endpoints for KV parameter: {key}")
        
        # Get version-specific endpoints (or use defaults from constants)
        try:
            version_endpoints = self.version_compat.get_kv_parameter_endpoints()
            rest_endpoints = [f"{self.url}{endpoint}" for endpoint in version_endpoints]
        except Exception:
            # Fallback to constants if version compat not available
            rest_endpoints = [f"{self.url}{endpoint}" for endpoint in KV_PARAMETER_ENDPOINTS]
        
        for endpoint in rest_endpoints:
            try:
                response = self.session.get(endpoint, headers=self.headers)
                logger.debug(f"REST endpoint {endpoint} response: {response.status_code}")
                
                if response.status_code == 200:
                    try:
                        data = response.json()
                        logger.debug(f"Parsing response from {endpoint}, type: {type(data).__name__}")
                        
                        # Try to find the key in the response
                        if isinstance(data, list):
                            for item in data:
                                if isinstance(item, dict) and item.get('key') == key:
                                    value = item.get('value', '')
                                    logger.debug(f"Found key '{key}' in list response from {endpoint}")
                                    return str(value)
                        elif isinstance(data, dict):
                            # Check if key is directly in dict
                            if key in data:
                                value = str(data[key])
                                logger.debug(f"Found key '{key}' directly in dict from {endpoint}")
                                return value
                            # Check if there's a list of settings
                            if 'items' in data:
                                for item in data['items']:
                                    if isinstance(item, dict) and item.get('key') == key:
                                        value = str(item.get('value', ''))
                                        logger.debug(f"Found key '{key}' in items list from {endpoint}")
                                        return value
                            # Check nested structures
                            for section_name, section in data.items():
                                if isinstance(section, dict) and key in section:
                                    value = str(section[key])
                                    logger.debug(f"Found key '{key}' in nested section '{section_name}' from {endpoint}")
                                    return value
                    except ValueError:
                        # Response is not JSON
                        logger.debug(f"Response from {endpoint} is not JSON")
                        pass
            except Exception as e:
                logger.debug(f"REST endpoint {endpoint} failed: {e}")
                continue
        
        logger.debug(f"Key '{key}' not found in any REST endpoint")
        return None
    
    def _get_kv_parameter_via_graphql(self, key):
        """
        Get a KV parameter value using GraphQL query.
        
        This method queries KV parameters via GraphQL, which is needed for
        parameters that aren't available in the REST /settings endpoint,
        such as keys starting with 'DEFAULT/'.
        
        Args:
            key: Parameter key (e.g., 'DEFAULT/collate-service/TRACKS_RETENTION_TIME_MS')
            
        Returns:
            Parameter value as string, or None if not found
        """
        try:
            graphql_url = f"{self.url}/graphql"
            
            # Try multiple GraphQL query patterns to find the one that works
            # Pattern 1: Query all key-value settings
            query_all = """
            query {
              settings {
                keyValueSettings {
                  key
                  value
                }
              }
            }
            """
            
            # Pattern 2: Try to query a single setting by key (if API supports it)
            query_single = """
            query getSetting($key: String!) {
              getSetting(key: $key) {
                key
                value
              }
            }
            """
            
            # Pattern 3: Query settings with keyValueSettings as a list
            query_list = """
            query {
              keyValueSettings {
                key
                value
              }
            }
            """
            
            # Pattern 4: Try querying all settings (mirroring the mutation structure)
            query_all_settings = """
            query {
              settings {
                keyValueSettings {
                  key
                  value
                }
              }
            }
            """
            
            # Pattern 5: Try getSingleSetting query (mirroring updateSingleSetting mutation)
            query_single_mirror = """
            query getSingleSetting($key: String!) {
              getSingleSetting(key: $key) {
                key
                value
              }
            }
            """
            
            # Try Pattern 1 first: query all settings with keyValueSettings
            try:
                payload = {
                    "query": query_all
                }
                
                response = self.session.post(
                    graphql_url,
                    headers=self.headers,
                    json=payload
                )
                logger.debug(f"GraphQL Pattern 1 response: {response.status_code}")
                
                result = response.json() if response.status_code == 200 else None
                if response.status_code != 200:
                    logger.debug(f"GraphQL Pattern 1 error: HTTP {response.status_code}")
                    raise Exception(f"HTTP {response.status_code}: {response.text[:200]}")
                
                if 'errors' in result:
                    logger.debug(f"GraphQL Pattern 1 returned errors: {result.get('errors')}")
                    # Check if it's a schema error (field doesn't exist)
                    errors = result['errors']
                    error_messages = ' '.join(str(e) for e in errors).lower()
                    if 'keyvaluesettings' not in error_messages and 'cannot query field' not in error_messages:
                        # Not a schema error, might be something else
                        logger.debug(f"GraphQL query returned errors (but might be recoverable): {errors}")
                    else:
                        # Schema doesn't support keyValueSettings, try other patterns
                        raise Exception("keyValueSettings field not available")
                
                # Extract settings from response
                if 'data' in result and 'settings' in result['data']:
                    settings = result['data']['settings']
                    if 'keyValueSettings' in settings:
                        # Find the setting with matching key
                        kv_settings = settings['keyValueSettings']
                        if isinstance(kv_settings, list):
                            for setting in kv_settings:
                                if setting.get('key') == key:
                                    value = setting.get('value', '')
                                    logger.debug(f"Found KV parameter '{key}' via GraphQL: {value}")
                                    return str(value)
                        elif isinstance(kv_settings, dict):
                            # If it's a dict, might be keyed by the key itself
                            if key in kv_settings:
                                value = kv_settings[key].get('value', '') if isinstance(kv_settings[key], dict) else str(kv_settings[key])
                                logger.debug(f"Found KV parameter '{key}' via GraphQL: {value}")
                                return str(value)
            except Exception as e1:
                logger.debug(f"Pattern 1 (settings.keyValueSettings) failed: {e1}, trying Pattern 2...")
                
                # Try Pattern 2: query single setting
                try:
                    payload = {
                        "operationName": "getSetting",
                        "variables": {
                            "key": key
                        },
                        "query": query_single
                    }
                    
                    response = self.session.post(
                        graphql_url,
                        headers=self.headers,
                        json=payload
                    )
                    logger.debug(f"GraphQL Pattern 2 response: {response.status_code}")
                    
                    result = response.json() if response.status_code == 200 else None
                    if response.status_code != 200:
                        logger.debug(f"GraphQL Pattern 2 error: HTTP {response.status_code}")
                        raise Exception(f"HTTP {response.status_code}: {response.text[:200]}")
                    
                    if 'errors' not in result:
                        if 'data' in result and 'getSetting' in result['data']:
                            setting = result['data']['getSetting']
                            if setting and 'value' in setting:
                                value = setting['value']
                                logger.debug(f"Found KV parameter '{key}' via GraphQL (getSetting): {value}")
                                return str(value)
                    else:
                        logger.debug(f"GraphQL Pattern 2 returned errors: {result.get('errors')}")
                except Exception as e2:
                    logger.debug(f"Pattern 2 (getSetting) failed: {e2}, trying Pattern 3...")
                    
                    # Try Pattern 3: direct keyValueSettings query
                    try:
                        payload = {
                            "query": query_list
                        }
                        
                        response = self.session.post(
                            graphql_url,
                            headers=self.headers,
                            json=payload
                        )
                        logger.debug(f"GraphQL Pattern 3 response: {response.status_code}")
                        
                        result = response.json() if response.status_code == 200 else None
                        if response.status_code != 200:
                            logger.debug(f"GraphQL Pattern 3 error: HTTP {response.status_code}")
                            raise Exception(f"HTTP {response.status_code}: {response.text[:200]}")
                        
                        if 'errors' not in result:
                            if 'data' in result and 'keyValueSettings' in result['data']:
                                kv_settings = result['data']['keyValueSettings']
                                if isinstance(kv_settings, list):
                                    for setting in kv_settings:
                                        if setting.get('key') == key:
                                            value = setting.get('value', '')
                                            logger.debug(f"Found KV parameter '{key}' via GraphQL (direct query): {value}")
                                            return str(value)
                        else:
                            logger.debug(f"GraphQL Pattern 3 returned errors: {result.get('errors')}")
                    except Exception as e3:
                        logger.debug(f"Pattern 3 (direct keyValueSettings) also failed: {e3}, trying Pattern 4...")
                        
                        # Try Pattern 4: query all settings (alternative structure)
                        try:
                            payload = {
                                "query": query_all_settings
                            }
                            
                            response = self.session.post(
                                graphql_url,
                                headers=self.headers,
                                json=payload
                            )
                            logger.debug(f"GraphQL Pattern 4 response: {response.status_code}")
                            
                            result = response.json() if response.status_code == 200 else None
                            if response.status_code != 200:
                                logger.debug(f"GraphQL Pattern 4 error: HTTP {response.status_code}")
                                raise Exception(f"HTTP {response.status_code}: {response.text[:200]}")
                            
                            if 'errors' not in result and 'data' in result:
                                # Try different response structures
                                data = result['data']
                                if 'settings' in data and isinstance(data['settings'], dict):
                                    settings = data['settings']
                                    if 'keyValueSettings' in settings:
                                        kv_settings = settings['keyValueSettings']
                                        if isinstance(kv_settings, list):
                                            for setting in kv_settings:
                                                if setting.get('key') == key:
                                                    value = setting.get('value', '')
                                                    logger.debug(f"Found KV parameter '{key}' via GraphQL (Pattern 4): {value}")
                                                    return str(value)
                            elif 'errors' in result:
                                logger.debug(f"GraphQL Pattern 4 returned errors: {result.get('errors')}")
                        except Exception as e4:
                            logger.debug(f"Pattern 4 also failed: {e4}, trying Pattern 5...")
                            
                            # Try Pattern 5: getSingleSetting (mirroring updateSingleSetting)
                            try:
                                payload = {
                                    "operationName": "getSingleSetting",
                                    "variables": {
                                        "key": key
                                    },
                                    "query": query_single_mirror
                                }
                                
                                response = self.session.post(
                                    graphql_url,
                                    headers=self.headers,
                                    json=payload
                                )
                                logger.debug(f"GraphQL Pattern 5 response: {response.status_code}")
                                
                                result = response.json() if response.status_code == 200 else None
                                if response.status_code != 200:
                                    logger.debug(f"GraphQL Pattern 5 error: HTTP {response.status_code}")
                                    raise Exception(f"HTTP {response.status_code}: {response.text[:200]}")
                                
                                if 'errors' not in result:
                                    if 'data' in result and 'getSingleSetting' in result['data']:
                                        setting = result['data']['getSingleSetting']
                                        if setting and 'value' in setting:
                                            value = setting['value']
                                            logger.debug(f"Found KV parameter '{key}' via GraphQL (getSingleSetting): {value}")
                                            return str(value)
                                elif 'errors' in result:
                                    logger.debug(f"GraphQL Pattern 5 returned errors: {result.get('errors')}")
                            except Exception as e5:
                                logger.debug(f"Pattern 5 (getSingleSetting) also failed: {e5}")
            
            logger.debug(f"KV parameter '{key}' not found in any GraphQL query pattern")
            return None
            
        except Exception as e:
            logger.debug(f"Could not get KV parameter {key} via GraphQL: {e}")
            return None
    
    def get_kv_parameter(self, key):
        """
        Get a KV parameter value using REST API endpoint, with GraphQL fallback.
        
        First tries REST /bt/api/settings endpoint for keys starting with 'applicationSettings/'.
        Falls back to GraphQL for keys starting with 'DEFAULT/' or if REST lookup fails.
        
        Args:
            key: Parameter key (e.g., 'applicationSettings/watchVideo/secondsAfterDetection' or 'DEFAULT/collate-service/TRACKS_RETENTION_TIME_MS')
            
        Returns:
            Parameter value as string, or None if not found
        """
        # For keys starting with 'DEFAULT/', try REST first, then GraphQL
        if key.startswith('DEFAULT/'):
            logger.debug(f"KV parameter key '{key}' uses DEFAULT prefix - trying REST endpoints first")
            rest_result = self._get_kv_parameter_via_rest(key)
            logger.debug(f"REST result for '{key}': {rest_result is not None}")
            if rest_result is not None:
                return rest_result
            logger.debug(f"REST endpoints failed for '{key}', trying GraphQL...")
            return self._get_kv_parameter_via_graphql(key)
        
        try:
            # Try REST endpoint first for 'applicationSettings/' keys
            # Cache the settings response to avoid multiple API calls
            if self._settings_cache is None:
                settings_url = f"{self.url}/settings"
                response = self.session.get(settings_url, headers=self.headers)
                response.raise_for_status()
                self._settings_cache = response.json()
                logger.debug(f"Settings cache loaded, top-level keys: {list(self._settings_cache.keys())[:10] if isinstance(self._settings_cache, dict) else 'not_dict'}")
            
            settings_data = self._settings_cache
            
            # Map KV parameter key to nested path in settings response
            # Examples:
            # 'applicationSettings/watchVideo/secondsAfterDetection' -> watchVideo.secondsAfterDetection
            # 'applicationSettings/maskClassifier/threshold' -> maskClassifier.threshold
            # 'applicationSettings/defaultFaceThreshold' -> defaultFaceThreshold (but this is also a system setting)
            
            # Remove 'applicationSettings/' prefix if present
            if key.startswith('applicationSettings/'):
                path = key.replace('applicationSettings/', '')
                # Convert path to nested dictionary access
                parts = path.split('/')
                
                # Navigate nested structure
                value = settings_data
                for i, part in enumerate(parts):
                    if isinstance(value, dict) and part in value:
                        value = value[part]
                    else:
                        # Path not found in settings - try GraphQL as fallback
                        logger.debug(f"KV parameter key '{key}' not found in REST settings response, trying GraphQL...")
                        return self._get_kv_parameter_via_graphql(key)
                
                # Convert to string for consistency
                return str(value) if value is not None else None
            else:
                # Try direct key lookup
                if key in settings_data:
                    return str(settings_data[key])
                
                # Not found in REST - check if it's a DEFAULT/ key and try REST endpoints, then GraphQL
                if key.startswith('DEFAULT/'):
                    logger.debug(f"KV parameter key '{key}' not found in /settings, trying REST KV endpoints...")
                    rest_result = self._get_kv_parameter_via_rest(key)
                    if rest_result is not None:
                        return rest_result
                    logger.debug(f"REST KV endpoints failed, trying GraphQL...")
                    return self._get_kv_parameter_via_graphql(key)
                else:
                    # Not found in REST - try GraphQL as fallback
                    logger.debug(f"KV parameter key '{key}' not found in REST settings response, trying GraphQL...")
                    return self._get_kv_parameter_via_graphql(key)
                
        except Exception as e:
            logger.debug(f"REST lookup failed for KV parameter {key}: {e}, trying GraphQL...")
            # If REST fails, try GraphQL as fallback
            return self._get_kv_parameter_via_graphql(key)
    
    def get_system_settings(self):
        """
        Get system settings via REST API endpoint.
        
        Uses GET /bt/api/settings to retrieve system settings separately from KV parameters.
        This ensures we get the actual system settings, not KV parameters.
        
        Returns:
            Dictionary with system settings or None if error
        """
        try:
            # Use REST endpoint to get system settings separately from KV parameters
            settings_url = f"{self.url}/settings"
            response = self.session.get(settings_url, headers=self.headers)
            response.raise_for_status()
            
            settings_data = response.json()
            
            # Map REST API response fields to our validation structure
            # The REST API returns fields like defaultFaceThreshold, defaultBodyThreshold, etc.
            result = {}
            
            # Map the fields we validate
            if 'defaultFaceThreshold' in settings_data:
                result['defaultFaceThreshold'] = float(settings_data['defaultFaceThreshold'])
            if 'defaultBodyThreshold' in settings_data:
                result['defaultBodyThreshold'] = float(settings_data['defaultBodyThreshold'])
            if 'cameraDefaultLivenessTh' in settings_data:
                result['cameraDefaultLivenessTh'] = float(settings_data['cameraDefaultLivenessTh'])
            if 'bodyImageTtlH' in settings_data:
                result['bodyImageTtlH'] = int(settings_data['bodyImageTtlH'])
            if 'whiteLabel' in settings_data:
                result['whiteLabel'] = settings_data['whiteLabel']
            
            return result
            
        except Exception as e:
            logger.debug(f"Could not get system settings: {e}")
            return None

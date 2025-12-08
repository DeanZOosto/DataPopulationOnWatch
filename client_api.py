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

# Disable SSL warnings for self-signed certificates
urllib3.disable_warnings(InsecureRequestWarning)

logger = logging.getLogger(__name__)

# Add support for additional image types
mimetypes.add_type('image/jpeg', '.jfif')


class ClientApi:
    """Client API for interacting with OnWatch system."""
    
    def __init__(self, ip_address, username, password):
        """
        Initialize the ClientApi.
        
        Args:
            ip_address: IP address of the OnWatch system
            username: Username for authentication
            password: Password for authentication
        """
        self.ip_address = ip_address
        self.username = username
        self.password = password
        self.url = f"https://{ip_address}/bt/api"
        self.headers = {"accept": "application/json"}
        self.token = ""
        self.session = requests.Session()
        self.session.verify = False
        
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
            return response
            
        except requests.exceptions.RequestException as e:
            print(f"Login failed: {e}")
            raise
    
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
            logger.error(f"Image file not found: {image_path}")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to extract faces from {extract_url}: {e}")
            raise
    
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
                logger.error(f"Failed to add subject. Status: {response.status_code}, Response: {response.text}")
                logger.error(f"Payload sent: {payload}")
            
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
    
    def add_image_to_subject(self, subject_id, image_path):
        """
        Add an additional image to an existing subject.
        
        Args:
            subject_id: ID of the subject
            image_path: Path to the image file
            
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
            
            # Add new image (not primary)
            new_image = {
                "objectType": data["objectType"],
                "isPrimary": False,  # Additional images are not primary
                "featuresQuality": data["featuresQuality"],
                "url": data["url"],
                "features": data["features"],
                "landmarkScore": data["landmarkScore"]
            }
            
            existing_images.append(new_image)
            
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
    
    def get_subjects(self):
        """Get all subjects."""
        try:
            response = self.session.get(
                f"{self.url}/subjects",
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()
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
            
            # GraphQL mutation - matches what the browser sends
            payload = {
                "operationName": "updateSingleSetting",
                "variables": {
                    "settingInput": {
                        "key": key,
                        "value": str(value)  # Convert to string as API expects
                    }
                },
                "query": "mutation updateSingleSetting($settingInput: KeyValueSettingInput!) {\n  updateSingleSetting(settingInput: $settingInput) {\n    code\n  }\n}\n"
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
                logger.error(f"GraphQL errors for {key}: {result['errors']}")
                raise Exception(f"GraphQL error: {result['errors']}")
            
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
            response.raise_for_status()
            result = response.json()
            logger.info(f"Created acknowledge action: {title} (id: {result.get('id')})")
            return result
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
        """
        try:
            graphql_url = f"{self.url}/graphql"
            query = """
            query {
              settings {
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
                logger.warning(f"Could not get current white label settings: {result['errors']}")
                return None
            
            if 'data' in result and 'settings' in result['data']:
                return result['data']['settings'].get('whiteLabel', {})
            
            return None
        except Exception as e:
            logger.warning(f"Could not get current white label settings: {e}")
            return None
    
    def _update_white_label(self, white_label_updates):
        """
        Update white label settings via GraphQL mutation.
        
        Args:
            white_label_updates: Dict with whiteLabel fields to update
                e.g., {"productName": "...", "favicon": "...", "companyLogo": "...", "sidebarLogo": "..."}
        """
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
            
            response = self.session.post(
                graphql_url,
                headers=self.headers,
                json=payload
            )
            response.raise_for_status()
            
            result = response.json()
            if 'errors' in result:
                logger.error(f"GraphQL errors for updateWhiteLabel: {result['errors']}")
                raise Exception(f"GraphQL error: {result['errors']}")
            
            return result
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to update white label settings: {e}")
            raise

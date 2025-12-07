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
    
    def get_groups(self):
        """Get all groups. Returns list of groups or dict with 'items' key."""
        try:
            response = self.session.get(
                f"{self.url}/groups",
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
            print(f"Failed to get groups: {e}")
            raise
    
    def create_group(self, name):
        """Create a new group."""
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
            print(f"Failed to create group: {e}")
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
            print(f"Failed to get subjects: {e}")
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
            with open(logo_path, 'rb') as f:
                files = {"files": (filename, f, content_type)}
                response = self.session.post(
                    f"{self.url}/upload/static-files/{upload_uuid}",
                    headers=self.headers,
                    files=files
                )
                response.raise_for_status()
                logger.info(f"Uploaded {folder_name} logo: {filename}")
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

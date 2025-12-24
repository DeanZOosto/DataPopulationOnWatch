#!/usr/bin/env python3
"""
Main automation script for populating OnWatch system with data.
This script orchestrates automation tasks via REST API, GraphQL API, and Rancher configuration.
"""
import asyncio
import os
import sys
import logging
import time
from pathlib import Path
from client_api import ClientApi
from rancher_api import RancherApi
from ssh_util import SSHUtil
from run_summary import RunSummary
from config_manager import ConfigManager
from constants import (
    INQUIRY_PRIORITY_MAP,
    INQUIRY_PRIORITY_DEFAULT,
    ANALYSIS_WAIT_DELAY,
    FILE_STATUS_CHECK_DELAY,
    RETRY_DELAY,
    FILE_ANALYSIS_CHECK_INTERVAL
)

# Store original exception hook for verbose mode
_original_excepthook = sys.excepthook

def _clean_excepthook(exc_type, exc_value, exc_traceback):
    """Custom exception handler that suppresses traceback unless in verbose mode."""
    # Check if verbose/debug mode is enabled
    root_logger = logging.getLogger()
    if root_logger.level <= logging.DEBUG:
        # Show full traceback in verbose mode
        _original_excepthook(exc_type, exc_value, exc_traceback)
    else:
        # In normal mode, suppress traceback (our error handlers will show user-friendly messages)
        # Only print the exception type and message, not the full traceback
        error_msg = str(exc_value) if exc_value else str(exc_type)
        # Don't print anything - our logging system already handles it with user-friendly messages
        pass

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'  # Removes milliseconds
)
logger = logging.getLogger(__name__)


# RunSummary class moved to run_summary.py


class OnWatchAutomation:
    """Main automation orchestrator."""
    
    def __init__(self, config_path="config.yaml"):
        """
        Initialize automation with configuration.
        
        Args:
            config_path: Path to YAML configuration file
        """
        self.config_path = config_path
        self.config_manager = ConfigManager(config_path)
        self.config = self.config_manager.load_config()
        self.client_api = None
        self.rancher_automation = None
        self.summary = RunSummary()
    
    def validate_config(self, verbose=False):
        """
        Validate configuration file structure and values.
        
        Args:
            verbose: If True, print detailed validation report
            
        Returns:
            tuple: (is_valid, errors_list)
        """
        return self.config_manager.validate_config(verbose=verbose)
    
    def initialize_api_client(self):
        """
        Initialize the OnWatch API client and authenticate.
        
        Reads OnWatch connection details from config.yaml (onwatch section)
        and establishes authenticated session with the OnWatch system.
        
        Raises:
            Exception: If authentication fails or connection cannot be established
        """
        onwatch_config = self.config['onwatch']
        # Get version from config (required)
        version = onwatch_config.get('version')
        if not version:
            raise ValueError("OnWatch version is required. Set 'onwatch.version' in config.yaml (e.g., '2.6' or '2.8')")
        
        logger.info(f"Using OnWatch version from config: {version}")
        
        self.client_api = ClientApi(
            ip_address=onwatch_config['ip_address'],
            username=onwatch_config['username'],
            password=onwatch_config['password'],
            version=version
        )
        self.client_api.login()
        
        # Store version in summary
        self.summary.onwatch_version = version
        logger.info(f"API client initialized and logged in (OnWatch {version})")
    
    async def set_kv_parameters(self):
        """
        Set key-value parameters via GraphQL API.
        
        Reads KV parameters from config.yaml (kv_parameters section) and
        applies them to the OnWatch system using GraphQL mutations.
        
        Config Section: kv_parameters
        Example:
            kv_parameters:
              "applicationSettings/watchVideo/secondsAfterDetection": 6
        """
        kv_params = self.config.get('kv_parameters', {})
        if not kv_params:
            logger.info("No KV parameters to set")
            return
        
        logger.info("Setting KV parameters...")
        
        # Initialize client if needed
        if not self.client_api:
            self.initialize_api_client()
        
        # Set each KV parameter
        for key, value in kv_params.items():
            try:
                self.client_api.set_kv_parameter(key, value)
                logger.info(f"✓ Set KV parameter: {key} = {value}")
                # Track created item
                self.summary.add_created_item('kv_parameters', {'key': key, 'value': str(value)})
            except Exception as e:
                error_str = str(e).lower()
                # Check if error indicates value already exists or is already set correctly
                if any(phrase in error_str for phrase in ['already exists', 'already set', 'no change', 'unchanged', 'duplicate']):
                    logger.debug(f"KV parameter {key} already has value {value} (or already exists), skipping")
                    # Don't log as error - this is expected behavior
                else:
                    logger.error(f"Failed to set KV parameter {key}: {e}")
                    self.summary.add_error("KV Parameter", key, str(e))
                # Continue with next parameter instead of stopping
                continue
    
    async def configure_system_settings(self):
        """
        Configure system settings via REST API.
        
        Configures general, map, engine, and system interface settings.
        Also handles acknowledge actions and logo uploads.
        
        Config Section: system_settings
        Includes:
            - General settings (thresholds, retention periods)
            - Map settings (seed location, acknowledge actions)
            - Engine settings (storage periods)
            - System interface (product name, logos, favicon, translation file)
        """
        system_settings = self.config.get('system_settings', {})
        if not system_settings:
            logger.info("No system settings to configure")
            return
        
        logger.info("Configuring system settings...")
        
        # Try API first - initialize client if needed
        if not self.client_api:
            self.initialize_api_client()
        
        try:
            self.client_api.update_system_settings(system_settings)
            logger.info("✓ System settings configured via API")
            
            # Verify and store actual values that were set (not just config values)
            # Query back the actual system settings to store what's really in the system
            time.sleep(FILE_STATUS_CHECK_DELAY)  # Brief wait for settings to be saved
            actual_system_settings = self.client_api.get_system_settings()
            
            # Build verified system settings dict with actual values
            verified_settings = {}
            if actual_system_settings:
                # Map actual values back to config structure
                if 'general' in system_settings:
                    verified_general = {}
                    if 'default_face_threshold' in system_settings['general']:
                        actual_value = actual_system_settings.get('defaultFaceThreshold')
                        if actual_value is not None:
                            verified_general['default_face_threshold'] = float(actual_value)
                    if 'default_body_threshold' in system_settings['general']:
                        actual_value = actual_system_settings.get('defaultBodyThreshold')
                        if actual_value is not None:
                            verified_general['default_body_threshold'] = float(actual_value)
                    if 'default_liveness_threshold' in system_settings['general']:
                        actual_value = actual_system_settings.get('cameraDefaultLivenessTh')
                        if actual_value is not None:
                            verified_general['default_liveness_threshold'] = float(actual_value)
                    if verified_general:
                        verified_settings['general'] = verified_general
                
                if 'system_interface' in system_settings:
                    verified_interface = {}
                    if 'product_name' in system_settings['system_interface']:
                        actual_value = actual_system_settings.get('whiteLabel', {}).get('productName')
                        if actual_value:
                            verified_interface['product_name'] = actual_value
                    if verified_interface:
                        verified_settings['system_interface'] = verified_interface
            
            # Track system settings with verified actual values (fallback to config if verification failed)
            settings_to_store = verified_settings if verified_settings else system_settings
            self.summary.add_created_item('system_settings', settings_to_store)
            
            # Handle acknowledge actions separately
            if 'map' in system_settings:
                map_settings = system_settings['map']
                if 'acknowledge' in map_settings and map_settings['acknowledge']:
                    try:
                        self.client_api.enable_acknowledge_actions(True)
                        logger.info("✓ Acknowledge actions enabled")
                    except Exception as e:
                        logger.warning(f"Could not enable acknowledge actions: {e}")
                        logger.warning("Continuing with other settings...")
                
                if 'action_title' in map_settings and map_settings['action_title']:
                    try:
                        from client_api import AcknowledgeActionAlreadyExists
                        try:
                            self.client_api.create_acknowledge_action(map_settings['action_title'], description="")
                            logger.info(f"✓ Created acknowledge action: {map_settings['action_title']}")
                        except AcknowledgeActionAlreadyExists:
                            logger.info(f"⏭️  Acknowledge action '{map_settings['action_title']}' already exists, skipping")
                            self.summary.add_skipped("Acknowledge Action", map_settings['action_title'], "already exists")
                    except Exception as e:
                        logger.warning(f"Could not create acknowledge action: {e}")
                        logger.warning("Continuing with other settings...")
            
            # Handle logo and favicon uploads (read from config.yaml)
            system_interface = system_settings.get('system_interface', {})
            project_root = os.path.dirname(os.path.abspath(self.config_path))
            
            # Upload company and sidebar logos
            logos = system_interface.get('logos', {})
            if logos:
                for logo_type in ["company", "sidebar"]:
                    logo_path_config = logos.get(logo_type)
                    if logo_path_config:
                        # Resolve path (relative to project root or absolute)
                        if not os.path.isabs(logo_path_config):
                            logo_path = os.path.join(project_root, logo_path_config)
                        else:
                            logo_path = logo_path_config
                        
                        if os.path.exists(logo_path):
                            try:
                                self.client_api.upload_logo(logo_path, logo_type)
                                logger.info(f"✓ Uploaded {logo_type} logo from: {logo_path_config}")
                                # Track uploaded logo under system_interface
                                self.summary.add_created_item('logo', {
                                    'type': logo_type,
                                    'source_file': os.path.basename(logo_path),
                                    'path': logo_path_config,  # Store relative path for config consistency
                                    'resolved_path': logo_path
                                })
                            except Exception as e:
                                logger.warning(f"Could not upload {logo_type} logo from '{logo_path_config}': {e}")
                                logger.warning("Continuing with other settings...")
                        else:
                            logger.warning(f"Logo file not found: {logo_path_config} (resolved: {logo_path})")
                    else:
                        logger.debug(f"No {logo_type} logo configured in config.yaml (optional, skipping)")
            else:
                logger.debug("No logos configured in config.yaml (optional, skipping)")
            
            # Upload favicon
            favicon_path_config = system_interface.get('favicon')
            if favicon_path_config:
                # Resolve path (relative to project root or absolute)
                if not os.path.isabs(favicon_path_config):
                    favicon_path = os.path.join(project_root, favicon_path_config)
                else:
                    favicon_path = favicon_path_config
                
                if os.path.exists(favicon_path):
                    try:
                        self.client_api.upload_logo(favicon_path, "favicon")
                        logger.info(f"✓ Uploaded favicon from: {favicon_path_config}")
                        # Track uploaded favicon under system_interface
                        self.summary.add_created_item('logo', {
                            'type': 'favicon',
                            'source_file': os.path.basename(favicon_path),
                            'path': favicon_path_config,  # Store relative path for config consistency
                            'resolved_path': favicon_path
                        })
                    except Exception as e:
                        logger.warning(f"Could not upload favicon from '{favicon_path_config}': {e}")
                else:
                    logger.warning(f"Favicon file not found: {favicon_path_config} (resolved: {favicon_path})")
            else:
                logger.debug("No favicon configured in config.yaml (optional, skipping)")
                
        except Exception as e:
            logger.error(f"Failed to configure system settings via API: {e}")
            raise
    
    async def configure_devices(self):
        """
        Configure cameras/devices via GraphQL API.
        
        Creates cameras with full configuration including thresholds, locations,
        calibration settings, and security access settings.
        Automatically skips cameras that already exist.
        
        Config Section: devices
        Example:
            devices:
              - name: "face camera"
                video_url: "rtsp://..."
                details:
                  threshold: 0.5
                  location:
                    name: "holon"
                    lat: 32.007
                    long: 34.800
        """
        devices = self.config.get('devices', [])
        if not devices:
            logger.info("No devices to configure")
            return
        
        logger.info("Configuring devices/cameras...")
        
        # Initialize API client if needed
        if not self.client_api:
            self.initialize_api_client()
        
        # Get or create camera groups
        camera_group_map = {}  # name -> id
        try:
            camera_groups = self.client_api.get_camera_groups()
            if isinstance(camera_groups, list):
                for cg in camera_groups:
                    if isinstance(cg, dict):
                        title = cg.get('title', '')
                        cg_id = cg.get('id')
                        if title and cg_id:
                            camera_group_map[title.lower()] = cg_id
            logger.debug(f"Found {len(camera_group_map)} existing camera groups")
        except Exception as e:
            logger.warning(f"Could not get camera groups: {e}")
        
        # Get device groups from config to map to camera groups
        device_groups_config = self.config.get('groups', {}).get('device_groups', [])
        default_camera_group_id = None
        
        # Try to create camera groups from device groups config if they don't exist
        for device_group in device_groups_config:
            dg_name = device_group.get('name', '').strip()
            if dg_name and dg_name.lower() not in camera_group_map:
                try:
                    dg_description = device_group.get('description', '')
                    cg_response = self.client_api.create_camera_group(dg_name, dg_description)
                    if isinstance(cg_response, dict):
                        cg_id = cg_response.get('id')
                        camera_group_map[dg_name.lower()] = cg_id
                        logger.info(f"Created camera group: {dg_name}")
                        if not default_camera_group_id:
                            default_camera_group_id = cg_id
                except Exception as e:
                    logger.warning(f"Could not create camera group '{dg_name}': {e}")
            elif dg_name:
                # Use existing camera group
                if not default_camera_group_id:
                    default_camera_group_id = camera_group_map.get(dg_name.lower())
        
        # If no camera groups, create a default one
        if not camera_group_map and not default_camera_group_id:
            try:
                logger.info("No camera groups found, creating default camera group...")
                cg_response = self.client_api.create_camera_group("Default Camera Group", "Default camera group")
                if isinstance(cg_response, dict):
                    default_camera_group_id = cg_response.get('id')
                    camera_group_map["default camera group"] = default_camera_group_id
            except Exception as e:
                logger.warning(f"Could not create default camera group: {e}")
        
        # Get existing cameras to check for duplicates
        existing_camera_names = set()
        try:
            existing_cameras = self.client_api.get_cameras()
            if isinstance(existing_cameras, list):
                for cam in existing_cameras:
                    if isinstance(cam, dict):
                        title = cam.get('title', '').strip()
                        if title:
                            existing_camera_names.add(title.lower())
            logger.debug(f"Found {len(existing_camera_names)} existing cameras")
        except Exception as e:
            logger.warning(f"Could not fetch existing cameras: {e}")
            existing_camera_names = set()
        
        # Create each camera
            logger.debug(f"Creating {len(devices)} cameras...")
        created_count = 0
        skipped_count = 0
        
        for device_config in devices:
            try:
                name = device_config.get('name', '').strip()
                if not name:
                    logger.warning(f"Device missing name: {device_config}")
                    skipped_count += 1
                    continue
                
                # Check for duplicates
                if name.lower() in existing_camera_names:
                    logger.info(f"⏭️  Camera '{name}' already exists, skipping")
                    self.summary.add_skipped("Camera", name, "already exists")
                    skipped_count += 1
                    continue
                
                video_url = device_config.get('video_url', '').strip()
                if not video_url:
                    logger.warning(f"Device '{name}' missing video_url, skipping")
                    skipped_count += 1
                    continue
                
                # Get camera group ID (use default if not specified)
                camera_group_id = default_camera_group_id
                # TODO: Add camera_group field to config if needed
                
                details = device_config.get('details', {})
                threshold = details.get('threshold', 0.5)
                location = details.get('location', {})
                
                calibration = device_config.get('calibration', {})
                security_access = device_config.get('security_access', {})
                
                # Determine camera mode based on name
                # camera_mode: 1 = face, 2 = body
                camera_mode = 2 if "body" in name.lower() else 1
                
                # Create camera via GraphQL
                camera_response = self.client_api.create_camera(
                    name=name,
                    video_url=video_url,
                    camera_group_id=camera_group_id,
                    threshold=threshold,
                    location=location,
                    calibration=calibration,
                    security_access=security_access,
                    camera_mode=camera_mode
                )
                logger.info(f"✓ Created camera: {name} (mode: {'body' if camera_mode == 2 else 'face'})")
                created_count += 1
                existing_camera_names.add(name.lower())  # Track created camera
                
                # Track created camera
                try:
                    camera_data = camera_response.json() if hasattr(camera_response, 'json') else {}
                    camera_id = camera_data.get('id') or camera_data.get('cameraId') or 'unknown'
                    self.summary.add_created_item('cameras', {
                        'name': name,
                        'id': camera_id,
                        'video_url': video_url,
                        'mode': 'body' if camera_mode == 2 else 'face'
                    })
                except Exception:
                    self.summary.add_created_item('cameras', {
                        'name': name,
                        'id': 'unknown',
                        'video_url': video_url,
                        'mode': 'body' if camera_mode == 2 else 'face'
                    })
                
            except Exception as e:
                camera_name = device_config.get('name', 'unknown')
                error_detail = str(e)
                logger.error(f"❌ Failed to create camera '{camera_name}': {error_detail}")
                logger.warning(f"⚠️  Camera '{camera_name}' was not created. You may need to create it manually in the UI.")
                self.summary.add_warning(f"Camera '{camera_name}' was not created - manual action may be needed")
                self.summary.add_error("Camera", camera_name, error_detail)
                skipped_count += 1
        
        logger.info(f"Devices configuration complete: {created_count} created, {skipped_count} skipped")
    
    def populate_watch_list(self):
        """
        Populate watch list with subjects via REST API.
        
        Adds subjects to the watch list with their images. Automatically
        skips subjects that already exist (duplicate detection).
        
        Config Section: watch_list.subjects
        Example:
            watch_list:
              subjects:
                - name: "Yonatan"
                  images:
                    - path: "assets/images/me.jpg"
                  group: "Default Group"
        
        Returns:
            None (logs success/failure counts)
        """
        watch_list_config = self.config.get('watch_list', {})
        # Handle both old format (list) and new format (dict with 'subjects')
        if isinstance(watch_list_config, dict):
            watch_list = watch_list_config.get('subjects', [])
        else:
            watch_list = watch_list_config if isinstance(watch_list_config, list) else []
        
        if not watch_list:
            logger.info("No watch list items to add")
            return
        
        logger.info(f"Populating watch list with {len(watch_list)} subjects...")
        
        # Initialize API client if not already done
        if not self.client_api:
            self.initialize_api_client()
        
        # Get project root directory (where main.py is located) for resolving relative image paths
        project_root = os.path.dirname(os.path.abspath(__file__))
        
        # Get groups mapping (name -> id)
        group_map = {}
        default_group_id = None
        try:
            groups = self.client_api.get_groups()
            # Handle case where groups might be a number or different format
            if isinstance(groups, list):
                group_map = {g.get('name'): g.get('id') for g in groups if isinstance(g, dict) and g.get('name')}
                # Get first group as default if available
                if groups and isinstance(groups[0], dict):
                    default_group_id = groups[0].get('id')
            elif isinstance(groups, dict) and 'items' in groups:
                items = groups.get('items', [])
                group_map = {g.get('name'): g.get('id') for g in items if isinstance(g, dict) and g.get('name')}
                # Get first group as default if available
                if items and isinstance(items[0], dict):
                    default_group_id = items[0].get('id')
            
            logger.debug(f"Found {len(group_map)} groups")
        except Exception as e:
            logger.warning(f"Could not get groups: {e}")
        
        # Try to create default group if none found (for clean system)
        if not group_map and not default_group_id:
            try:
                logger.info("No groups found, attempting to create default group for clean system...")
                # Use create_subject_group with proper defaults for clean system
                group_response = self.client_api.create_subject_group(
                    name="Default Group",
                    authorization="Always Unauthorized",
                    visibility="Silent",
                    priority=0,
                    description="Default group created automatically"
                )
                if isinstance(group_response, dict):
                    default_group_id = group_response.get('id')
                    logger.info(f"Created default group with ID: {default_group_id}")
                    # Update group_map with the newly created group
                    group_map["Default Group"] = default_group_id
            except Exception as e:
                logger.warning(f"Could not create default group: {e}")
        
        # Track success/failure counts
        success_count = 0
        failed_count = 0
        skipped_count = 0
        
        # Get existing subjects to check for duplicates
        # Use fetch_all=True to ensure we get ALL subjects (handles pagination on 2.8)
        existing_subject_names = set()
        existing_subjects = None
        try:
            existing_subjects = self.client_api.get_subjects(fetch_all=True)
            # Handle different response formats
            if isinstance(existing_subjects, list):
                subjects_list = existing_subjects
            elif isinstance(existing_subjects, dict) and 'items' in existing_subjects:
                subjects_list = existing_subjects['items']
            else:
                subjects_list = []
            
            for subj in subjects_list:
                if isinstance(subj, dict):
                    subj_name = subj.get('name', '')
                    if subj_name:
                        existing_subject_names.add(subj_name.lower())
            
            logger.info(f"Found {len(existing_subject_names)} existing subjects in system (for duplicate check)")
            logger.debug(f"Existing subject names: {sorted(existing_subject_names)}")
        except Exception as e:
            logger.warning(f"Could not fetch existing subjects for duplicate check: {e}")
            logger.warning("Continuing anyway - will try to add subjects and handle duplicate errors if they occur")
            # Continue anyway - will try to add and handle errors if duplicate
        
        for subject in watch_list:
            try:
                if not isinstance(subject, dict):
                    logger.warning(f"Invalid subject format: {subject}")
                    continue
                
                name = subject.get('name')
                if not name:
                    logger.warning(f"Subject missing name: {subject}")
                    continue
                
                images = subject.get('images', [])
                group_name = subject.get('group', 'Default Group')
                group_id = group_map.get(group_name) or default_group_id
                
                if not group_id:
                    logger.warning(f"Group '{group_name}' not found and no default group available. Subject will be added without group assignment.")
                
                if not images:
                    logger.warning(f"No images specified for subject: {name}")
                    continue
                
                # Get first image path
                first_image = images[0] if isinstance(images[0], dict) else {'path': images[0]}
                image_path = first_image.get('path') if isinstance(first_image, dict) else first_image
                
                if not image_path:
                    logger.warning(f"No image path specified for subject: {name}")
                    continue
                
                # Resolve relative paths to absolute paths (relative to project root)
                if not os.path.isabs(image_path):
                    image_path = os.path.join(project_root, image_path)
                
                # Check if file exists
                if not os.path.exists(image_path):
                    logger.warning(f"Image file not found: {image_path}")
                    continue
                
                # Check if subject already exists
                if name.lower() in existing_subject_names:
                    # Get the actual subject to check images
                    try:
                        # existing_subjects is already a list when fetch_all=True
                        existing_subjects_list = existing_subjects if isinstance(existing_subjects, list) else (existing_subjects.get('items', []) if isinstance(existing_subjects, dict) else [])
                        existing_subject = next((s for s in existing_subjects_list if isinstance(s, dict) and s.get('name', '').lower() == name.lower()), None)
                        
                        if existing_subject:
                            existing_images = existing_subject.get('images', [])
                            existing_image_count = len(existing_images)
                            required_image_count = len(images)
                            
                            if existing_image_count >= required_image_count:
                                logger.info(f"⏭️  Subject '{name}' already exists with {existing_image_count} image(s) (required: {required_image_count}), skipping")
                                self.summary.add_skipped("Subject", name, "already exists with all images")
                                skipped_count += 1
                                continue
                            else:
                                # Subject exists but missing images - add missing ones
                                logger.info(f"⚠️  Subject '{name}' exists but has {existing_image_count} image(s), needs {required_image_count}. Adding missing images...")
                                subject_id = existing_subject.get('id')
                                if subject_id:
                                    # Get existing image URLs to avoid duplicates
                                    existing_urls = {img.get('url', '') for img in existing_images if img.get('url')}
                                    
                                    # Add missing images
                                    for img_info in images[existing_image_count:]:
                                        img_path = img_info.get('path') if isinstance(img_info, dict) else img_info
                                        if img_path:
                                            if not os.path.isabs(img_path):
                                                img_path = os.path.join(project_root, img_path)
                                            
                                            if os.path.exists(img_path):
                                                try:
                                                    # Extract to get URL for duplicate check
                                                    extract_response = self.client_api.extract_faces_from_image(img_path)
                                                    extract_data = extract_response.json()
                                                    items = extract_data.get("items", []) if "items" in extract_data else (extract_data if isinstance(extract_data, list) else [extract_data])
                                                    if items and items[0].get('url') not in existing_urls:
                                                        # Get first image data from existing subject for fallback
                                                        first_img_data = existing_images[0] if existing_images else None
                                                        self.client_api.add_image_to_subject(subject_id, img_path, first_img_data)
                                                        logger.info(f"✓ Added missing image to existing subject '{name}': {os.path.basename(img_path)}")
                                                    else:
                                                        logger.debug(f"Image already exists for {name}: {os.path.basename(img_path)}")
                                                except Exception as e:
                                                    logger.warning(f"Could not add missing image to {name}: {e}")
                                    self.summary.add_skipped("Subject", name, f"existed, added {required_image_count - existing_image_count} missing image(s)")
                                    skipped_count += 1
                                    continue
                    except Exception as e:
                        logger.debug(f"Could not check existing subject images: {e}, skipping duplicate check")
                        # Fall back to simple skip
                        logger.info(f"⏭️  Subject '{name}' already exists, skipping")
                        self.summary.add_skipped("Subject", name, "already exists")
                        skipped_count += 1
                        continue
                
                # Extract face data from first image BEFORE creating subject
                # This ensures we have first_image_data even if API response doesn't include it
                first_image_data = None
                try:
                    extract_response = self.client_api.extract_faces_from_image(image_path)
                    extract_data = extract_response.json()
                    
                    # Handle different response formats
                    if "items" in extract_data:
                        items = extract_data["items"]
                    elif isinstance(extract_data, list):
                        items = extract_data
                    else:
                        items = [extract_data]
                    
                    if items:
                        data = items[0]
                        # Construct first_image_data in the same format as add_subject_from_image uses
                        first_image_data = {
                            "objectType": data.get("objectType", 1),
                            "isPrimary": True,
                            "featuresQuality": data.get("featuresQuality", 0),
                            "url": data.get("url"),
                            "features": data.get("features", []),
                            "landmarkScore": data.get("landmarkScore", 0)
                        }
                        # Add optional fields if present
                        if "featuresId" in data:
                            first_image_data["featuresId"] = data["featuresId"]
                        if "backup" in data:
                            first_image_data["backup"] = data["backup"]
                        if "attributes" in data:
                            first_image_data["attributes"] = data["attributes"]
                        if "feNetwork" in data:
                            first_image_data["feNetwork"] = data["feNetwork"]
                        logger.debug(f"Extracted first image data from extract response for {name}")
                except Exception as e:
                    logger.debug(f"Could not extract first image data: {e}")
                
                # Add subject with first image
                response = self.client_api.add_subject_from_image(name, image_path, group_id)
                logger.info(f"✓ Added subject to watch list: {name} (image: {os.path.basename(image_path)})")
                success_count += 1
                
                # Track created subject
                try:
                    subject_data = response.json() if hasattr(response, 'json') else {}
                    subject_id = subject_data.get('id')
                    self.summary.add_created_item('subjects', {
                        'name': name,
                        'id': subject_id or 'unknown',
                        'images': len(images)
                    })
                except Exception:
                    # Fallback if response parsing fails
                    self.summary.add_created_item('subjects', {
                        'name': name,
                        'id': 'unknown',
                        'images': len(images)
                    })
                
                # Add additional images immediately if any (e.g., Yonatan has 2 images)
                if len(images) > 1:
                    try:
                        if not subject_id:
                            subject_data = response.json() if hasattr(response, 'json') else {}
                            subject_id = subject_data.get('id')
                        
                        if subject_id:
                            for additional_img_info in images[1:]:
                                additional_img_path = additional_img_info.get('path') if isinstance(additional_img_info, dict) else additional_img_info
                                
                                if additional_img_path:
                                    # Resolve relative paths
                                    if not os.path.isabs(additional_img_path):
                                        additional_img_path = os.path.join(project_root, additional_img_path)
                                    
                                    if os.path.exists(additional_img_path):
                                        try:
                                            # Pass first_image_data as fallback in case API doesn't return existing images yet
                                            self.client_api.add_image_to_subject(subject_id, additional_img_path, first_image_data)
                                            logger.info(f"✓ Added additional image to {name}: {os.path.basename(additional_img_path)}")
                                        except Exception as e:
                                            error_detail = str(e)
                                            logger.error(f"❌ Failed to add additional image '{additional_img_path}' to subject '{name}': {error_detail}")
                                            logger.warning(f"⚠️  Subject '{name}' was created but additional image was not added. You may need to add it manually in the UI.")
                                            self.summary.add_warning(f"Subject '{name}': Additional image '{os.path.basename(additional_img_path)}' not added - manual action may be needed")
                                    else:
                                        logger.warning(f"Additional image file not found: {additional_img_path}")
                                else:
                                    logger.warning(f"Additional image path is empty for {name}")
                        else:
                            logger.warning(f"Could not get subject ID to add additional images for {name}")
                    except Exception as e:
                        logger.warning(f"Could not process additional images for {name}: {e}")
                
            except Exception as e:
                subject_name = subject.get('name', 'unknown') if isinstance(subject, dict) else 'unknown'
                error_detail = str(e)
                logger.error(f"❌ Failed to add subject '{subject_name}': {error_detail}")
                logger.warning(f"⚠️  Subject '{subject_name}' was not added. You may need to add it manually in the UI.")
                self.summary.add_warning(f"Subject '{subject_name}' was not added - manual action may be needed")
                self.summary.add_error("Subject", subject_name, error_detail)
                failed_count += 1
        
        # Log summary
        if failed_count == 0 and skipped_count == 0:
            logger.info(f"✓ Watch list population complete: {success_count} subjects added")
        elif failed_count == 0:
            logger.info(f"✓ Watch list population complete: {success_count} added, {skipped_count} skipped")
        elif success_count > 0:
            logger.warning(f"⚠️  Watch list population partial: {success_count} succeeded, {failed_count} failed, {skipped_count} skipped")
        else:
            logger.error(f"❌ Watch list population failed: all {failed_count} subjects failed, {skipped_count} skipped")
    
    async def configure_groups(self):
        """
        Configure subject groups via REST API.
        
        Creates subject groups with authorization, visibility, and priority settings.
        Automatically skips groups that already exist (fuzzy matching).
        
        Config Section: groups.subject_groups
        Example:
            groups:
              subject_groups:
                - name: "Cardholders"
                  authorization: "Always Authorized"
                  visibility: "Visible"
                  priority: 2
        """
        groups = self.config.get('groups', {})
        if not groups:
            logger.info("No groups to configure")
            return
        
        logger.info("Configuring groups and profiles...")
        
        # Initialize API client if needed
        if not self.client_api:
            self.initialize_api_client()
        
        # Process subject groups
        subject_groups = groups.get('subject_groups', [])
        if subject_groups:
            logger.debug(f"Creating {len(subject_groups)} subject groups...")
            
            # Helper function to check if two names are similar (handles plural/singular, case differences)
            def names_match(name1, name2):
                """Check if two group names are essentially the same (handles plural/singular variations)."""
                n1 = name1.lower().strip()
                n2 = name2.lower().strip()
                
                # Exact match (case-insensitive)
                if n1 == n2:
                    return True
                
                # Check if one is the other + 's' or vice versa (plural/singular)
                if n1 + 's' == n2 or n2 + 's' == n1:
                    return True
                if n1 + 'es' == n2 or n2 + 'es' == n1:
                    return True
                if (n1.endswith('s') and n1[:-1] == n2) or (n2.endswith('s') and n2[:-1] == n1):
                    return True
                if (n1.endswith('es') and n1[:-2] == n2) or (n2.endswith('es') and n2[:-2] == n1):
                    return True
                
                return False
            
            # Get existing groups to check for duplicates
            try:
                existing_groups = self.client_api.get_groups()
                existing_group_list = []  # Keep full group objects for better matching
                if isinstance(existing_groups, list):
                    for g in existing_groups:
                        if isinstance(g, dict):
                            title = g.get('title', '').strip()
                            if title:
                                existing_group_list.append(title)
                elif isinstance(existing_groups, dict) and 'items' in existing_groups:
                    for g in existing_groups.get('items', []):
                        if isinstance(g, dict):
                            title = g.get('title', '').strip()
                            if title:
                                existing_group_list.append(title)
                
                logger.debug(f"Found {len(existing_group_list)} existing groups")
            except Exception as e:
                logger.warning(f"Could not fetch existing groups: {e}")
                existing_group_list = []
            
            # Create each subject group
            for group_config in subject_groups:
                try:
                    name = group_config.get('name', '').strip()
                    if not name:
                        logger.warning(f"Subject group missing name: {group_config}")
                        continue
                    
                    # Skip if group already exists (fuzzy matching for plural/singular variations)
                    matching_existing = None
                    for existing_name in existing_group_list:
                        if names_match(name, existing_name):
                            matching_existing = existing_name
                            break
                    
                    if matching_existing:
                        logger.info(f"⏭️  Subject group '{name}' already exists as '{matching_existing}', skipping")
                        self.summary.add_skipped("Subject Group", name, f"already exists as '{matching_existing}'")
                        continue
                    
                    authorization = group_config.get('authorization', 'Always Unauthorized')
                    visibility = group_config.get('visibility', 'Silent')
                    priority = group_config.get('priority', 0)
                    description = group_config.get('description', '')
                    color = group_config.get('color', '#D20300')
                    camera_groups = group_config.get('camera_groups', None)
                    
                    group_response = self.client_api.create_subject_group(
                        name=name,
                        authorization=authorization,
                        visibility=visibility,
                        priority=priority,
                        description=description,
                        color=color,
                        camera_groups=camera_groups
                    )
                    logger.info(f"✓ Created subject group: {name}")
                    
                    # Track created group
                    try:
                        group_data = group_response.json() if hasattr(group_response, 'json') else group_response if isinstance(group_response, dict) else {}
                        group_id = group_data.get('id') or 'unknown'
                        self.summary.add_created_item('groups', {
                            'name': name,
                            'id': group_id,
                            'type': 'subject',
                            'authorization': authorization,
                            'visibility': visibility
                        })
                    except Exception:
                        self.summary.add_created_item('groups', {
                            'name': name,
                            'id': 'unknown',
                            'type': 'subject',
                            'authorization': authorization,
                            'visibility': visibility
                        })
                    
                except Exception as e:
                    group_name = group_config.get('name', 'unknown')
                    error_detail = str(e)
                    logger.error(f"❌ Failed to create subject group '{group_name}': {error_detail}")
                    logger.warning(f"⚠️  Subject group '{group_name}' was not created. You may need to create it manually in the UI.")
                    self.summary.add_warning(f"Subject group '{group_name}' was not created - manual action may be needed")
        
        # Device groups - TODO: implement once endpoint is available
        device_groups = groups.get('device_groups', [])
        if device_groups:
            logger.debug(f"Device groups configuration not yet implemented ({len(device_groups)} groups skipped)")
    
    async def configure_accounts(self):
        """Configure user accounts and user groups via API."""
        accounts = self.config.get('accounts', {})
        if not accounts:
            logger.info("No accounts to configure")
            return
        
        logger.info("Configuring accounts...")
        
        # Initialize API client if needed
        if not self.client_api:
            self.initialize_api_client()
        
        # Get roles and user groups for mapping
        role_map = {}  # role name (lowercase) -> roleId
        user_group_map = {}  # user group name (lowercase) -> userGroupId
        
        try:
            roles = self.client_api.get_roles()
            if isinstance(roles, list):
                for role in roles:
                    if isinstance(role, dict):
                        title = role.get('title', '')
                        role_id = role.get('id')
                        if title and role_id:
                            role_map[title.lower()] = role_id
            logger.debug(f"Found {len(role_map)} roles")
        except Exception as e:
            logger.warning(f"Could not get roles: {e}")
        
        try:
            user_groups = self.client_api.get_user_groups()
            if isinstance(user_groups, list):
                for ug in user_groups:
                    if isinstance(ug, dict):
                        title = ug.get('title', '')
                        ug_id = ug.get('id')
                        if title and ug_id:
                            user_group_map[title.lower()] = ug_id
            logger.debug(f"Found {len(user_group_map)} user groups")
        except Exception as e:
            logger.warning(f"Could not get user groups: {e}")
        
        # Process users
        users = accounts.get('users', [])
        if users:
            logger.debug(f"Creating {len(users)} users...")
            
            # Get existing users to check for duplicates
            try:
                existing_users = self.client_api.get_users()
                existing_usernames = set()
                if isinstance(existing_users, list):
                    for u in existing_users:
                        if isinstance(u, dict):
                            username = u.get('username', '')
                            if username:
                                existing_usernames.add(username.lower())
                elif isinstance(existing_users, dict) and 'items' in existing_users:
                    for u in existing_users.get('items', []):
                        if isinstance(u, dict):
                            username = u.get('username', '')
                            if username:
                                existing_usernames.add(username.lower())
                logger.debug(f"Found {len(existing_usernames)} existing users")
            except Exception as e:
                logger.warning(f"Could not fetch existing users: {e}")
                existing_usernames = set()
            
            for user_config in users:
                try:
                    username = user_config.get('username', '').strip()
                    if not username:
                        logger.warning(f"User missing username: {user_config}")
                        continue
                    
                    # Skip if user already exists
                    if username.lower() in existing_usernames:
                        logger.info(f"⏭️  User '{username}' already exists, skipping")
                        self.summary.add_skipped("User", username, "already exists")
                        continue
                    
                    first_name = user_config.get('first_name', '').strip()
                    last_name = user_config.get('last_name', '').strip()
                    email = user_config.get('email')
                    email = email.strip() if email else None
                    
                    # Map role name to roleId
                    role_name = user_config.get('role', '').strip()
                    role_id = None
                    if role_name:
                        # Normalize role name and try to match
                        role_lower = role_name.lower()
                        # Try direct match first
                        if role_lower in role_map:
                            role_id = role_map[role_lower]
                        else:
                            # Try common variations
                            # "operator" -> "Operator"
                            if role_lower == 'operator':
                                role_id = role_map.get('operator')
                            # "super admin" or "superadmin" -> "Super Admin"
                            elif role_lower in ['super admin', 'superadmin']:
                                role_id = role_map.get('super admin')
                            # "admin" -> "Admin"
                            elif role_lower == 'admin':
                                role_id = role_map.get('admin')
                            # Try case-insensitive search
                            else:
                                for role_title, rid in role_map.items():
                                    if role_title.lower() == role_lower:
                                        role_id = rid
                                        break
                    
                    if not role_id:
                        logger.error(f"Could not find role '{role_name}' for user '{username}'. Available roles: {list(role_map.keys())}")
                        continue
                    
                    # Map user group name to userGroupId
                    user_group_name = user_config.get('user_group', '').strip()
                    user_group_id = None
                    if user_group_name:
                        user_group_lower = user_group_name.lower()
                        if user_group_lower in user_group_map:
                            user_group_id = user_group_map[user_group_lower]
                    
                    if not user_group_id:
                        logger.error(f"Could not find user group '{user_group_name}' for user '{username}'. Available groups: {list(user_group_map.keys())}")
                        continue
                    
                    # Handle password
                    password = user_config.get('password')
                    if password is None:
                        # Generate password: <FirstLetterCaps>rest_lowercase123!
                        # Example: "Test" -> "Test123!", "Administrator" -> "Administrator123!"
                        if username:
                            password = f"{username[0].upper()}{username[1:].lower()}123!"
                            logger.info(f"Generated password for user '{username}'")
                            logger.debug(f"Generated password: {password}")  # Only log in debug mode
                        else:
                            logger.warning(f"Cannot generate password for user without username, skipping")
                            continue
                    elif password == "":
                        # Empty string means skip password field (keep existing password)
                        password = None
                        logger.info(f"Skipping password for user '{username}' (keep existing)")
                    
                    # Create user
                    user_response = self.client_api.create_user(
                        username=username,
                        first_name=first_name,
                        last_name=last_name,
                        email=email,
                        role_id=role_id,
                        user_group_id=user_group_id,
                        password=password
                    )
                    logger.info(f"✓ Created user: {username}")
                    
                    # Track created user
                    try:
                        user_data = user_response.json() if hasattr(user_response, 'json') else user_response if isinstance(user_response, dict) else {}
                        user_id = user_data.get('id') or user_data.get('userId') or 'unknown'
                        self.summary.add_created_item('accounts', {
                            'username': username,
                            'id': user_id,
                            'first_name': first_name,
                            'last_name': last_name,
                            'email': email,
                            'role': role_name
                        })
                    except Exception:
                        self.summary.add_created_item('accounts', {
                            'username': username,
                            'id': 'unknown',
                            'first_name': first_name,
                            'last_name': last_name,
                            'email': email,
                            'role': role_name
                        })
                    
                except Exception as e:
                    username = user_config.get('username', 'unknown')
                    error_detail = str(e)
                    logger.error(f"❌ Failed to create user '{username}': {error_detail}")
                    logger.warning(f"⚠️  User '{username}' was not created. You may need to create it manually in the UI.")
                    self.summary.add_warning(f"User '{username}' was not created - manual action may be needed")
                    self.summary.add_error("User", username, error_detail)
        
        # User groups - create user groups
        user_groups_config = accounts.get('user_groups', [])
        if user_groups_config:
            logger.debug(f"Creating {len(user_groups_config)} user groups...")
            
            # Get existing user groups to check for duplicates
            try:
                existing_user_groups = self.client_api.get_user_groups()
                existing_titles = set()
                if isinstance(existing_user_groups, list):
                    for ug in existing_user_groups:
                        if isinstance(ug, dict):
                            title = ug.get('title', '')
                            if title:
                                existing_titles.add(title.lower())
                logger.debug(f"Found {len(existing_titles)} existing user groups")
            except Exception as e:
                logger.warning(f"Could not fetch existing user groups: {e}")
                existing_titles = set()
            
            # Get subject groups for mapping
            subject_group_map = {}  # name -> id
            try:
                groups = self.client_api.get_groups()
                if isinstance(groups, list):
                    for g in groups:
                        if isinstance(g, dict):
                            name = g.get('name', '') or g.get('title', '')
                            gid = g.get('id')
                            if name and gid:
                                subject_group_map[name.lower()] = gid
                elif isinstance(groups, dict) and 'items' in groups:
                    for g in groups.get('items', []):
                        if isinstance(g, dict):
                            name = g.get('name', '') or g.get('title', '')
                            gid = g.get('id')
                            if name and gid:
                                subject_group_map[name.lower()] = gid
            except Exception as e:
                logger.warning(f"Could not get subject groups for mapping: {e}")
            
            for ug_config in user_groups_config:
                try:
                    # Support both 'title' and 'name' fields for backward compatibility
                    title = (ug_config.get('title', '') or ug_config.get('name', '')).strip()
                    if not title:
                        logger.warning(f"User group missing title/name: {ug_config}")
                        continue
                    
                    # Skip if already exists
                    if title.lower() in existing_titles:
                        logger.info(f"⏭️  User group '{title}' already exists, skipping")
                        self.summary.add_skipped("User Group", title, "already exists")
                        continue
                    
                    # Map subject group names to IDs
                    subject_group_names = ug_config.get('subject_groups', [])
                    subject_group_ids = []
                    for sg_name in subject_group_names:
                        sg_name_lower = sg_name.lower()
                        if sg_name_lower in subject_group_map:
                            subject_group_ids.append(subject_group_map[sg_name_lower])
                        else:
                            logger.warning(f"Subject group '{sg_name}' not found for user group '{title}'")
                    
                    # Map camera group names to IDs (if provided)
                    camera_group_names = ug_config.get('camera_groups', [])
                    camera_group_ids = []
                    # TODO: Implement camera group mapping when endpoint is available
                    if camera_group_names:
                        logger.debug(f"Camera groups mapping not yet implemented for user group '{title}'")
                    
                    # Create user group
                    ug_response = self.client_api.create_user_group(
                        title=title,
                        subject_groups=subject_group_ids,
                        camera_groups=camera_group_ids
                    )
                    logger.info(f"✓ Created user group: {title}")
                    
                    # Track created user group
                    try:
                        ug_data = ug_response.json() if hasattr(ug_response, 'json') else ug_response if isinstance(ug_response, dict) else {}
                        ug_id = ug_data.get('id') or ug_data.get('userGroupId') or 'unknown'
                        self.summary.add_created_item('groups', {
                            'name': title,
                            'id': ug_id,
                            'type': 'user',
                            'subject_groups': len(subject_group_ids),
                            'camera_groups': len(camera_group_ids)
                        })
                    except Exception:
                        self.summary.add_created_item('groups', {
                            'name': title,
                            'id': 'unknown',
                            'type': 'user',
                            'subject_groups': len(subject_group_ids),
                            'camera_groups': len(camera_group_ids)
                        })
                    
                except Exception as e:
                    title = ug_config.get('title', 'unknown') or ug_config.get('name', 'unknown')
                    error_detail = str(e)
                    logger.error(f"❌ Failed to create user group '{title}': {error_detail}")
                    logger.warning(f"⚠️  User group '{title}' was not created. You may need to create it manually in the UI.")
                    self.summary.add_warning(f"User group '{title}' was not created - manual action may be needed")
                    self.summary.add_error("User Group", title, error_detail)
    
    async def configure_inquiries(self):
        """
        Configure inquiry cases via REST API and GraphQL.
        
        Creates inquiry cases, uploads files, and configures file settings
        (ROI, threshold). Automatically skips inquiry cases that already exist.
        
        Config Section: inquiries
        Example:
            inquiries:
              - name: "upgrade test"
                priority: "Medium"
                files:
                  - path: "assets/videos/Neo.mp4"
                    settings: "default"
                  - path: "assets/videos/Neo.webm"
                    settings: "custom"  # Custom ROI and threshold
        """
        inquiries = self.config.get('inquiries', [])
        if not inquiries:
            logger.info("No inquiries to configure")
            return
        
        logger.debug(f"Configuring {len(inquiries)} inquiry cases...")
        
        # Initialize API client if needed
        if not self.client_api:
            self.initialize_api_client()
        
        # Get project root directory (where main.py is located)
        project_root = os.path.dirname(os.path.abspath(__file__))
        
        for inquiry_config in inquiries:
            try:
                inquiry_name = inquiry_config.get('name', '').strip()
                if not inquiry_name:
                    logger.warning(f"Inquiry missing name: {inquiry_config}")
                    continue
                
                files_config = inquiry_config.get('files', [])
                if not files_config:
                    logger.warning(f"Inquiry '{inquiry_name}' has no files, skipping")
                    continue
                
                priority = inquiry_config.get('priority', 'Medium')  # Default to Medium if not specified
                
                # Check if case already exists before creating (prevent "case 2")
                existing_cases = self.client_api.get_inquiry_cases()
                existing_case_names = {case.get('name', '').lower() for case in existing_cases if case.get('name')}
                
                if inquiry_name.lower() in existing_case_names:
                    # Find the existing case ID
                    existing_case = next((c for c in existing_cases if c.get('name', '').lower() == inquiry_name.lower()), None)
                    if existing_case:
                        case_id = existing_case.get('id')
                        logger.info(f"⏭️  Inquiry case '{inquiry_name}' already exists (id: {case_id}), skipping")
                        self.summary.add_skipped("Inquiry Case", inquiry_name, "already exists")
                        continue
                
                # Create inquiry case with priority (try to set during creation, then update as fallback)
                from client_api import InquiryCaseAlreadyExists
                inquiry_tracking = None  # Initialize for tracking
                try:
                    # Try to create with priority included in creation payload
                    case_result = self.client_api.create_inquiry_case(inquiry_name, priority=priority)
                    case_id = case_result.get('id')
                    if not case_id:
                        logger.error(f"Failed to get case ID for '{inquiry_name}'")
                        continue
                    
                    # Track created inquiry case (will update with files later)
                    inquiry_tracking = {
                        'name': inquiry_name,
                        'id': case_id,
                        'files': []
                    }
                    
                    # Always update priority separately as well (in case creation didn't accept it)
                    # This ensures priority is set even if the creation API doesn't support it
                    try:
                        self.client_api.update_inquiry_case(case_id, priority=priority)
                        logger.info(f"✓ Set inquiry priority to: {priority}")
                    except Exception as e:
                        logger.warning(f"Could not set priority for inquiry '{inquiry_name}': {e}")
                        logger.warning(f"  → Priority may need to be set manually in the UI")
                except InquiryCaseAlreadyExists:
                    logger.info(f"⏭️  Inquiry case '{inquiry_name}' already exists, skipping")
                    self.summary.add_skipped("Inquiry Case", inquiry_name, "already exists")
                    continue
                
                # Process each file
                logger.info(f"Adding {len(files_config)} files to inquiry case...")
                file_ids_map = {}  # filename -> file_id (uploadId)
                successful_uploads = []  # Track successfully uploaded files
                
                for idx, file_config in enumerate(files_config):
                    try:
                        # Add small delay between file uploads to prevent queue issues (except first file)
                        if idx > 0:
                            time.sleep(FILE_STATUS_CHECK_DELAY)  # Small delay between uploads
                        
                        file_path = file_config.get('path', '').strip()
                        if not file_path:
                            logger.warning(f"File entry missing path: {file_config}")
                            continue
                        
                        settings = file_config.get('settings', '')
                        filename = os.path.basename(file_path)
                        
                        # Parse settings - support both string (backward compatibility) and dict (new format)
                        custom_settings = None
                        if isinstance(settings, dict):
                            # New format: settings is a dict with type, threshold, roi
                            if settings.get('type') == 'custom':
                                custom_settings = {
                                    'threshold': settings.get('threshold', 0.5),
                                    'roi': settings.get('roi', {})
                                }
                                logger.debug(f"File '{filename}' has custom settings: threshold={custom_settings['threshold']}, ROI={custom_settings['roi']}")
                        elif isinstance(settings, str):
                            # Legacy format: string like "custom" or "DEFAULT VALUES"
                            settings_str = settings.strip().lower()
                            if settings_str == 'custom':
                                # Backward compatibility: use hardcoded Neo.webm values if it's Neo.webm
                                if filename.lower() == 'neo.webm':
                                    custom_settings = {
                                        'threshold': 0.37,
                                        'roi': {'top': 15, 'right': 15, 'bottom': 22, 'left': 0}
                                    }
                                    logger.debug(f"File '{filename}' using legacy custom settings (Neo.webm defaults)")
                        
                        # Resolve file path - always relative to project root
                        # Supports paths like: "assets/videos/Neo.mp4", "Neo.mp4", or absolute paths
                        full_file_path = None
                        if os.path.isabs(file_path):
                            # Absolute path provided
                            full_file_path = file_path
                        else:
                            # Relative path - resolve from project root
                            # Try the path as-is first (e.g., "assets/videos/Neo.mp4")
                            relative_path = os.path.join(project_root, file_path)
                            if os.path.exists(relative_path):
                                full_file_path = relative_path
                            else:
                                # Try in assets/videos directory (e.g., just "Neo.mp4" -> "assets/videos/Neo.mp4")
                                videos_path = os.path.join(project_root, 'assets', 'videos', filename)
                                if os.path.exists(videos_path):
                                    full_file_path = videos_path
                                else:
                                    logger.warning(f"File not found: {file_path} (tried: {relative_path}, {videos_path})")
                                    continue
                        
                        if not os.path.exists(full_file_path):
                            logger.warning(f"File does not exist: {full_file_path}")
                            continue
                        
                        # Step 1: Prepare forensic upload
                        logger.debug(f"Preparing upload for: {filename}")
                        prepare_result = self.client_api.prepare_forensic_upload(filename, with_analysis=True)
                        upload_id = prepare_result.get('id') or prepare_result.get('uploadId')
                        if not upload_id:
                            logger.error(f"Failed to get upload ID for '{filename}'")
                            continue
                        
                        # Step 2: Upload file
                        logger.debug(f"Uploading file: {filename}")
                        self.client_api.upload_forensic_file(full_file_path, upload_id)
                        
                        # Step 3: Add file to case
                        # Use custom threshold if specified, otherwise default (0.5)
                        threshold = custom_settings.get('threshold', 0.5) if custom_settings else 0.5
                        
                        logger.debug(f"Adding file to case: {filename} (threshold: {threshold})")
                        add_result = self.client_api.add_file_to_inquiry_case(
                            case_id, upload_id, filename, threshold=threshold
                        )
                        
                        # Verify file was added successfully
                        time.sleep(0.5)  # Wait a moment for file to be registered (short delay, keep as-is)
                        case_files = self.client_api.get_inquiry_case_files(case_id)
                        uploaded_file = next((f for f in case_files if f.get('fileName', '').lower() == filename.lower()), None)
                        if not uploaded_file:
                            logger.warning(f"⚠️  File '{filename}' may not have been added successfully - verify in UI")
                        else:
                            logger.debug(f"Verified file '{filename}' was added (status: {uploaded_file.get('status', 'unknown')})")
                        
                        # Store upload_id and custom settings for potential configuration update
                        file_ids_map[filename] = upload_id
                        if custom_settings:
                            # Store custom settings for this file to configure after all files are added
                            file_ids_map[f'{filename}_custom'] = custom_settings
                        successful_uploads.append(filename)
                        
                        logger.info(f"✓ Added file to inquiry: {filename}")
                        
                        # Track uploaded file in inquiry_tracking
                        if inquiry_tracking is not None:
                            inquiry_tracking['files'].append({
                                'filename': filename,
                                'upload_id': upload_id,
                                'has_custom_settings': custom_settings is not None
                            })
                        
                    except Exception as e:
                        logger.error(f"❌ Failed to process file '{file_config.get('path', 'unknown')}': {e}")
                        self.summary.add_error(f"Inquiry File Upload", file_config.get('path', 'unknown'), str(e))
                        continue
                
                if not successful_uploads:
                    logger.warning(f"⚠️  No files were successfully uploaded for inquiry '{inquiry_name}'")
                    continue
                
                # Wait a moment for all files to be registered before configuring
                if file_ids_map:
                    time.sleep(RETRY_DELAY)
                    
                    # Get all files from the case
                    try:
                        case_files = self.client_api.get_inquiry_case_files(case_id)
                        
                        # Configure files with custom ROI and threshold settings
                        files_to_configure = {}
                        for key, value in file_ids_map.items():
                            if key.endswith('_custom') and isinstance(value, dict):
                                filename = key.replace('_custom', '')
                                files_to_configure[filename] = value
                        
                        if files_to_configure:
                            logger.info(f"Configuring {len(files_to_configure)} file(s) with custom ROI/threshold settings...")
                            
                            for filename, custom_config in files_to_configure.items():
                                file_id = None
                                file_status = None
                                
                                # Find the file in the case
                                for case_file in case_files:
                                    if case_file.get('fileName', '').lower() == filename.lower():
                                        # Use cameraId for GraphQL mutations (updateFileMediaData and startAnalyzeFilesCase)
                                        file_id = case_file.get('cameraId', '')
                                        file_status = case_file.get('status', '')
                                        logger.debug(f"Found {filename} in case (cameraId: {file_id}, status: {file_status})")
                                        break
                                
                                if file_id:
                                    # Update ROI and threshold configuration
                                    try:
                                        roi = custom_config.get('roi', {})
                                        threshold = custom_config.get('threshold', 0.5)
                                        
                                        self.client_api.update_file_media_data(
                                            file_id=file_id,
                                            threshold=threshold,
                                            camera_padding=roi
                                        )
                                        logger.info(f"✓ Updated {filename} configuration (ROI: top={roi.get('top', 0)}, right={roi.get('right', 0)}, bottom={roi.get('bottom', 0)}, left={roi.get('left', 0)}, threshold={threshold})")
                                        
                                        # Track the custom configuration
                                        if inquiry_tracking is not None:
                                            for file_track in inquiry_tracking['files']:
                                                if file_track.get('filename', '').lower() == filename.lower():
                                                    file_track['custom_config'] = custom_config
                                                    break
                                    except Exception as update_error:
                                        logger.error(f"Failed to update {filename} configuration: {update_error}")
                                        logger.warning(f"You may need to manually update the ROI configuration for {filename} in the UI")
                                else:
                                    logger.warning(f"Could not find {filename} in case to configure custom settings")
                        
                        # Check file analysis status and start analysis if needed
                        # Note: Files are typically already analyzing due to with_analysis=True in prepare_forensic_upload
                        all_file_ids = [f.get('cameraId') for f in case_files if f.get('cameraId')]
                        if all_file_ids:
                            # Check which files are not already analyzing
                            files_not_analyzing = []
                            for case_file in case_files:
                                file_id = case_file.get('cameraId')
                                status = case_file.get('status', '').upper()
                                if file_id and status not in ['ANALYZING', 'DONE']:
                                    files_not_analyzing.append(file_id)
                            
                            if files_not_analyzing:
                                # Only start analysis for files that aren't already analyzing
                                try:
                                    logger.debug(f"Starting analysis for {len(files_not_analyzing)} file(s) that aren't already analyzing...")
                                    self.client_api.start_analyze_files_case(case_id, files_not_analyzing)
                                    logger.info(f"✓ Started analysis for {len(files_not_analyzing)} file(s)")
                                    
                                    # Wait a moment and re-check status
                                    time.sleep(RETRY_DELAY)
                                    case_files = self.client_api.get_inquiry_case_files(case_id)
                                    
                                except Exception as analyze_error:
                                    # Re-check file statuses after error to provide accurate feedback
                                    time.sleep(FILE_STATUS_CHECK_DELAY)  # Brief wait for status to update
                                    try:
                                        case_files = self.client_api.get_inquiry_case_files(case_id)
                                    except Exception as fetch_error:
                                        logger.debug(f"Could not re-fetch case files after error: {fetch_error}")
                                        case_files = []  # Fallback if we can't re-fetch
                                    
                                    # Count files by status
                                    status_counts = {}
                                    files_by_status = {}
                                    for case_file in case_files:
                                        status = case_file.get('status', 'UNKNOWN').upper()
                                        filename = case_file.get('fileName', 'unknown')
                                        status_counts[status] = status_counts.get(status, 0) + 1
                                        if status not in files_by_status:
                                            files_by_status[status] = []
                                        files_by_status[status].append(filename)
                                    
                                    done_count = status_counts.get('DONE', 0)
                                    analyzing_count = status_counts.get('ANALYZING', 0)
                                    queued_count = status_counts.get('QUEUED', 0)
                                    total_files = len(case_files)
                                    
                                    # Provide clear warning based on actual status
                                    error_str = str(analyze_error)
                                    if "ERR_FAILED_TO_UPDATE_PROGRESS" in error_str:
                                        if done_count == total_files:
                                            # All files are done - this is actually success
                                            logger.info(f"✓ All {total_files} inquiry file(s) completed analysis successfully")
                                        elif done_count > 0 or analyzing_count > 0:
                                            # Some files are working
                                            warning_msg = f"⚠️  Inquiry file analysis status: {done_count} out of {total_files} file(s) DONE"
                                            if analyzing_count > 0:
                                                warning_msg += f", {analyzing_count} ANALYZING"
                                            if queued_count > 0:
                                                warning_msg += f", {queued_count} QUEUED"
                                            
                                            # List files that need attention
                                            if queued_count > 0 and 'QUEUED' in files_by_status:
                                                warning_msg += f"\n   Files that may need manual attention: {', '.join(files_by_status['QUEUED'])}"
                                            
                                            warning_msg += "\n   Please check the UI to verify all files complete analysis"
                                            logger.warning(warning_msg)
                                            self.summary.add_warning(f"Inquiry '{inquiry_name}': {done_count}/{total_files} files completed analysis - some may need manual review")
                                        else:
                                            # All files stuck
                                            logger.warning(f"⚠️  Could not start analysis for inquiry files. Status: {status_counts}")
                                            logger.warning(f"   Please check the UI and manually start analysis if needed")
                                            self.summary.add_warning(f"Inquiry '{inquiry_name}': Analysis may need to be started manually")
                                    else:
                                        # Other error - log but don't be too verbose
                                        logger.debug(f"Could not start analysis (files may already be analyzing): {error_str[:100]}")
                                        
                                        # Still provide status summary
                                        if done_count > 0 or analyzing_count > 0:
                                            logger.info(f"✓ File analysis status: {done_count} DONE, {analyzing_count} ANALYZING")
                            
                            else:
                                # All files are already analyzing or done - check final status
                                time.sleep(FILE_STATUS_CHECK_DELAY)  # Brief wait to get latest status
                                try:
                                    case_files = self.client_api.get_inquiry_case_files(case_id)
                                except Exception as fetch_error:
                                    logger.debug(f"Could not re-fetch case files for final status: {fetch_error}")
                                    pass  # Use existing case_files if re-fetch fails
                                
                                analyzing_count = len([f for f in case_files if f.get('status', '').upper() == 'ANALYZING'])
                                done_count = len([f for f in case_files if f.get('status', '').upper() == 'DONE'])
                                queued_count = len([f for f in case_files if f.get('status', '').upper() == 'QUEUED'])
                                
                                if done_count == len(case_files):
                                    logger.info(f"✓ All {done_count} inquiry file(s) completed analysis")
                                elif analyzing_count > 0 or done_count > 0:
                                    logger.info(f"✓ File analysis in progress: {done_count} DONE, {analyzing_count} ANALYZING")
                                    if queued_count > 0:
                                        logger.warning(f"⚠️  {queued_count} file(s) are QUEUED - may need manual attention")
                                else:
                                    logger.debug(f"File analysis status: Analyzing: {analyzing_count}, Done: {done_count}, Queued: {queued_count}")
                        else:
                            logger.debug("No file IDs found to start analysis")
                    except Exception as e:
                        logger.warning(f"Could not configure files or start analysis: {e}")
                
                # Final status check - wait a moment and verify all files
                time.sleep(RETRY_DELAY)
                try:
                    final_case_files = self.client_api.get_inquiry_case_files(case_id)
                    final_status_counts = {}
                    final_files_by_status = {}
                    for case_file in final_case_files:
                        status = case_file.get('status', 'UNKNOWN').upper()
                        filename = case_file.get('fileName', 'unknown')
                        final_status_counts[status] = final_status_counts.get(status, 0) + 1
                        if status not in final_files_by_status:
                            final_files_by_status[status] = []
                        final_files_by_status[status].append(filename)
                    
                    final_done = final_status_counts.get('DONE', 0)
                    final_analyzing = final_status_counts.get('ANALYZING', 0)
                    final_queued = final_status_counts.get('QUEUED', 0)
                    final_total = len(final_case_files)
                    
                    if final_done == final_total:
                        logger.info(f"✓ Completed inquiry case: {inquiry_name} ({len(successful_uploads)} file(s) uploaded, all {final_done} completed analysis)")
                    elif final_done > 0 or final_analyzing > 0:
                        status_msg = f"✓ Completed inquiry case: {inquiry_name} ({len(successful_uploads)} file(s) uploaded)"
                        status_msg += f" - Analysis status: {final_done}/{final_total} DONE"
                        if final_analyzing > 0:
                            status_msg += f", {final_analyzing} ANALYZING"
                        if final_queued > 0:
                            status_msg += f", {final_queued} QUEUED"
                        logger.info(status_msg)
                        
                        if final_queued > 0:
                            logger.warning(f"⚠️  {final_queued} file(s) are QUEUED and may need manual analysis:")
                            for queued_file in final_files_by_status.get('QUEUED', []):
                                logger.warning(f"   - {queued_file}")
                            logger.warning(f"   Please check the UI and manually start analysis if needed")
                            self.summary.add_warning(f"Inquiry '{inquiry_name}': {final_queued} file(s) are QUEUED - may need manual analysis")
                    else:
                        logger.info(f"✓ Completed inquiry case: {inquiry_name} ({len(successful_uploads)} file(s) uploaded)")
                        logger.warning(f"⚠️  File analysis status unclear - please verify in UI")
                except Exception as e:
                    # If we can't check final status, just log completion
                    logger.info(f"✓ Completed inquiry case: {inquiry_name} ({len(successful_uploads)} file(s) uploaded)")
                    logger.debug(f"Could not check final file status: {e}")
                
                # Track created inquiry case
                if inquiry_tracking is not None:
                    inquiry_tracking['files_count'] = len(successful_uploads)
                    self.summary.add_created_item('inquiries', inquiry_tracking)
                
            except Exception as e:
                inquiry_name = inquiry_config.get('name', 'unknown')
                error_detail = str(e)
                logger.error(f"❌ Failed to configure inquiry '{inquiry_name}': {error_detail}")
                logger.warning(f"⚠️  Inquiry '{inquiry_name}' was not configured. You may need to create it manually in the UI.")
                self.summary.add_warning(f"Inquiry '{inquiry_name}' was not configured - manual action may be needed")
                continue
        
        logger.info("Inquiries configuration complete")
    
    async def configure_mass_import(self):
        """
        Upload mass import file via REST API.
        
        Prepares and uploads mass import file to OnWatch system.
        Processing continues in background after upload.
        Automatically skips if mass import with same name already exists.
        
        Config Section: mass_import
        Example:
            mass_import:
              name: "mass-import 43"
              file_path: "assets/mass-import/mass-import-43.tar"
              group: "Cardholders"  # Subject group to attach import to
        
        Note: Check UI for processing status and manually resolve issues if needed.
        """
        mass_import = self.config.get('mass_import', {})
        file_path = mass_import.get('file_path')
        if not file_path:
            logger.info("No mass import file specified")
            return
        
        logger.info("Configuring mass import...")
        
        # Initialize API client if needed
        if not self.client_api:
            self.initialize_api_client()
        
        # Get project root directory
        project_root = os.path.dirname(os.path.abspath(__file__))
        
        # Resolve file path
        if os.path.isabs(file_path):
            full_file_path = file_path
        else:
            full_file_path = os.path.join(project_root, file_path)
        
        if not os.path.exists(full_file_path):
            logger.error(f"Mass import file not found: {full_file_path}")
            return
        
        filename = os.path.basename(full_file_path)
        # Get name from config, or fallback to filename without extension
        mass_import_name = mass_import.get('name') or os.path.splitext(filename)[0]
        
        # Get Cardholders group ID
        try:
            groups = self.client_api.get_groups(limit=100)  # Get more groups to ensure we find it
            cardholders_group_id = None
            
            # Normalize groups to a list
            if isinstance(groups, dict) and 'items' in groups:
                groups_list = groups['items']
            elif isinstance(groups, list):
                groups_list = groups
            else:
                groups_list = []
            
            # Log all groups for debugging (use INFO level so it's visible)
            logger.info(f"Searching for Cardholders group among {len(groups_list)} groups...")
            for group in groups_list:
                if isinstance(group, dict):
                    # Try both 'name' and 'title' fields (API might use either)
                    group_name = group.get('name', '') or group.get('title', '')
                    group_name = group_name.strip() if group_name else ''
                    group_id = group.get('id', '')
                    
                    if group_name:
                        logger.info(f"  - Found group: '{group_name}' (id: {group_id})")
                    
                    # Fuzzy match for "Cardholders" (case-insensitive, handle plural/singular)
                    if group_name and group_name.lower() in ['cardholders', 'cardholder']:
                        cardholders_group_id = group_id
                        logger.info(f"✓ Matched Cardholders group: '{group_name}' (id: {cardholders_group_id})")
                        break
            
            if not cardholders_group_id:
                logger.error("Cardholders group not found in the system. Please ensure the group exists before uploading mass import.")
                logger.error("Mass import requires a subject group to attach the import to.")
                logger.error("Tip: Run Step 4 (Groups Configuration) first to create the Cardholders group.")
                return
            
        except Exception as e:
            logger.error(f"Failed to get groups: {e}")
            logger.error("Cannot proceed with mass import without group information")
            return
        
        # Step 0: Check quota (optional, but good practice)
        try:
            self.client_api.check_subjects_quota()
        except Exception as e:
            logger.debug(f"Quota check skipped: {e}")
        
        # Step 1: Prepare mass import upload
        logger.info(f"Preparing mass import upload: {mass_import_name}")
        try:
            prepare_result = self.client_api.prepare_mass_import_upload(
                name=mass_import_name,
                subject_group_ids=[cardholders_group_id],
                is_search_backwards=False,
                duplication_threshold=0.61
            )
            upload_id = prepare_result.get('id') or prepare_result.get('uploadId')
            if not upload_id:
                logger.error("Failed to get upload ID from prepare response")
                return
            
            mass_import_id = upload_id  # The upload ID is also the mass import ID
            
        except Exception as e:
            logger.error(f"Failed to prepare mass import upload: {e}")
            return
        
        # Step 2: Upload file
        logger.info(f"Uploading mass import file: {filename}")
        try:
            from client_api import MassImportAlreadyExists
            try:
                self.client_api.upload_mass_import_file(full_file_path, upload_id)
                logger.info(f"✓ Uploaded mass import file: {filename}")
                logger.info(f"✓ Mass import '{mass_import_name}' upload started successfully")
                logger.info("Processing will continue in the background. Check the UI for status updates.")
                logger.info("Note: You may need to manually resolve issues in the mass import report after processing completes.")
                
                # Track mass import
                self.summary.add_created_item('mass_import', {
                    'name': mass_import_name,
                    'filename': filename,
                    'upload_id': upload_id
                })
            except MassImportAlreadyExists as e:
                logger.info(f"⏭️  Mass import '{mass_import_name}' already exists, skipping")
                self.summary.add_skipped("Mass Import", mass_import_name, "already exists")
                return
        except Exception as e:
            logger.error(f"Failed to upload mass import file: {e}")
            return
        
        logger.info("Mass import configuration complete")
    
    def configure_rancher(self):
        """
        Configure Rancher environment variables via REST API (Step 11 - last step).
        
        This method uses the Rancher v3 REST API to update Kubernetes workload
        environment variables. It:
        1. Validates Rancher configuration from config.yaml
        2. Authenticates with Rancher API
        3. Extracts workload ID and project ID from config
        4. Updates environment variables in the main container
        
        The workload_path in config.yaml can be used to automatically extract
        the workload_id and project_id, or defaults are used.
        
        Raises:
            Exception: If configuration is missing or API calls fail
        """
        env_vars = self.config.get('env_vars', {})
        
        # Track env_vars from config.yaml for export (for transparency, even if step fails)
        # This ensures they appear in the export file regardless of success/failure
        if env_vars:
            for key, value in env_vars.items():
                self.summary.add_created_item('rancher_env_vars', {
                    'key': key,
                    'value': str(value)  # Convert to string for export
                })
        
        if not env_vars:
            logger.info("No Rancher environment variables to set")
            return
        
        rancher_config = self.config.get('rancher', {})
        if not rancher_config:
            logger.warning("Rancher configuration not found in config.yaml")
            logger.warning("Skipping Rancher environment variable configuration")
            return
        
        # Validate required Rancher config fields (ip_address not needed - uses onwatch.ip_address)
        required_fields = ['port', 'username', 'password']
        missing_fields = [field for field in required_fields if not rancher_config.get(field)]
        if missing_fields:
            logger.error(f"Missing required Rancher configuration fields: {', '.join(missing_fields)}")
            logger.error("Skipping Rancher environment variable configuration")
            return
        
        logger.info("Configuring Rancher environment variables via API...")
        
        # Use OnWatch IP address for Rancher base URL (Rancher runs on same machine as OnWatch)
        onwatch_config = self.config.get('onwatch', {})
        onwatch_ip = onwatch_config.get('ip_address')
        if not onwatch_ip:
            raise ValueError("onwatch.ip_address not found in config.yaml - required for Rancher API")
        
        rancher_port = rancher_config.get('port', 9443)
        base_url = rancher_config.get('base_url') or f"https://{onwatch_ip}:{rancher_port}"
        
        try:
            # Initialize Rancher API client
            rancher_api = RancherApi(
                base_url=base_url,
            username=rancher_config['username'],
                password=rancher_config['password']
            )
            rancher_api.login()
            
            # Extract workload_id from workload_path if provided (always discover project_id dynamically)
            workload_id = "statefulset:default:cv-engine"  # Default
            
            workload_path = rancher_config.get('workload_path', '')
            if workload_path:
                # Handle both full URLs and paths
                # Full URL: https://10.1.25.241:9443/p/local:p-5fh4c/workloads/run?...
                # Path: /p/local:p-p6l45/workloads/run?...
                
                # Remove protocol and base URL if present
                if '://' in workload_path:
                    # Full URL provided - extract just the path part
                    import urllib.parse
                    parsed_url = urllib.parse.urlparse(workload_path)
                    workload_path = parsed_url.path + ('?' + parsed_url.query if parsed_url.query else '')
                    logger.debug(f"Extracted path from full URL: {workload_path}")
                
                # Parse workload_path to extract workload_id only (not project_id - always discover dynamically)
                # Format: /p/local:p-p6l45/workloads/run?launchConfigIndex=-1&namespaceId=default&upgrade=true&workloadId=statefulset%3Adefault%3Acv-engine
                if 'workloadId=' in workload_path:
                    import urllib.parse
                    parsed = urllib.parse.parse_qs(urllib.parse.urlparse(workload_path).query)
                    if 'workloadId' in parsed:
                        workload_id = urllib.parse.unquote(parsed['workloadId'][0])
                        logger.info(f"Extracted workload_id from workload_path: {workload_id}")
            
            # Always discover project_id dynamically from default namespace
            logger.info("Discovering project_id from default namespace via Rancher API...")
            project_id = rancher_api.get_project_id_from_namespace(namespace="default")
            if not project_id:
                error_msg = "Could not discover project_id from default namespace"
                error_msg += f"\n  → Verify Rancher API is accessible at {base_url}"
                error_msg += "\n  → Verify namespace 'default' exists and has a projectId"
                logger.error(error_msg)
                raise ValueError(error_msg)
            
            logger.info(f"✓ Discovered project_id: {project_id}")
            
            # Log what we're using
            logger.info(f"Using workload_id: {workload_id}, project_id: {project_id}")
            
            # Update environment variables in the workload
            rancher_api.update_workload_environment_variables(
                env_vars=env_vars,
                workload_id=workload_id,
                project_id=project_id
            )
            logger.info(f"✓ Successfully configured {len(env_vars)} environment variables in Rancher")
            
            # Note: Rancher env vars are already tracked at the start of this method
            # for export transparency (so they appear even if step fails)
        except Exception as e:
            logger.error(f"Failed to configure Rancher environment variables: {e}")
            raise
    
    async def upload_files(self):
        """
        Upload translation file via SSH/SCP.
        
        Copies translation file to device and runs translation-util script
        to upload it to the OnWatch system.
        
        Config Sections: ssh, system_settings.system_interface.translation_file
        Example:
            ssh:
              ip_address: "10.1.71.14"
              username: "user"
              password: "${SSH_PASSWORD}"
            system_settings:
              system_interface:
                translation_file: "assets/Polski-updated3.json.json"
        
        This method uploads translation files to the OnWatch device using:
        1. SCP to copy file to /tmp/ on the device
        2. SSH to run translation-util upload script
        3. Provides file path when prompted by the script
        
        Icons directory upload is not yet implemented (requires API endpoint or additional SSH setup).
        """
        translation_file = self.config.get('system_settings', {}).get('system_interface', {}).get('translation_file', '')
        icons = self.config.get('system_settings', {}).get('system_interface', {}).get('icons', '')
        
        if not translation_file and not icons:
            logger.info("No translation file or icons directory specified in config")
            return
        
        # Handle translation file upload
        if translation_file:
            logger.info(f"Uploading translation file: {translation_file}")
            
            # Get SSH configuration
            ssh_config = self.config.get('ssh', {})
            if not ssh_config:
                logger.error("SSH configuration not found in config.yaml")
                logger.error("Translation file upload requires SSH configuration")
                return
            
            # Validate SSH config
            required_ssh_fields = ['ip_address', 'username', 'translation_util_path']
            missing_fields = [field for field in required_ssh_fields if not ssh_config.get(field)]
            if missing_fields:
                logger.error(f"Missing required SSH configuration fields: {', '.join(missing_fields)}")
                return
            
            # Get project root for resolving relative paths
            project_root = os.path.dirname(os.path.abspath(__file__))
            
            # Resolve translation file path
            if os.path.isabs(translation_file):
                local_file_path = translation_file
            else:
                local_file_path = os.path.join(project_root, translation_file)
            
            if not os.path.exists(local_file_path):
                logger.error(f"Translation file not found: {local_file_path}")
                return
            
            try:
                # Get SSH password - prompt if not in config
                ssh_password = ssh_config.get('password', '').strip()
                if not ssh_password:
                    logger.warning("SSH password not set in config.yaml")
                    logger.info("Prompting for SSH password (will not be saved)...")
                    import getpass
                    ssh_password = getpass.getpass(f"Enter SSH password for {ssh_config['username']}@{ssh_config['ip_address']}: ")
                    if not ssh_password:
                        logger.error("SSH password is required")
                        return
                
                # Initialize SSH utility
                ssh_util = SSHUtil(
                    ip_address=ssh_config['ip_address'],
                    username=ssh_config['username'],
                    password=ssh_password,
                    ssh_key_path=ssh_config.get('ssh_key_path')
                )
                
                # Upload translation file
                # Use sudo_password if specified, otherwise fall back to SSH password
                sudo_password = ssh_config.get('sudo_password')
                if not sudo_password:
                    sudo_password = ssh_config.get('password')
                
                success = ssh_util.upload_translation_file(
                    local_file_path=local_file_path,
                    translation_util_path=ssh_config['translation_util_path'],
                    sudo_password=sudo_password
                )
                
                if success:
                    logger.info(f"✓ Successfully uploaded translation file: {translation_file}")
                    
                    # Track translation file
                    self.summary.add_created_item('translation_file', {
                        'filename': os.path.basename(translation_file),
                        'path': translation_file,
                        'local_path': local_file_path
                    })
                else:
                    logger.error("Failed to upload translation file")
                    raise RuntimeError("Translation file upload failed")
                    
            except Exception as e:
                logger.error(f"Error uploading translation file: {e}")
                raise
        
        # Handle icons directory (not yet implemented)
        if icons:
            logger.warning("Icons directory upload is not yet implemented")
            logger.info(f"Icons directory configured: {icons} (requires manual upload or future implementation)")
    
    async def run(self):
        """Run the complete automation process."""
        logger.info("=" * 80)
        logger.info("Starting OnWatch Data Population Automation")
        logger.info("=" * 80)
        
        # Get OnWatch IP for export metadata
        onwatch_ip = self.config.get('onwatch', {}).get('ip_address', 'unknown')
        
        # Start timing
        self.summary.start_timing(onwatch_ip=onwatch_ip)
        
        try:
            # Step 1: Initialize API client
            step_start = time.time()
            logger.info("\n[Step 1/11] Initializing API client...")
            try:
                self.initialize_api_client()
                step_end = time.time()
                self.summary.record_step_timing(1, step_start, step_end)
                self.summary.record_step(1, "Initialize API Client", "success", "API client initialized and logged in")
            except Exception as e:
                step_end = time.time()
                self.summary.record_step_timing(1, step_start, step_end)
                error_msg = f"Failed to initialize API client: {str(e)}"
                logger.error(f"❌ {error_msg}")
                logger.error("⚠️  MANUAL ACTION REQUIRED: Cannot proceed without API client. Please check credentials and network connectivity.")
                self.summary.record_step(1, "Initialize API Client", "failed", error_msg, manual_action=True)
                # Store the exception to re-raise later (but we'll catch it cleanly in outer handler)
                raise  # Cannot continue without API client
            
            # Step 2: Set KV parameters
            step_start = time.time()
            logger.info("\n[Step 2/11] Setting KV parameters...")
            try:
                await self.set_kv_parameters()
                step_end = time.time()
                self.summary.record_step_timing(2, step_start, step_end)
                self.summary.record_step(2, "Set KV Parameters", "success")
            except Exception as e:
                step_end = time.time()
                self.summary.record_step_timing(2, step_start, step_end)
                error_msg = f"Failed to set KV parameters: {str(e)}"
                logger.error(f"❌ {error_msg}")
                logger.error("⚠️  MANUAL ACTION REQUIRED: Please set KV parameters manually in the UI at /bt/settings/kv")
                self.summary.record_step(2, "Set KV Parameters", "failed", error_msg, manual_action=True)
            
            # Step 3: Configure system settings
            step_start = time.time()
            logger.info("\n[Step 3/11] Configuring system settings...")
            try:
                await self.configure_system_settings()
                step_end = time.time()
                self.summary.record_step_timing(3, step_start, step_end)
                self.summary.record_step(3, "Configure System Settings", "success")
            except Exception as e:
                step_end = time.time()
                self.summary.record_step_timing(3, step_start, step_end)
                error_msg = f"Failed to configure system settings: {str(e)}"
                logger.error(f"❌ {error_msg}")
                logger.error("⚠️  MANUAL ACTION REQUIRED: Please configure system settings manually in the UI")
                self.summary.record_step(3, "Configure System Settings", "failed", error_msg, manual_action=True)
            
            # Step 4: Configure groups and profiles
            step_start = time.time()
            logger.info("\n[Step 4/11] Configuring groups and profiles...")
            try:
                await self.configure_groups()
                step_end = time.time()
                self.summary.record_step_timing(4, step_start, step_end)
                self.summary.record_step(4, "Configure Groups", "success")
            except Exception as e:
                step_end = time.time()
                self.summary.record_step_timing(4, step_start, step_end)
                error_msg = f"Failed to configure groups: {str(e)}"
                logger.error(f"❌ {error_msg}")
                logger.error("⚠️  MANUAL ACTION REQUIRED: Please configure groups manually in the UI")
                self.summary.record_step(4, "Configure Groups", "failed", error_msg, manual_action=True)
            
            # Step 5: Configure accounts
            step_start = time.time()
            logger.info("\n[Step 5/11] Configuring accounts...")
            try:
                await self.configure_accounts()
                step_end = time.time()
                self.summary.record_step_timing(5, step_start, step_end)
                self.summary.record_step(5, "Configure Accounts", "success")
            except Exception as e:
                step_end = time.time()
                self.summary.record_step_timing(5, step_start, step_end)
                error_msg = f"Failed to configure accounts: {str(e)}"
                logger.error(f"❌ {error_msg}")
                logger.error("⚠️  MANUAL ACTION REQUIRED: Please configure accounts manually in the UI")
                self.summary.record_step(5, "Configure Accounts", "failed", error_msg, manual_action=True)
            
            # Step 6: Populate watch list
            step_start = time.time()
            logger.info("\n[Step 6/11] Populating watch list...")
            try:
                self.populate_watch_list()
                step_end = time.time()
                self.summary.record_step_timing(6, step_start, step_end)
                # Check if there were any failures (tracked in populate_watch_list)
                # If warnings exist for subjects, mark as partial
                subject_warnings = [w for w in self.summary.warnings if "Subject" in w and "was not added" in w]
                if subject_warnings:
                    self.summary.record_step(6, "Populate Watch List", "partial", f"Some subjects failed - see warnings", manual_action=True)
                else:
                    self.summary.record_step(6, "Populate Watch List", "success")
            except Exception as e:
                step_end = time.time()
                self.summary.record_step_timing(6, step_start, step_end)
                error_msg = f"Failed to populate watch list: {str(e)}"
                logger.error(f"❌ {error_msg}")
                logger.error("⚠️  MANUAL ACTION REQUIRED: Please add watch list subjects manually in the UI")
                self.summary.record_step(6, "Populate Watch List", "failed", error_msg, manual_action=True)
            
            # Step 7: Configure devices
            step_start = time.time()
            logger.info("\n[Step 7/11] Configuring devices...")
            try:
                await self.configure_devices()
                step_end = time.time()
                self.summary.record_step_timing(7, step_start, step_end)
                self.summary.record_step(7, "Configure Devices", "success")
            except Exception as e:
                step_end = time.time()
                self.summary.record_step_timing(7, step_start, step_end)
                error_msg = f"Failed to configure devices: {str(e)}"
                logger.error(f"❌ {error_msg}")
                logger.error("⚠️  MANUAL ACTION REQUIRED: Please configure devices manually in the UI")
                self.summary.record_step(7, "Configure Devices", "failed", error_msg, manual_action=True)
            
            # Step 8: Configure inquiries
            step_start = time.time()
            logger.info("\n[Step 8/11] Configuring inquiries...")
            try:
                await self.configure_inquiries()
                step_end = time.time()
                self.summary.record_step_timing(8, step_start, step_end)
                self.summary.record_step(8, "Configure Inquiries", "success")
            except Exception as e:
                step_end = time.time()
                self.summary.record_step_timing(8, step_start, step_end)
                error_msg = f"Failed to configure inquiries: {str(e)}"
                logger.error(f"❌ {error_msg}")
                logger.error("⚠️  MANUAL ACTION REQUIRED: Please configure inquiries manually in the UI")
                self.summary.record_step(8, "Configure Inquiries", "failed", error_msg, manual_action=True)
            
            # Step 9: Upload mass import
            step_start = time.time()
            logger.info("\n[Step 9/11] Uploading mass import...")
            try:
                await self.configure_mass_import()
                step_end = time.time()
                self.summary.record_step_timing(9, step_start, step_end)
                self.summary.record_step(9, "Upload Mass Import", "success", "File uploaded, processing continues in background")
            except Exception as e:
                step_end = time.time()
                self.summary.record_step_timing(9, step_start, step_end)
                error_msg = f"Failed to upload mass import: {str(e)}"
                logger.error(f"❌ {error_msg}")
                logger.error("⚠️  MANUAL ACTION REQUIRED: Please upload mass import file manually in the UI")
                self.summary.record_step(9, "Upload Mass Import", "failed", error_msg, manual_action=True)
            
            # Step 10: Upload translation file
            step_start = time.time()
            logger.info("\n[Step 10/11] Uploading translation file...")
            try:
                await self.upload_files()
                step_end = time.time()
                self.summary.record_step_timing(10, step_start, step_end)
                self.summary.record_step(10, "Upload Translation File", "success")
            except Exception as e:
                step_end = time.time()
                self.summary.record_step_timing(10, step_start, step_end)
                error_msg = f"Failed to upload translation file: {str(e)}"
                logger.error(f"❌ {error_msg}")
                logger.error("⚠️  MANUAL ACTION REQUIRED: Please upload translation file manually via SSH")
                self.summary.record_step(10, "Upload Translation File", "failed", error_msg, manual_action=True)
            
            # Step 11: Configure Rancher (last step)
            step_start = time.time()
            logger.info("\n[Step 11/11] Configuring Rancher...")
            try:
                self.configure_rancher()
                step_end = time.time()
                self.summary.record_step_timing(11, step_start, step_end)
                self.summary.record_step(11, "Configure Rancher", "success")
            except Exception as e:
                step_end = time.time()
                self.summary.record_step_timing(11, step_start, step_end)
                error_msg = f"Failed to configure Rancher: {str(e)}"
                logger.error(f"❌ {error_msg}")
                logger.error("⚠️  MANUAL ACTION REQUIRED: Please configure Rancher environment variables manually")
                self.summary.record_step(11, "Configure Rancher", "failed", error_msg, manual_action=True)
            
        except Exception as e:
            # Show user-friendly error message without full stack trace
            error_message = str(e)
            logger.error(f"\n❌ FATAL ERROR: {error_message}")
            logger.error("Automation stopped due to fatal error")
            # Only show full traceback in verbose/debug mode
            # Check if verbose mode is enabled by checking root logger level
            root_logger = logging.getLogger()
            if root_logger.level <= logging.DEBUG:
                import traceback
                logger.debug("\nFull traceback (verbose mode):")
                logger.debug("", exc_info=True)
        finally:
            # End timing
            self.summary.end_timing()
        
        # Print summary
        self.summary.print_summary()
        
        # Export created items to file
        export_path = self.summary.export_to_file(format='yaml')
        if export_path:
            logger.info(f"💾 Data export saved for post-upgrade validation: {export_path}")
        
        # Exit with appropriate code
        failed_steps = sum(1 for s in self.summary.steps.values() if s['status'] == 'failed')
        if failed_steps > 0:
            sys.exit(1)


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='OnWatch Data Population Automation',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Validate configuration
  python3 main.py --validate
  
  # Run full automation
  python3 main.py
  
  # Run with custom config file
  python3 main.py --config my-config.yaml
  
  # Run specific step
  python3 main.py --step populate-watchlist
  
  # Dry-run mode (validate and show what would be executed)
  python3 main.py --dry-run
  
  # Preview dataset that will be populated
  python3 main.py --preview-data
  
  # Verbose logging
  python3 main.py --verbose
  
  # Quiet mode (errors only)
  python3 main.py --quiet
        """
    )
    parser.add_argument(
        '--config',
        type=str,
        default='config.yaml',
        help='Path to configuration YAML file (default: config.yaml)'
    )
    parser.add_argument(
        '--step',
        type=str,
        choices=[
            'init-api', 'set-kv-params', 'configure-system', 'configure-groups',
            'configure-accounts', 'populate-watchlist', 'configure-devices',
            'configure-inquiries', 'upload-mass-import', 'configure-rancher', 'upload-files'
        ],
        help='Run only a specific step. Use --list-steps to see descriptions.'
    )
    parser.add_argument(
        '--validate',
        action='store_true',
        help='Validate configuration file and exit (does not run automation)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Validate config and show what would be executed without making API calls'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging (DEBUG level)'
    )
    parser.add_argument(
        '--quiet',
        action='store_true',
        help='Enable quiet mode (ERROR level only)'
    )
    parser.add_argument(
        '--log-file',
        type=str,
        help='Save logs to file (e.g., --log-file automation.log)'
    )
    parser.add_argument(
        '--version',
        action='version',
        version='OnWatch Data Population Automation v1.0'
    )
    parser.add_argument(
        '--list-steps',
        action='store_true',
        help='List all available automation steps and exit'
    )
    parser.add_argument(
        '--set-ip',
        type=str,
        metavar='IP_ADDRESS',
        help='Update all IP addresses in config.yaml to the specified IP address. Updates onwatch, ssh, and rancher IPs automatically. Creates a backup of the original config file.'
    )
    parser.add_argument(
        '--preview-data',
        action='store_true',
        help='Preview the dataset that will be populated (shows all configured data) and exit'
    )
    
    args = parser.parse_args()
    
    # Handle list-steps
    if args.list_steps:
        steps = [
            ("init-api", "Initialize API Client", "Connect and authenticate with OnWatch API"),
            ("set-kv-params", "Set KV Parameters", "Configure key-value system parameters"),
            ("configure-system", "Configure System Settings", "Set general, map, engine, and interface settings"),
            ("configure-groups", "Configure Groups", "Create subject groups with authorization and visibility"),
            ("configure-accounts", "Configure Accounts", "Create user accounts and user groups"),
            ("populate-watchlist", "Populate Watch List", "Add subjects to watch list with images"),
            ("configure-devices", "Configure Devices", "Create cameras/devices with thresholds and calibration"),
            ("configure-inquiries", "Configure Inquiries", "Create inquiry cases with file uploads and ROI settings"),
            ("upload-mass-import", "Upload Mass Import", "Upload mass import file for bulk subject import"),
            ("configure-rancher", "Configure Rancher", "Set Kubernetes environment variables via Rancher API"),
            ("upload-files", "Upload Translation File", "Upload translation file to device via SSH")
        ]
        print("\nAvailable Automation Steps:")
        print("=" * 70)
        for step_id, step_name, description in steps:
            print(f"  --step {step_id:20s}  {step_name}")
            print(f"  {'':22s}  {description}\n")
        sys.exit(0)
    
    # Handle preview-data
    if args.preview_data:
        try:
            automation = OnWatchAutomation(config_path=args.config)
            config = automation.config
            
            print("\n" + "=" * 70)
            print("Dataset Preview")
            print("=" * 70)
            print(f"\nConfiguration file: {args.config}")
            print("\nThis dataset will be populated when you run the automation:\n")
            
            # KV Parameters
            kv_params = config.get('kv_parameters', {})
            if kv_params:
                print(f"📋 KV Parameters: {len(kv_params)}")
                for key, value in kv_params.items():
                    print(f"   • {key}: {value}")
            
            # System Settings
            sys_settings = config.get('system_settings', {})
            if sys_settings:
                print(f"\n⚙️  System Settings:")
                general = sys_settings.get('general', {})
                if general:
                    blur_faces = general.get('blur_all_faces_except_selected', False)
                    discard_detections = general.get('discard_detections_not_in_watch_list', False)
                    print(f"   General:")
                    print(f"     • Blur all faces except selected: {'enabled' if blur_faces else 'disabled'}")
                    print(f"     • Discard detections not in watch list: {'enabled' if discard_detections else 'disabled'}")
                    print(f"     • Face Threshold: {general.get('default_face_threshold', 'N/A')}")
                    print(f"     • Body Threshold: {general.get('default_body_threshold', 'N/A')}")
                    print(f"     • Liveness Threshold: {general.get('default_liveness_threshold', 'N/A')}")
                    print(f"     • Body Image Retention: {general.get('body_image_retention_period', 'N/A')}")
                map_settings = sys_settings.get('map', {})
                if map_settings:
                    seed = map_settings.get('seed_location', {})
                    acknowledge = map_settings.get('acknowledge', False)
                    action_title = map_settings.get('action_title', 'N/A')
                    masks_access = map_settings.get('masks_access_control', False)
                    print(f"   Map:")
                    if seed:
                        print(f"     • Seed Location: lat {seed.get('lat', 'N/A')}, long {seed.get('long', 'N/A')}")
                    print(f"     • Acknowledge: {'enabled' if acknowledge else 'disabled'}")
                    if acknowledge:
                        print(f"     • Action Title: {action_title}")
                    print(f"     • Masks Access Control: {'enabled' if masks_access else 'disabled'}")
                interface = sys_settings.get('system_interface', {})
                if interface:
                    product_name = interface.get('product_name', 'N/A')
                    translation_file = interface.get('translation_file', '')
                    icons = interface.get('icons', '')
                    print(f"   System Interface:")
                    print(f"     • Product Name: {product_name}")
                    if translation_file:
                        # Check if translation file exists
                        project_root = os.path.dirname(os.path.abspath(__file__))
                        if os.path.isabs(translation_file):
                            translation_path = translation_file
                        else:
                            translation_path = os.path.join(project_root, translation_file)
                        file_exists = os.path.exists(translation_path)
                        file_size = os.path.getsize(translation_path) if file_exists else 0
                        file_size_mb = file_size / (1024 * 1024) if file_size > 0 else 0
                        filename = os.path.basename(translation_file)
                        print(f"     • Translation File: {filename}")
                        print(f"       Path: {translation_file}")
                        if file_exists:
                            print(f"       Status: ✓ File exists ({file_size_mb:.2f} MB)")
                            print(f"       Upload: Will be uploaded via SSH to device")
                        else:
                            print(f"       Status: ⚠️  File not found at configured path")
                    if icons:
                        print(f"     • Icons: {icons} (⚠️  not yet implemented)")
                engine = sys_settings.get('engine', {})
                if engine:
                    video_storage = engine.get('video_storage', {})
                    print(f"   Engine:")
                    if video_storage:
                        print(f"     • All Videos Storage: {video_storage.get('all_videos_days', 'N/A')} days")
                        print(f"     • Videos with Detections: {video_storage.get('videos_with_detections_days', 'N/A')} days")
                    print(f"     • Detection Storage: {engine.get('detection_storage_days', 'N/A')} days")
                    print(f"     • Alert Storage: {engine.get('alert_storage_days', 'N/A')} days")
                    print(f"     • Inquiry Storage: {engine.get('inquiry_storage_days', 'N/A')} days")
            
            # Devices/Cameras
            devices = config.get('devices', [])
            if devices:
                print(f"\n📹 Cameras/Devices: {len(devices)}")
                for device in devices:
                    name = device.get('name', 'Unknown')
                    details = device.get('details', {})
                    threshold = details.get('threshold', 'N/A')
                    location = details.get('location', {}).get('name', 'default')
                    calibration = device.get('calibration', {})
                    tracker = calibration.get('tracker', 'N/A')
                    track_length = calibration.get('face_track_length', {})
                    track_min = track_length.get('min', 'N/A')
                    track_max = track_length.get('max', 'N/A')
                    padding = calibration.get('calibration_tool', {}).get('padding', {})
                    detection_min = calibration.get('calibration_tool', {}).get('detection_min_size', 'N/A')
                    security = device.get('security_access', {})
                    liveness = security.get('liveness', False)
                    liveness_threshold = security.get('liveness_threshold', 'N/A')
                    
                    print(f"   • {name}")
                    print(f"     - Threshold: {threshold}, Location: {location}")
                    print(f"     - Tracker: {tracker}, Face Track Length: {track_min}-{track_max}s")
                    if padding:
                        print(f"     - Padding: top={padding.get('top', 0)}, right={padding.get('right', 0)}, bottom={padding.get('bottom', 0)}, left={padding.get('left', 0)}")
                    print(f"     - Detection Min Size: {detection_min}")
                    print(f"     - Liveness: {'active' if liveness else 'disabled'}", end='')
                    if liveness:
                        print(f" (threshold: {liveness_threshold})")
                    else:
                        print()
            
            # Groups
            groups = config.get('groups', {})
            subject_groups = groups.get('subject_groups', [])
            device_groups = groups.get('device_groups', [])
            if subject_groups:
                print(f"\n👥 Subject Groups: {len(subject_groups)}")
                for group in subject_groups:
                    name = group.get('name', 'Unknown')
                    auth = group.get('authorization', 'N/A')
                    visibility = group.get('visibility', 'N/A')
                    priority = group.get('priority', 'N/A')
                    print(f"   • {name} ({auth}, {visibility}, priority: {priority})")
            if device_groups:
                print(f"\n📱 Device Groups (Camera Groups): {len(device_groups)}")
                for group in device_groups:
                    name = group.get('name', 'Unknown')
                    priority = group.get('priority', 'N/A')
                    description = group.get('description', '')
                    print(f"   • {name} (priority: {priority}, description: {description or 'none'})")
            
            # Watch List
            watch_list = config.get('watch_list', {})
            subjects = watch_list.get('subjects', [])
            if subjects:
                total_images = sum(len(s.get('images', [])) for s in subjects)
                print(f"\n👤 Watch List Subjects: {len(subjects)}")
                print(f"   Total Images: {total_images}")
                for subject in subjects:
                    name = subject.get('name', 'Unknown')
                    images = subject.get('images', [])
                    group = subject.get('group', 'N/A')
                    print(f"   • {name} ({len(images)} image(s), group: {group})")
            
            # Inquiry Cases
            inquiries = config.get('inquiries', [])
            if inquiries:
                print(f"\n🔍 Inquiry Cases: {len(inquiries)}")
                for inquiry in inquiries:
                    name = inquiry.get('name', 'Unknown')
                    files = inquiry.get('files', [])
                    priority = inquiry.get('priority', 'N/A')
                    print(f"   • {name} (priority: {priority}, {len(files)} file(s))")
                    for file_config in files:
                        file_path = file_config.get('path', 'Unknown')
                        filename = os.path.basename(file_path)
                        settings = file_config.get('settings', 'default')
                        print(f"     - {filename} ({settings})")
            
            # Mass Import
            mass_import = config.get('mass_import', {})
            if mass_import:
                name = mass_import.get('name', 'N/A')
                file_path = mass_import.get('file_path', 'N/A')
                print(f"\n📦 Mass Import:")
                print(f"   • Name: {name}")
                print(f"   • File: {file_path}")
            
            # Environment Variables
            env_vars = config.get('env_vars', {})
            if env_vars:
                print(f"\n🔧 Environment Variables: {len(env_vars)}")
                for key in env_vars.keys():
                    print(f"   • {key}")
            
            # User Accounts
            accounts = config.get('accounts', {})
            users = accounts.get('users', [])
            user_groups = accounts.get('user_groups', [])
            if users or user_groups:
                print(f"\n👤 User Accounts: {len(users)}")
                for user in users:
                    username = user.get('username', 'Unknown')
                    first_name = user.get('first_name', '')
                    last_name = user.get('last_name', '')
                    email = user.get('email', '')
                    role = user.get('role', 'N/A')
                    user_group = user.get('user_group', 'N/A')
                    password = user.get('password')
                    print(f"   • {username} ({first_name} {last_name}, {role}, group: {user_group})")
                    if email:
                        print(f"     Email: {email}")
                    if password:
                        print(f"     Password: {password}")
                    elif password is None:
                        print(f"     Password: (keep existing)")
                if user_groups:
                    # Count users per group
                    user_group_counts = {}
                    for user in users:
                        user_group_name = user.get('user_group', '').lower()
                        if user_group_name:
                            user_group_counts[user_group_name] = user_group_counts.get(user_group_name, 0) + 1
                    
                    print(f"\n   User Groups: {len(user_groups)}")
                    for ug in user_groups:
                        title = ug.get('title', 'Unknown')
                        # Match user group title (case-insensitive) to count users
                        title_lower = title.lower()
                        user_count = user_group_counts.get(title_lower, 0)
                        print(f"   • {title} (Users Count: {user_count})")
            
            # Missing/Not Implemented Features
            missing_features = []
            sys_settings = config.get('system_settings', {})
            if sys_settings:
                interface = sys_settings.get('system_interface', {})
                icons = interface.get('icons', '')
                if icons and icons.strip():
                    missing_features.append("Icons directory upload (configured but not yet implemented)")
            
            # Check for user group assignments (if any are configured)
            accounts = config.get('accounts', {})
            user_groups = accounts.get('user_groups', [])
            has_assignments = False
            for ug in user_groups:
                subject_groups = ug.get('subject_groups', [])
                camera_groups = ug.get('camera_groups', [])
                if subject_groups or camera_groups:
                    has_assignments = True
                    break
            if has_assignments:
                missing_features.append("User group assignments to subject/camera groups (configured but not yet implemented)")
            
            if missing_features:
                print(f"\n⚠️  Features Configured But Not Yet Implemented:")
                for feature in missing_features:
                    print(f"   • {feature}")
            
            print("\n" + "=" * 70)
            print("Note: This is the dataset from config.yaml.")
            print("You can customize it by editing config.yaml before running automation.")
            print("=" * 70 + "\n")
        except Exception as e:
            print(f"\n❌ Error loading dataset: {e}\n", file=sys.stderr)
            sys.exit(1)
        sys.exit(0)
    
    # Configure logging
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        # In verbose mode, show full tracebacks
        sys.excepthook = _original_excepthook
    elif args.quiet:
        logging.getLogger().setLevel(logging.ERROR)
        # In quiet mode, suppress tracebacks
        sys.excepthook = _clean_excepthook
    else:
        # In normal mode, suppress tracebacks (show user-friendly messages only)
        sys.excepthook = _clean_excepthook
    
    # Setup log file if specified
    if args.log_file:
        file_handler = logging.FileHandler(args.log_file)
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
        logging.getLogger().addHandler(file_handler)
    
    # Handle --set-ip option (must be done before creating OnWatchAutomation)
    if args.set_ip:
        config_manager = ConfigManager(config_path=args.config)
        success, message = config_manager.update_ip_address(args.set_ip, backup=True)
        if success:
            logger.info(f"✓ {message}")
            logger.info(f"✓ Configuration file updated: {args.config}")
            logger.info("✓ You can now run the automation with: python3 main.py")
        else:
            logger.error(f"❌ {message}")
            sys.exit(1)
        sys.exit(0)
    
    automation = OnWatchAutomation(config_path=args.config)
    
    # Handle step execution
    if args.step:
        step_mapping = {
            'init-api': lambda: automation.initialize_api_client(),
            'set-kv-params': lambda: asyncio.run(automation.set_kv_parameters()),
            'configure-system': lambda: asyncio.run(automation.configure_system_settings()),
            'configure-groups': lambda: asyncio.run(automation.configure_groups()),
            'configure-accounts': lambda: asyncio.run(automation.configure_accounts()),
            'populate-watchlist': lambda: automation.populate_watch_list(),
            'configure-devices': lambda: asyncio.run(automation.configure_devices()),
            'configure-inquiries': lambda: asyncio.run(automation.configure_inquiries()),
            'upload-mass-import': lambda: asyncio.run(automation.configure_mass_import()),
            'configure-rancher': lambda: automation.configure_rancher(),
            'upload-files': lambda: asyncio.run(automation.upload_files())
        }
        
        # Some steps need API client initialized first
        if args.step in ['set-kv-params', 'populate-watchlist']:
            automation.initialize_api_client()
        
        if args.step in step_mapping:
            step_mapping[args.step]()
        else:
            logger.error(f"Invalid step: {args.step}. Use --list-steps to see available steps.")
            sys.exit(1)
        return
    
    # Handle validate-only mode
    if args.validate:
        is_valid, errors = automation.validate_config(verbose=True)
        if is_valid:
            logger.info("\n✓ Configuration is valid")
            sys.exit(0)
        else:
            logger.error(f"\n❌ Configuration validation failed with {len(errors)} error(s)")
            sys.exit(1)
    
    # Handle dry-run mode
    if args.dry_run:
        is_valid, errors = automation.validate_config(verbose=True)
        if not is_valid:
            logger.error(f"\n❌ Configuration validation failed. Cannot proceed with dry-run.")
            sys.exit(1)
        logger.info("\n" + "=" * 80)
        logger.info("DRY-RUN MODE: Showing what would be executed")
        logger.info("=" * 80)
        logger.info("\nThe following steps would be executed:")
        logger.info("  1. Initialize API client")
        logger.info("  2. Set KV parameters")
        logger.info("  3. Configure system settings")
        logger.info("  4. Configure groups")
        logger.info("  5. Configure accounts")
        logger.info("  6. Populate watch list")
        logger.info("  7. Configure devices")
        logger.info("  8. Configure inquiries")
        logger.info("  9. Upload mass import")
        logger.info("  10. Upload translation file")
        logger.info("  11. Configure Rancher")
        logger.info("\n✓ Dry-run completed - no actual changes were made")
        sys.exit(0)
    
    automation = OnWatchAutomation(config_path=args.config)
    
    # Handle step execution
    if args.step:
        step_mapping = {
            'init-api': lambda: automation.initialize_api_client(),
            'set-kv-params': lambda: asyncio.run(automation.set_kv_parameters()),
            'configure-system': lambda: asyncio.run(automation.configure_system_settings()),
            'configure-groups': lambda: asyncio.run(automation.configure_groups()),
            'configure-accounts': lambda: asyncio.run(automation.configure_accounts()),
            'populate-watchlist': lambda: automation.populate_watch_list(),
            'configure-devices': lambda: asyncio.run(automation.configure_devices()),
            'configure-inquiries': lambda: asyncio.run(automation.configure_inquiries()),
            'upload-mass-import': lambda: asyncio.run(automation.configure_mass_import()),
            'configure-rancher': lambda: automation.configure_rancher(),
            'upload-files': lambda: asyncio.run(automation.upload_files())
        }
        
        # Some steps need API client initialized first
        if args.step in ['set-kv-params', 'populate-watchlist']:
            automation.initialize_api_client()
        
        if args.step in step_mapping:
            step_mapping[args.step]()
        else:
            logger.error(f"Invalid step: {args.step}. Use --list-steps to see available steps.")
            sys.exit(1)
        return
    
    # Handle validate-only mode
    if args.validate:
        is_valid, errors = automation.validate_config(verbose=True)
        if is_valid:
            logger.info("\n✓ Configuration is valid")
            sys.exit(0)
        else:
            logger.error(f"\n❌ Configuration validation failed with {len(errors)} error(s)")
            sys.exit(1)
    
    # Handle dry-run mode
    if args.dry_run:
        is_valid, errors = automation.validate_config(verbose=True)
        if not is_valid:
            logger.error(f"\n❌ Configuration validation failed. Cannot proceed with dry-run.")
            sys.exit(1)
        logger.info("\n" + "=" * 80)
        logger.info("DRY-RUN MODE: Showing what would be executed")
        logger.info("=" * 80)
        logger.info("\nThe following steps would be executed:")
        logger.info("  1. Initialize API client")
        logger.info("  2. Set KV parameters")
        logger.info("  3. Configure system settings")
        logger.info("  4. Configure groups")
        logger.info("  5. Configure accounts")
        logger.info("  6. Populate watch list")
        logger.info("  7. Configure devices")
        logger.info("  8. Configure inquiries")
        logger.info("  9. Upload mass import")
        logger.info("  10. Upload translation file")
        logger.info("  11. Configure Rancher")
        logger.info("\n✓ Dry-run completed - no actual changes were made")
        sys.exit(0)
    
    # Run full automation
    # Run automation with clean error handling
    try:
        asyncio.run(automation.run())
    except Exception as e:
        # This should not normally be reached since run() catches all exceptions,
        # but if it does, show user-friendly message
        error_message = str(e)
        logger.error(f"\n❌ FATAL ERROR: {error_message}")
        logger.error("Automation stopped due to fatal error")
        # Only show traceback in verbose mode
        root_logger = logging.getLogger()
        if root_logger.level <= logging.DEBUG:
            import traceback
            logger.debug("\nFull traceback (verbose mode):")
            logger.debug("", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()


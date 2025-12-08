#!/usr/bin/env python3
"""
Main automation script for populating OnWatch system with data.
This script orchestrates automation tasks via REST API, GraphQL API, and Rancher configuration.
"""
import asyncio
import yaml
import os
import sys
import logging
import time
from pathlib import Path
from client_api import ClientApi
from rancher_api import RancherApi

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class OnWatchAutomation:
    """Main automation orchestrator."""
    
    def __init__(self, config_path="config.yaml"):
        """
        Initialize automation with configuration.
        
        Args:
            config_path: Path to YAML configuration file
        """
        self.config_path = config_path
        self.config = self.load_config()
        self.client_api = None
        self.rancher_automation = None
    
    def load_config(self):
        """Load configuration from YAML file."""
        try:
            with open(self.config_path, 'r') as f:
                config = yaml.safe_load(f)
            logger.info(f"Configuration loaded from {self.config_path}")
            return config
        except FileNotFoundError:
            logger.error(f"Configuration file not found: {self.config_path}")
            sys.exit(1)
        except yaml.YAMLError as e:
            logger.error(f"Error parsing YAML: {e}")
            sys.exit(1)
    
    def initialize_api_client(self):
        """Initialize the API client."""
        onwatch_config = self.config['onwatch']
        self.client_api = ClientApi(
            ip_address=onwatch_config['ip_address'],
            username=onwatch_config['username'],
            password=onwatch_config['password']
        )
        self.client_api.login()
        logger.info("API client initialized and logged in")
    
    async def set_kv_parameters(self):
        """Set KV parameters via API."""
        kv_params = self.config.get('kv_parameters', {})
        if not kv_params:
            logger.info("No KV parameters to set")
            return
        
        logger.info("Setting KV parameters...")
        
        # Initialize client if needed
        if not self.client_api:
            self.initialize_api_client()
        
        for key, value in kv_params.items():
            try:
                self.client_api.set_kv_parameter(key, value)
                logger.info(f"✓ Set KV parameter: {key} = {value}")
            except Exception as e:
                logger.error(f"Failed to set KV parameter {key}: {e}")
                raise
    
    async def configure_system_settings(self):
        """Configure system settings via API."""
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
                        self.client_api.create_acknowledge_action(map_settings['action_title'], description="")
                        logger.info(f"✓ Created acknowledge action: {map_settings['action_title']}")
                    except Exception as e:
                        logger.warning(f"Could not create acknowledge action: {e}")
                        logger.warning("Continuing with other settings...")
            
            # Handle logo uploads
            # Use "me.jpg" from Yonatan subject for company and sidebar logos
            watch_list = self.config.get('watch_list', {}).get('subjects', [])
            logo_path = None
            for subject in watch_list:
                if subject.get('name') == 'Yonatan':
                    images = subject.get('images', [])
                    for img in images:
                        img_path = img.get('path', '') if isinstance(img, dict) else img
                        if 'me.jpg' in img_path:
                            if not os.path.isabs(img_path):
                                config_dir = os.path.dirname(os.path.abspath(self.config_path))
                                logo_path = os.path.join(config_dir, img_path)
                            else:
                                logo_path = img_path
                            break
                    if logo_path:
                        break
            
            # Upload company and sidebar logos (use me.jpg)
            if logo_path and os.path.exists(logo_path):
                for logo_type in ["company", "sidebar"]:
                    try:
                        self.client_api.upload_logo(logo_path, logo_type)
                        logger.info(f"✓ Uploaded {logo_type} logo")
                    except Exception as e:
                        logger.warning(f"Could not upload {logo_type} logo: {e}")
                        logger.warning("Continuing with other settings...")
            elif logo_path:
                logger.warning(f"Logo image not found: {logo_path}")
            else:
                logger.warning("Could not find 'me.jpg' image from Yonatan subject in watch_list")
            
            # Upload favicon (use favicon.ico from images directory)
            config_dir = os.path.dirname(os.path.abspath(self.config_path))
            favicon_path = os.path.join(config_dir, "images", "favicon.ico")
            if os.path.exists(favicon_path):
                try:
                    self.client_api.upload_logo(favicon_path, "favicon")
                    logger.info("✓ Uploaded favicon logo")
                except Exception as e:
                    logger.warning(f"Could not upload favicon logo: {e}")
            else:
                logger.warning(f"Favicon not found at {favicon_path}")
                
        except Exception as e:
            logger.error(f"Failed to configure system settings via API: {e}")
            raise
    
    async def configure_devices(self):
        """Configure devices/cameras via GraphQL API."""
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
            logger.info(f"Found {len(camera_group_map)} existing camera groups")
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
            logger.info(f"Found {len(existing_camera_names)} existing cameras")
        except Exception as e:
            logger.warning(f"Could not fetch existing cameras: {e}")
            existing_camera_names = set()
        
        # Create each camera
        logger.info(f"Creating {len(devices)} cameras...")
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
                    logger.warning(f"Camera '{name}' already exists, skipping")
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
                
                # Create camera via GraphQL
                self.client_api.create_camera(
                    name=name,
                    video_url=video_url,
                    camera_group_id=camera_group_id,
                    threshold=threshold,
                    location=location,
                    calibration=calibration,
                    security_access=security_access
                )
                logger.info(f"✓ Created camera: {name}")
                created_count += 1
                existing_camera_names.add(name.lower())  # Track created camera
                
            except Exception as e:
                logger.error(f"Failed to create camera '{device_config.get('name', 'unknown')}': {e}")
                skipped_count += 1
        
        logger.info(f"Devices configuration complete: {created_count} created, {skipped_count} skipped")
    
    def populate_watch_list(self):
        """Populate watch list with subjects via API."""
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
            
            logger.info(f"Found {len(group_map)} groups")
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
                
                # Add subject with first image
                response = self.client_api.add_subject_from_image(name, image_path, group_id)
                logger.info(f"Added subject to watch list: {name} (image: {image_path})")
                
                # Add additional images if any (e.g., Yonatan has 2 images)
                if len(images) > 1:
                    try:
                        subject_data = response.json() if hasattr(response, 'json') else {}
                        subject_id = subject_data.get('id')
                        
                        if subject_id:
                            for additional_img_info in images[1:]:
                                additional_img_path = additional_img_info.get('path') if isinstance(additional_img_info, dict) else additional_img_info
                                
                                if additional_img_path:
                                    # Resolve relative paths to absolute paths (relative to project root)
                                    if not os.path.isabs(additional_img_path):
                                        additional_img_path = os.path.join(project_root, additional_img_path)
                                    
                                    if os.path.exists(additional_img_path):
                                        try:
                                            self.client_api.add_image_to_subject(subject_id, additional_img_path)
                                            logger.info(f"Added additional image to {name}: {additional_img_path}")
                                        except Exception as e:
                                            logger.warning(f"Could not add additional image {additional_img_path} to {name}: {e}")
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
                logger.error(f"Error adding subject {subject_name}: {e}", exc_info=True)
    
    async def configure_groups(self):
        """Configure groups and profiles via API."""
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
            logger.info(f"Creating {len(subject_groups)} subject groups...")
            
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
                
                logger.info(f"Found {len(existing_group_list)} existing groups")
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
                        logger.info(f"Subject group '{name}' already exists as '{matching_existing}', skipping")
                        continue
                    
                    authorization = group_config.get('authorization', 'Always Unauthorized')
                    visibility = group_config.get('visibility', 'Silent')
                    priority = group_config.get('priority', 0)
                    description = group_config.get('description', '')
                    color = group_config.get('color', '#D20300')
                    camera_groups = group_config.get('camera_groups', None)
                    
                    self.client_api.create_subject_group(
                        name=name,
                        authorization=authorization,
                        visibility=visibility,
                        priority=priority,
                        description=description,
                        color=color,
                        camera_groups=camera_groups
                    )
                    logger.info(f"✓ Created subject group: {name}")
                    
                except Exception as e:
                    logger.error(f"Failed to create subject group '{group_config.get('name', 'unknown')}': {e}")
        
        # Device groups - TODO: implement once endpoint is available
        device_groups = groups.get('device_groups', [])
        if device_groups:
            logger.warning(f"Device groups configuration not yet implemented ({len(device_groups)} groups skipped)")
            logger.warning("Device groups use a different API endpoint - will be implemented when endpoint details are available")
        
        # Time profile - manual/screenshot based, not API-driven
        time_profile = groups.get('time_profile')
        if time_profile:
            logger.info("Time profile configuration requires manual setup or screenshot reference")
            logger.info(f"Reference: {time_profile.get('screenshot_reference', 'N/A')}")
    
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
            logger.info(f"Found {len(role_map)} roles")
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
            logger.info(f"Found {len(user_group_map)} user groups")
        except Exception as e:
            logger.warning(f"Could not get user groups: {e}")
        
        # Process users
        users = accounts.get('users', [])
        if users:
            logger.info(f"Creating {len(users)} users...")
            
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
                logger.info(f"Found {len(existing_usernames)} existing users")
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
                        logger.info(f"User '{username}' already exists, skipping")
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
                            logger.info(f"Generated password for user '{username}': {password}")
                        else:
                            logger.warning(f"Cannot generate password for user without username, skipping")
                            continue
                    elif password == "":
                        # Empty string means skip password field (keep existing password)
                        password = None
                        logger.info(f"Skipping password for user '{username}' (keep existing)")
                    
                    # Create user
                    self.client_api.create_user(
                        username=username,
                        first_name=first_name,
                        last_name=last_name,
                        email=email,
                        role_id=role_id,
                        user_group_id=user_group_id,
                        password=password
                    )
                    logger.info(f"✓ Created user: {username}")
                    
                except Exception as e:
                    logger.error(f"Failed to create user '{user_config.get('username', 'unknown')}': {e}")
        
        # User groups - TODO: implement creation if endpoint is available
        user_groups_config = accounts.get('user_groups', [])
        if user_groups_config:
            logger.warning(f"User groups creation not yet implemented ({len(user_groups_config)} groups skipped)")
            logger.warning("User groups may need to be created manually or via different endpoint")
    
    async def configure_inquiries(self):
        """Configure inquiries via API."""
        inquiries = self.config.get('inquiries', [])
        if not inquiries:
            logger.info("No inquiries to configure")
            return
        
        logger.info(f"Configuring {len(inquiries)} inquiry cases...")
        
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
                
                priority = inquiry_config.get('priority', 'Medium')
                
                # Create inquiry case
                logger.info(f"Creating inquiry case: {inquiry_name}")
                case_result = self.client_api.create_inquiry_case(inquiry_name)
                case_id = case_result.get('id')
                if not case_id:
                    logger.error(f"Failed to get case ID for '{inquiry_name}'")
                    continue
                
                # Update priority if specified
                if priority:
                    try:
                        self.client_api.update_inquiry_case(case_id, priority=priority)
                        logger.info(f"Set inquiry priority to: {priority}")
                    except Exception as e:
                        logger.warning(f"Could not set priority for inquiry '{inquiry_name}': {e}")
                
                # Process each file
                logger.info(f"Adding {len(files_config)} files to inquiry case...")
                file_ids_map = {}  # filename -> file_id (uploadId)
                
                for file_config in files_config:
                    try:
                        file_path = file_config.get('path', '').strip()
                        if not file_path:
                            logger.warning(f"File entry missing path: {file_config}")
                            continue
                        
                        settings = file_config.get('settings', '').strip()
                        filename = os.path.basename(file_path)
                        
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
                        logger.info(f"Preparing upload for: {filename}")
                        prepare_result = self.client_api.prepare_forensic_upload(filename, with_analysis=True)
                        upload_id = prepare_result.get('id') or prepare_result.get('uploadId')
                        if not upload_id:
                            logger.error(f"Failed to get upload ID for '{filename}'")
                            continue
                        
                        # Step 2: Upload file
                        logger.info(f"Uploading file: {filename}")
                        self.client_api.upload_forensic_file(full_file_path, upload_id)
                        
                        # Step 3: Add file to case
                        # Use default threshold (0.5) unless it's Neo.webm with custom settings
                        threshold = 0.5
                        if filename.lower() == 'neo.webm' and settings.lower() == 'custom':
                            threshold = 0.37  # Will be updated via GraphQL later
                        
                        logger.info(f"Adding file to case: {filename}")
                        add_result = self.client_api.add_file_to_inquiry_case(
                            case_id, upload_id, filename, threshold=threshold
                        )
                        
                        # Store upload_id for potential configuration update
                        file_ids_map[filename] = upload_id
                        
                        logger.info(f"✓ Added file to inquiry: {filename}")
                        
                        # Store Neo.webm upload_id for configuration after all files are added
                        if filename.lower() == 'neo.webm' and settings.lower() == 'custom':
                            file_ids_map['neo_webm_configure'] = upload_id
                        
                    except Exception as e:
                        logger.error(f"Failed to process file '{file_config.get('path', 'unknown')}': {e}")
                        continue
                
                # Configure Neo.webm ROI and threshold, then restart analysis
                if 'neo_webm_configure' in file_ids_map:
                    neo_webm_upload_id = file_ids_map['neo_webm_configure']
                    logger.info("Configuring Neo.webm ROI and threshold...")
                    
                    # Wait a moment for files to be registered
                    time.sleep(2)
                    
                    try:
                        # Get the file from the case to get its actual ID
                        case_files = self.client_api.get_inquiry_case_files(case_id)
                        neo_webm_file_id = None
                        neo_webm_status = None
                        
                        for case_file in case_files:
                            if case_file.get('fileName', '').lower() == 'neo.webm':
                                # Use cameraId for GraphQL mutations (updateFileMediaData and startAnalyzeFilesCase)
                                neo_webm_file_id = case_file.get('cameraId', '')
                                neo_webm_status = case_file.get('status', '')
                                logger.info(f"Neo.webm cameraId: {neo_webm_file_id}, status: {neo_webm_status}")
                                break
                        
                        if neo_webm_file_id:
                            # Update ROI and threshold configuration
                            try:
                                self.client_api.update_file_media_data(
                                    file_id=neo_webm_file_id,
                                    threshold=0.37,
                                    camera_padding={
                                        'top': 15,
                                        'right': 15,
                                        'bottom': 22,
                                        'left': 0
                                    }
                                )
                                logger.info(f"✓ Updated Neo.webm configuration (ROI: top=15, right=15, bottom=22, left=0, threshold=0.37)")
                                
                                # Restart analysis with new configuration
                                logger.info("Restarting analysis for Neo.webm with new configuration...")
                                try:
                                    self.client_api.start_analyze_files_case(case_id, [neo_webm_file_id])
                                    logger.info("✓ Restarted analysis for Neo.webm")
                                except Exception as analyze_error:
                                    logger.warning(f"Could not restart analysis: {analyze_error}")
                                    logger.warning("Analysis may need to be started manually in the UI")
                            except Exception as update_error:
                                logger.error(f"Failed to update Neo.webm configuration: {update_error}")
                                logger.warning("You may need to manually update the ROI configuration in the UI")
                        else:
                            logger.warning("Could not find Neo.webm file in case to configure")
                    except Exception as e:
                        logger.warning(f"Could not configure Neo.webm: {e}")
                
                logger.info(f"✓ Completed inquiry case: {inquiry_name}")
                
            except Exception as e:
                logger.error(f"Failed to configure inquiry '{inquiry_config.get('name', 'unknown')}': {e}")
                continue
        
        logger.info("Inquiries configuration complete")
    
    async def configure_mass_import(self):
        """Upload mass import file and wait for completion."""
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
            self.client_api.upload_mass_import_file(full_file_path, upload_id)
            logger.info(f"✓ Uploaded mass import file: {filename}")
            logger.info(f"✓ Mass import '{mass_import_name}' upload started successfully")
            logger.info("Processing will continue in the background. Check the UI for status updates.")
            logger.info("Note: You may need to manually resolve issues in the mass import report after processing completes.")
        except Exception as e:
            logger.error(f"Failed to upload mass import file: {e}")
            return
        
        logger.info("Mass import configuration complete")
    
    def configure_rancher(self):
        """
        Configure Rancher environment variables via REST API (Step 10).
        
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
        if not env_vars:
            logger.info("No Rancher environment variables to set")
            return
        
        rancher_config = self.config.get('rancher', {})
        if not rancher_config:
            logger.warning("Rancher configuration not found in config.yaml")
            logger.warning("Skipping Rancher environment variable configuration")
            return
        
        # Validate required Rancher config fields
        required_fields = ['ip_address', 'port', 'username', 'password']
        missing_fields = [field for field in required_fields if not rancher_config.get(field)]
        if missing_fields:
            logger.error(f"Missing required Rancher configuration fields: {', '.join(missing_fields)}")
            logger.error("Skipping Rancher environment variable configuration")
            return
        
        logger.info("Configuring Rancher environment variables via API...")
        base_url = rancher_config.get('base_url') or f"https://{rancher_config['ip_address']}:{rancher_config['port']}"
        
        try:
            # Initialize Rancher API client
            rancher_api = RancherApi(
                base_url=base_url,
                username=rancher_config['username'],
                password=rancher_config['password']
            )
            rancher_api.login()
            
            # Extract workload_id and project_id from workload_path if provided
            # Default values for cv-engine workload
            workload_id = "statefulset:default:cv-engine"
            project_id = "local:p-p6l45"
            
            workload_path = rancher_config.get('workload_path', '')
            if workload_path:
                # Parse workload_path URL to extract IDs
                # Format: /p/local:p-p6l45/workloads/run?launchConfigIndex=-1&namespaceId=default&upgrade=true&workloadId=statefulset%3Adefault%3Acv-engine
                if 'workloadId=' in workload_path:
                    import urllib.parse
                    parsed = urllib.parse.parse_qs(urllib.parse.urlparse(workload_path).query)
                    if 'workloadId' in parsed:
                        workload_id = urllib.parse.unquote(parsed['workloadId'][0])
                    if '/p/' in workload_path:
                        project_id = workload_path.split('/p/')[1].split('/')[0]
            
            # Update environment variables in the workload
            rancher_api.update_workload_environment_variables(
                env_vars=env_vars,
                workload_id=workload_id,
                project_id=project_id
            )
            logger.info(f"✓ Successfully configured {len(env_vars)} environment variables in Rancher")
        except Exception as e:
            logger.error(f"Failed to configure Rancher environment variables: {e}")
            raise
    
    async def upload_files(self):
        """
        Upload general files (translation files, icons directory).
        
        Note: This step is for translation files and icons directory uploads.
        Currently, translation files are loaded via bash script to the service
        as no API endpoint is available. This step will be implemented once
        an API endpoint becomes available or SSH/SCP upload is added.
        """
        translation_file = self.config.get('system_settings', {}).get('system_interface', {}).get('translation_file', '')
        icons = self.config.get('system_settings', {}).get('system_interface', {}).get('icons', '')
        
        if not translation_file and not icons:
            logger.info("No translation file or icons directory specified in config")
            return
        
        logger.warning("File uploads (translation files, icons) require API endpoint - not yet implemented")
        if translation_file:
            logger.info(f"Translation file configured: {translation_file} (requires manual upload via bash script)")
        if icons:
            logger.info(f"Icons directory configured: {icons} (requires manual upload)")
        logger.info("See config.yaml comments for manual setup instructions")
    
    async def run(self):
        """Run the complete automation process."""
        logger.info("=" * 60)
        logger.info("Starting OnWatch Data Population Automation")
        logger.info("=" * 60)
        
        try:
            # Step 1: Initialize API client
            logger.info("\n[Step 1/11] Initializing API client...")
            self.initialize_api_client()
            
            # Step 2: Set KV parameters
            logger.info("\n[Step 2/11] Setting KV parameters...")
            await self.set_kv_parameters()
            
            # Step 3: Configure system settings
            logger.info("\n[Step 3/11] Configuring system settings...")
            await self.configure_system_settings()
            
            # Step 4: Configure groups and profiles
            logger.info("\n[Step 4/11] Configuring groups and profiles...")
            await self.configure_groups()
            
            # Step 5: Configure accounts
            logger.info("\n[Step 5/11] Configuring accounts...")
            await self.configure_accounts()
            
            # Step 6: Populate watch list
            logger.info("\n[Step 6/11] Populating watch list...")
            self.populate_watch_list()
            
            # Step 7: Configure devices
            logger.info("\n[Step 7/11] Configuring devices...")
            await self.configure_devices()
            
            # Step 8: Configure inquiries
            logger.info("\n[Step 8/11] Configuring inquiries...")
            await self.configure_inquiries()
            
            # Step 9: Upload mass import
            logger.info("\n[Step 9/11] Uploading mass import...")
            await self.configure_mass_import()
            
            # Step 10: Configure Rancher
            logger.info("\n[Step 10/11] Configuring Rancher...")
            await self.configure_rancher()
            
            # Step 11: Upload files
            logger.info("\n[Step 11/11] Uploading files...")
            await self.upload_files()
            
            logger.info("\n" + "=" * 60)
            logger.info("Automation completed successfully!")
            logger.info("=" * 60)
            
        except Exception as e:
            logger.error(f"Automation failed: {e}", exc_info=True)
            sys.exit(1)


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='OnWatch Data Population Automation')
    parser.add_argument(
        '--config',
        type=str,
        default='config.yaml',
        help='Path to configuration YAML file (default: config.yaml)'
    )
    parser.add_argument(
        '--step',
        type=int,
        help='Run only a specific step (1-11)'
    )
    
    args = parser.parse_args()
    
    automation = OnWatchAutomation(config_path=args.config)
    
    if args.step:
        # Steps that need API client initialized first
        if args.step in [2, 6]:  # KV parameters and watch list need API client
            automation.initialize_api_client()
        
        steps = {
            1: lambda: automation.initialize_api_client(),
            2: lambda: asyncio.run(automation.set_kv_parameters()),
            3: lambda: asyncio.run(automation.configure_system_settings()),
            4: lambda: asyncio.run(automation.configure_groups()),
            5: lambda: asyncio.run(automation.configure_accounts()),
            6: lambda: automation.populate_watch_list(),
            7: lambda: asyncio.run(automation.configure_devices()),
            8: lambda: asyncio.run(automation.configure_inquiries()),
            9: lambda: asyncio.run(automation.configure_mass_import()),
            10: lambda: automation.configure_rancher(),
            11: lambda: asyncio.run(automation.upload_files()),
        }
        if args.step in steps:
            steps[args.step]()
        else:
            logger.error(f"Invalid step number: {args.step}. Must be 1-11.")
    else:
        asyncio.run(automation.run())


if __name__ == "__main__":
    main()


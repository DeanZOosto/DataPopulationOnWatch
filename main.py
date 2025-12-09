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
import re
from pathlib import Path
from client_api import ClientApi
from rancher_api import RancherApi
from ssh_util import SSHUtil

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class RunSummary:
    """Track and report automation run summary."""
    
    def __init__(self):
        self.steps = {}
        self.errors = []
        self.warnings = []
        self.skipped = []
        self.manual_actions_needed = []
    
    def record_step(self, step_num, step_name, status, message="", manual_action=False):
        """
        Record step execution result.
        
        Args:
            step_num: Step number (1-11)
            step_name: Step name
            status: 'success', 'failed', 'skipped', 'partial'
            message: Additional message
            manual_action: Whether manual action is needed
        """
        self.steps[step_num] = {
            'name': step_name,
            'status': status,
            'message': message,
            'manual_action': manual_action
        }
        if status == 'failed':
            self.errors.append(f"Step {step_num}: {step_name} - {message}")
        if manual_action:
            self.manual_actions_needed.append(f"Step {step_num}: {step_name} - {message}")
    
    def add_warning(self, message):
        """Add a warning message."""
        self.warnings.append(message)
    
    def add_skipped(self, item_type, item_name, reason=""):
        """Record a skipped item."""
        self.skipped.append(f"{item_type}: {item_name}" + (f" ({reason})" if reason else ""))
    
    def print_summary(self):
        """Print a comprehensive summary of the run."""
        logger.info("\n" + "=" * 80)
        logger.info("AUTOMATION RUN SUMMARY")
        logger.info("=" * 80)
        
        # Step-by-step status
        logger.info("\n📋 Step Status:")
        for step_num in sorted(self.steps.keys()):
            step = self.steps[step_num]
            status_icon = {
                'success': '✅',
                'failed': '❌',
                'skipped': '⏭️',
                'partial': '⚠️'
            }.get(step['status'], '❓')
            
            logger.info(f"  {status_icon} Step {step_num}: {step['name']} - {step['status'].upper()}")
            if step['message']:
                logger.info(f"     {step['message']}")
        
        # Statistics
        total_steps = len(self.steps)
        successful = sum(1 for s in self.steps.values() if s['status'] == 'success')
        failed = sum(1 for s in self.steps.values() if s['status'] == 'failed')
        skipped_steps = sum(1 for s in self.steps.values() if s['status'] == 'skipped')
        
        logger.info(f"\n📊 Statistics:")
        logger.info(f"  Total Steps: {total_steps}")
        logger.info(f"  ✅ Successful: {successful}")
        logger.info(f"  ❌ Failed: {failed}")
        logger.info(f"  ⏭️  Skipped: {skipped_steps}")
        
        # Skipped items
        if self.skipped:
            logger.info(f"\n⏭️  Skipped Items ({len(self.skipped)}):")
            for item in self.skipped[:20]:  # Show first 20
                logger.info(f"  - {item}")
            if len(self.skipped) > 20:
                logger.info(f"  ... and {len(self.skipped) - 20} more")
        
        # Errors
        if self.errors:
            logger.error(f"\n❌ ERRORS ({len(self.errors)}):")
            for error in self.errors:
                logger.error(f"  • {error}")
        
        # Manual actions needed
        if self.manual_actions_needed:
            logger.warning(f"\n⚠️  MANUAL ACTION REQUIRED ({len(self.manual_actions_needed)}):")
            for action in self.manual_actions_needed:
                logger.warning(f"  ⚠️  {action}")
            logger.warning("\n⚠️  Please review the items above and complete them manually in the UI.")
        
        # Warnings
        if self.warnings:
            logger.warning(f"\n⚠️  WARNINGS ({len(self.warnings)}):")
            for warning in self.warnings[:10]:  # Show first 10
                logger.warning(f"  • {warning}")
            if len(self.warnings) > 10:
                logger.warning(f"  ... and {len(self.warnings) - 10} more warnings")
        
        # Final status
        logger.info("\n" + "=" * 80)
        if failed == 0 and not self.manual_actions_needed:
            logger.info("✅ AUTOMATION COMPLETED SUCCESSFULLY")
        elif failed > 0:
            logger.error(f"❌ AUTOMATION COMPLETED WITH {failed} FAILED STEP(S)")
            logger.error("Please review the errors above and take manual action if needed.")
        else:
            logger.warning("⚠️  AUTOMATION COMPLETED WITH WARNINGS")
            logger.warning("Please review the warnings and manual actions needed above.")
        logger.info("=" * 80 + "\n")


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
        self.summary = RunSummary()
    
    def _substitute_env_vars(self, value):
        """Substitute environment variables in config values."""
        if not isinstance(value, str):
            return value
        
        # Handle ${VAR_NAME} format
        def replace_env(match):
            var_name = match.group(1)
            return os.getenv(var_name, match.group(0))
        
        # Replace ${VAR_NAME} patterns
        value = re.sub(r'\$\{([^}]+)\}', replace_env, value)
        
        # Handle $VAR_NAME format (simple, no braces)
        def replace_simple_env(match):
            var_name = match.group(1)
            return os.getenv(var_name, match.group(0))
        
        # Only replace $VAR if it's not part of ${VAR} and followed by non-alphanumeric
        value = re.sub(r'\$([A-Z_][A-Z0-9_]*)', replace_simple_env, value)
        
        return value
    
    def _recursive_substitute_env(self, obj):
        """Recursively substitute environment variables in config structure."""
        if isinstance(obj, dict):
            return {k: self._recursive_substitute_env(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._recursive_substitute_env(item) for item in obj]
        elif isinstance(obj, str):
            return self._substitute_env_vars(obj)
        else:
            return obj
    
    def load_config(self):
        """Load configuration from YAML file with environment variable substitution."""
        try:
            with open(self.config_path, 'r') as f:
                config = yaml.safe_load(f)
            
            # Substitute environment variables
            config = self._recursive_substitute_env(config)
            
            logger.info(f"Configuration loaded from {self.config_path}")
            return config
        except FileNotFoundError:
            logger.error(f"Configuration file not found: {self.config_path}")
            sys.exit(1)
        except yaml.YAMLError as e:
            logger.error(f"Error parsing YAML: {e}")
            sys.exit(1)
    
    def _validate_ip_address(self, ip_str, field_name):
        """Validate IP address format."""
        if not ip_str or not isinstance(ip_str, str):
            return False
        # IPv4 pattern
        ipv4_pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
        if re.match(ipv4_pattern, ip_str):
            parts = ip_str.split('.')
            return all(0 <= int(part) <= 255 for part in parts)
        return False
    
    def _validate_file_path(self, file_path, field_name, required=True):
        """Validate file path exists (if not using env var)."""
        if not file_path:
            if required:
                return False, f"{field_name}: File path is required"
            return True, None
        
        # Check if it's an environment variable placeholder
        if isinstance(file_path, str) and (file_path.startswith('${') or file_path.startswith('$')):
            return True, None
        
        # Resolve relative paths
        project_root = os.path.dirname(os.path.abspath(__file__))
        if not os.path.isabs(file_path):
            full_path = os.path.join(project_root, file_path)
        else:
            full_path = file_path
        
        if not os.path.exists(full_path):
            return False, f"{field_name}: File not found: {file_path} (resolved: {full_path})"
        return True, None
    
    def validate_config(self, verbose=False):
        """
        Validate configuration file structure and values.
        
        Args:
            verbose: If True, print detailed validation report
            
        Returns:
            tuple: (is_valid, errors_list)
        """
        errors = []
        warnings = []
        config = self.config
        
        if not config:
            errors.append("Configuration file is empty or invalid")
            return False, errors
        
        # Validate required sections
        required_sections = {
            'onwatch': ['ip_address', 'username', 'password'],
            'ssh': ['ip_address', 'username', 'password', 'translation_util_path'],
            'rancher': ['ip_address', 'port', 'username', 'password', 'base_url', 'workload_path']
        }
        
        for section, required_fields in required_sections.items():
            if section not in config:
                errors.append(f"Missing required section: '{section}'")
                continue
            
            section_config = config[section]
            if not isinstance(section_config, dict):
                errors.append(f"Section '{section}' must be a dictionary")
                continue
            
            # Validate required fields in section
            for field in required_fields:
                if field not in section_config:
                    errors.append(f"Section '{section}': Missing required field '{field}'")
                elif not section_config[field]:
                    # Check if it's an env var placeholder
                    field_value = section_config[field]
                    if isinstance(field_value, str) and (field_value.startswith('${') or field_value.startswith('$')):
                        continue  # Env var placeholder is OK
                    warnings.append(f"Section '{section}': Field '{field}' is empty (may cause errors)")
        
        # Validate IP addresses
        ip_fields = [
            ('onwatch', 'ip_address'),
            ('ssh', 'ip_address'),
            ('rancher', 'ip_address')
        ]
        
        for section, field in ip_fields:
            if section in config and field in config[section]:
                ip_value = config[section][field]
                # Skip if it's an env var
                if isinstance(ip_value, str) and (ip_value.startswith('${') or ip_value.startswith('$')):
                    continue
                if not self._validate_ip_address(ip_value, f"{section}.{field}"):
                    errors.append(f"Section '{section}': Invalid IP address format for '{field}': {ip_value}")
        
        # Validate file paths (if specified)
        project_root = os.path.dirname(os.path.abspath(__file__))
        
        # Validate translation file path
        if 'system_settings' in config and 'system_interface' in config['system_settings']:
            translation_file = config['system_settings']['system_interface'].get('translation_file')
            if translation_file:
                is_valid, error_msg = self._validate_file_path(translation_file, 'system_settings.system_interface.translation_file', required=False)
                if not is_valid:
                    errors.append(error_msg)
        
        # Validate watch list image paths
        if 'watch_list' in config:
            watch_list = config.get('watch_list', {})
            subjects = watch_list.get('subjects', []) if isinstance(watch_list, dict) else watch_list
            
            for idx, subject in enumerate(subjects):
                if not isinstance(subject, dict):
                    continue
                name = subject.get('name', f'subject_{idx}')
                images = subject.get('images', [])
                for img_idx, img in enumerate(images):
                    if isinstance(img, dict):
                        img_path = img.get('path', '')
                    else:
                        img_path = img if isinstance(img, str) else ''
                    
                    if img_path:
                        is_valid, error_msg = self._validate_file_path(img_path, f'watch_list.subjects[{idx}].images[{img_idx}]', required=False)
                        if not is_valid:
                            warnings.append(f"Subject '{name}': {error_msg}")
        
        # Validate mass import file path
        if 'mass_import' in config:
            mass_import_file = config['mass_import'].get('file_path')
            if mass_import_file:
                is_valid, error_msg = self._validate_file_path(mass_import_file, 'mass_import.file_path', required=False)
                if not is_valid:
                    warnings.append(error_msg)
        
        # Validate inquiry file paths
        if 'inquiries' in config:
            for idx, inquiry in enumerate(config['inquiries']):
                if not isinstance(inquiry, dict):
                    continue
                files = inquiry.get('files', {})
                # Handle both dict format and list format
                if isinstance(files, dict):
                    for filename, file_config in files.items():
                        if isinstance(file_config, dict):
                            file_path = file_config.get('path', '')
                        else:
                            file_path = file_config if isinstance(file_config, str) else ''
                        
                        if file_path:
                            is_valid, error_msg = self._validate_file_path(file_path, f'inquiries[{idx}].files.{filename}', required=False)
                            if not is_valid:
                                warnings.append(error_msg)
                elif isinstance(files, list):
                    for file_idx, file_item in enumerate(files):
                        if isinstance(file_item, dict):
                            file_path = file_item.get('path', '')
                        else:
                            file_path = file_item if isinstance(file_item, str) else ''
                        
                        if file_path:
                            is_valid, error_msg = self._validate_file_path(file_path, f'inquiries[{idx}].files[{file_idx}]', required=False)
                            if not is_valid:
                                warnings.append(error_msg)
        
        # Validate Rancher port
        if 'rancher' in config and 'port' in config['rancher']:
            port = config['rancher']['port']
            if not isinstance(port, int) or port < 1 or port > 65535:
                errors.append(f"Section 'rancher': Invalid port number: {port} (must be 1-65535)")
        
        if verbose:
            if errors:
                logger.error("Configuration Validation - ERRORS:")
                for error in errors:
                    logger.error(f"  ❌ {error}")
            if warnings:
                logger.warning("Configuration Validation - WARNINGS:")
                for warning in warnings:
                    logger.warning(f"  ⚠️  {warning}")
            if not errors and not warnings:
                logger.info("✓ Configuration validation passed with no errors or warnings")
            elif not errors:
                logger.info("✓ Configuration validation passed (warnings present but non-critical)")
        
        return len(errors) == 0, errors
    
    def initialize_api_client(self):
        """
        Initialize the OnWatch API client and authenticate.
        
        Reads OnWatch connection details from config.yaml (onwatch section)
        and establishes authenticated session with the OnWatch system.
        
        Raises:
            Exception: If authentication fails or connection cannot be established
        """
        onwatch_config = self.config['onwatch']
        self.client_api = ClientApi(
            ip_address=onwatch_config['ip_address'],
            username=onwatch_config['username'],
            password=onwatch_config['password']
        )
        self.client_api.login()
        logger.info("API client initialized and logged in")
    
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
        
        for key, value in kv_params.items():
            try:
                self.client_api.set_kv_parameter(key, value)
            except Exception as e:
                logger.error(f"Failed to set KV parameter {key}: {e}")
                raise
    
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
            
            # Upload favicon (use favicon.ico from assets/images directory)
            project_root = os.path.dirname(os.path.abspath(__file__))
            favicon_path = os.path.join(project_root, "assets", "images", "favicon.ico")
            if os.path.exists(favicon_path):
                try:
                    self.client_api.upload_logo(favicon_path, "favicon")
                    logger.info("✓ Uploaded favicon logo")
                except Exception as e:
                    logger.warning(f"Could not upload favicon logo: {e}")
            else:
                logger.debug(f"Favicon not found at {favicon_path} (optional, skipping)")
                
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
                camera_name = device_config.get('name', 'unknown')
                error_detail = str(e)
                logger.error(f"❌ Failed to create camera '{camera_name}': {error_detail}")
                logger.warning(f"⚠️  Camera '{camera_name}' was not created. You may need to create it manually in the UI.")
                self.summary.add_warning(f"Camera '{camera_name}' was not created - manual action may be needed")
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
        existing_subject_names = set()
        try:
            existing_subjects = self.client_api.get_subjects()
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
            
            logger.debug(f"Found {len(existing_subject_names)} existing subjects")
        except Exception as e:
            logger.debug(f"Could not fetch existing subjects for duplicate check: {e}")
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
                    logger.info(f"⏭️  Subject '{name}' already exists, skipping")
                    self.summary.add_skipped("Subject", name, "already exists")
                    skipped_count += 1
                    continue
                
                # Add subject with first image
                response = self.client_api.add_subject_from_image(name, image_path, group_id)
                logger.info(f"✓ Added subject to watch list: {name} (image: {os.path.basename(image_path)})")
                success_count += 1
                
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
                    username = user_config.get('username', 'unknown')
                    error_detail = str(e)
                    logger.error(f"❌ Failed to create user '{username}': {error_detail}")
                    logger.warning(f"⚠️  User '{username}' was not created. You may need to create it manually in the UI.")
                    self.summary.add_warning(f"User '{username}' was not created - manual action may be needed")
        
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
                    self.client_api.create_user_group(
                        title=title,
                        subject_groups=subject_group_ids,
                        camera_groups=camera_group_ids
                    )
                    logger.info(f"✓ Created user group: {title}")
                    
                except Exception as e:
                    title = ug_config.get('title', 'unknown') or ug_config.get('name', 'unknown')
                    error_detail = str(e)
                    logger.error(f"❌ Failed to create user group '{title}': {error_detail}")
                    logger.warning(f"⚠️  User group '{title}' was not created. You may need to create it manually in the UI.")
                    self.summary.add_warning(f"User group '{title}' was not created - manual action may be needed")
    
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
                
                priority = inquiry_config.get('priority', 'Medium')
                
                # Create inquiry case
                from client_api import InquiryCaseAlreadyExists
                try:
                    case_result = self.client_api.create_inquiry_case(inquiry_name)
                    case_id = case_result.get('id')
                    if not case_id:
                        logger.error(f"Failed to get case ID for '{inquiry_name}'")
                        continue
                except InquiryCaseAlreadyExists:
                    logger.info(f"⏭️  Inquiry case '{inquiry_name}' already exists, skipping")
                    self.summary.add_skipped("Inquiry Case", inquiry_name, "already exists")
                    continue
                
                # Update priority if specified
                if priority:
                    try:
                        self.client_api.update_inquiry_case(case_id, priority=priority)
                        logger.info(f"Set inquiry priority to: {priority}")
                    except Exception as e:
                        logger.warning(f"Could not set priority for inquiry '{inquiry_name}': {e}")
                
                # Process each file
                logger.debug(f"Adding {len(files_config)} files to inquiry case...")
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
                        # Use default threshold (0.5) unless it's Neo.webm with custom settings
                        threshold = 0.5
                        if filename.lower() == 'neo.webm' and settings.lower() == 'custom':
                            threshold = 0.37  # Will be updated via GraphQL later
                        
                        logger.debug(f"Adding file to case: {filename}")
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
                    logger.debug("Configuring Neo.webm ROI and threshold...")
                    
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
                else:
                    logger.error("Failed to upload translation file")
                    raise Exception("Translation file upload failed")
                    
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
        
        try:
            # Step 1: Initialize API client
            logger.info("\n[Step 1/11] Initializing API client...")
            try:
                self.initialize_api_client()
                self.summary.record_step(1, "Initialize API Client", "success", "API client initialized and logged in")
            except Exception as e:
                error_msg = f"Failed to initialize API client: {str(e)}"
                logger.error(f"❌ {error_msg}")
                logger.error("⚠️  MANUAL ACTION REQUIRED: Cannot proceed without API client. Please check credentials and network connectivity.")
                self.summary.record_step(1, "Initialize API Client", "failed", error_msg, manual_action=True)
                raise  # Cannot continue without API client
            
            # Step 2: Set KV parameters
            logger.info("\n[Step 2/11] Setting KV parameters...")
            try:
                await self.set_kv_parameters()
                self.summary.record_step(2, "Set KV Parameters", "success")
            except Exception as e:
                error_msg = f"Failed to set KV parameters: {str(e)}"
                logger.error(f"❌ {error_msg}")
                logger.error("⚠️  MANUAL ACTION REQUIRED: Please set KV parameters manually in the UI at /bt/settings/kv")
                self.summary.record_step(2, "Set KV Parameters", "failed", error_msg, manual_action=True)
            
            # Step 3: Configure system settings
            logger.info("\n[Step 3/11] Configuring system settings...")
            try:
                await self.configure_system_settings()
                self.summary.record_step(3, "Configure System Settings", "success")
            except Exception as e:
                error_msg = f"Failed to configure system settings: {str(e)}"
                logger.error(f"❌ {error_msg}")
                logger.error("⚠️  MANUAL ACTION REQUIRED: Please configure system settings manually in the UI")
                self.summary.record_step(3, "Configure System Settings", "failed", error_msg, manual_action=True)
            
            # Step 4: Configure groups and profiles
            logger.info("\n[Step 4/11] Configuring groups and profiles...")
            try:
                await self.configure_groups()
                self.summary.record_step(4, "Configure Groups", "success")
            except Exception as e:
                error_msg = f"Failed to configure groups: {str(e)}"
                logger.error(f"❌ {error_msg}")
                logger.error("⚠️  MANUAL ACTION REQUIRED: Please configure groups manually in the UI")
                self.summary.record_step(4, "Configure Groups", "failed", error_msg, manual_action=True)
            
            # Step 5: Configure accounts
            logger.info("\n[Step 5/11] Configuring accounts...")
            try:
                await self.configure_accounts()
                self.summary.record_step(5, "Configure Accounts", "success")
            except Exception as e:
                error_msg = f"Failed to configure accounts: {str(e)}"
                logger.error(f"❌ {error_msg}")
                logger.error("⚠️  MANUAL ACTION REQUIRED: Please configure accounts manually in the UI")
                self.summary.record_step(5, "Configure Accounts", "failed", error_msg, manual_action=True)
            
            # Step 6: Populate watch list
            logger.info("\n[Step 6/11] Populating watch list...")
            try:
                self.populate_watch_list()
                # Check if there were any failures (tracked in populate_watch_list)
                # If warnings exist for subjects, mark as partial
                subject_warnings = [w for w in self.summary.warnings if "Subject" in w and "was not added" in w]
                if subject_warnings:
                    self.summary.record_step(6, "Populate Watch List", "partial", f"Some subjects failed - see warnings", manual_action=True)
                else:
                    self.summary.record_step(6, "Populate Watch List", "success")
            except Exception as e:
                error_msg = f"Failed to populate watch list: {str(e)}"
                logger.error(f"❌ {error_msg}")
                logger.error("⚠️  MANUAL ACTION REQUIRED: Please add watch list subjects manually in the UI")
                self.summary.record_step(6, "Populate Watch List", "failed", error_msg, manual_action=True)
            
            # Step 7: Configure devices
            logger.info("\n[Step 7/11] Configuring devices...")
            try:
                await self.configure_devices()
                self.summary.record_step(7, "Configure Devices", "success")
            except Exception as e:
                error_msg = f"Failed to configure devices: {str(e)}"
                logger.error(f"❌ {error_msg}")
                logger.error("⚠️  MANUAL ACTION REQUIRED: Please configure devices manually in the UI")
                self.summary.record_step(7, "Configure Devices", "failed", error_msg, manual_action=True)
            
            # Step 8: Configure inquiries
            logger.info("\n[Step 8/11] Configuring inquiries...")
            try:
                await self.configure_inquiries()
                self.summary.record_step(8, "Configure Inquiries", "success")
            except Exception as e:
                error_msg = f"Failed to configure inquiries: {str(e)}"
                logger.error(f"❌ {error_msg}")
                logger.error("⚠️  MANUAL ACTION REQUIRED: Please configure inquiries manually in the UI")
                self.summary.record_step(8, "Configure Inquiries", "failed", error_msg, manual_action=True)
            
            # Step 9: Upload mass import
            logger.info("\n[Step 9/11] Uploading mass import...")
            try:
                await self.configure_mass_import()
                self.summary.record_step(9, "Upload Mass Import", "success", "File uploaded, processing continues in background")
            except Exception as e:
                error_msg = f"Failed to upload mass import: {str(e)}"
                logger.error(f"❌ {error_msg}")
                logger.error("⚠️  MANUAL ACTION REQUIRED: Please upload mass import file manually in the UI")
                self.summary.record_step(9, "Upload Mass Import", "failed", error_msg, manual_action=True)
            
            # Step 10: Configure Rancher
            logger.info("\n[Step 10/11] Configuring Rancher...")
            try:
                self.configure_rancher()
                self.summary.record_step(10, "Configure Rancher", "success")
            except Exception as e:
                error_msg = f"Failed to configure Rancher: {str(e)}"
                logger.error(f"❌ {error_msg}")
                logger.error("⚠️  MANUAL ACTION REQUIRED: Please configure Rancher environment variables manually")
                self.summary.record_step(10, "Configure Rancher", "failed", error_msg, manual_action=True)
            
            # Step 11: Upload files
            logger.info("\n[Step 11/11] Uploading files...")
            try:
                await self.upload_files()
                self.summary.record_step(11, "Upload Files", "success")
            except Exception as e:
                error_msg = f"Failed to upload files: {str(e)}"
                logger.error(f"❌ {error_msg}")
                logger.error("⚠️  MANUAL ACTION REQUIRED: Please upload translation file manually via SSH")
                self.summary.record_step(11, "Upload Files", "failed", error_msg, manual_action=True)
            
        except Exception as e:
            logger.error(f"\n❌ FATAL ERROR: Automation failed with exception: {e}", exc_info=True)
            logger.error("Automation stopped due to fatal error")
        
        # Print summary
        self.summary.print_summary()
        
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
  python3 main.py --step 6
  
  # Dry-run mode (validate and show what would be executed)
  python3 main.py --dry-run
  
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
        type=int,
        help='Run only a specific step (1-11)'
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
    
    args = parser.parse_args()
    
    # Handle list-steps
    if args.list_steps:
        steps = [
            (1, "Initialize API Client", "Initialize connection to OnWatch API"),
            (2, "Set KV Parameters", "Configure key-value parameters"),
            (3, "Configure System Settings", "Set general, map, engine, and interface settings"),
            (4, "Configure Groups", "Create subject groups"),
            (5, "Configure Accounts", "Create user accounts and user groups"),
            (6, "Populate Watch List", "Add subjects to watch list with images"),
            (7, "Configure Devices", "Create cameras/devices"),
            (8, "Configure Inquiries", "Create inquiry cases with file uploads"),
            (9, "Upload Mass Import", "Upload mass import file"),
            (10, "Configure Rancher", "Set Kubernetes environment variables"),
            (11, "Upload Files", "Upload translation file via SSH")
        ]
        print("\nAvailable Automation Steps:")
        print("=" * 60)
        for step_num, step_name, description in steps:
            print(f"  Step {step_num}: {step_name}")
            print(f"    {description}\n")
        sys.exit(0)
    
    # Configure logging
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    elif args.quiet:
        logging.getLogger().setLevel(logging.ERROR)
    
    # Setup log file if specified
    if args.log_file:
        file_handler = logging.FileHandler(args.log_file)
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
        logging.getLogger().addHandler(file_handler)
    
    automation = OnWatchAutomation(config_path=args.config)
    
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
        logger.info("  10. Configure Rancher")
        logger.info("  11. Upload files")
        logger.info("\n✓ Dry-run completed - no actual changes were made")
        sys.exit(0)
    
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


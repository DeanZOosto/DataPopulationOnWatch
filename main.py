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
from pathlib import Path
from client_api import ClientApi
from rancher_automation import RancherAutomation

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
        """Configure devices/cameras - API not yet available."""
        devices = self.config.get('devices', [])
        if not devices:
            logger.info("No devices to configure")
            return
        logger.warning(f"Devices configuration requires API endpoint - not yet implemented ({len(devices)} devices skipped)")
    
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
        
        # Try to create default group if none found
        if not group_map and not default_group_id:
            try:
                logger.info("No groups found, attempting to create default group...")
                group_response = self.client_api.create_group("Default Group")
                if isinstance(group_response, dict):
                    default_group_id = group_response.get('id')
                    logger.info(f"Created default group with ID: {default_group_id}")
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
                                
                                if additional_img_path and os.path.exists(additional_img_path):
                                    try:
                                        self.client_api.add_image_to_subject(subject_id, additional_img_path)
                                        logger.info(f"Added additional image to {name}: {additional_img_path}")
                                    except Exception as e:
                                        logger.warning(f"Could not add additional image {additional_img_path} to {name}: {e}")
                                else:
                                    logger.warning(f"Additional image file not found: {additional_img_path}")
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
            
            # Get existing groups to check for duplicates
            try:
                existing_groups = self.client_api.get_groups()
                existing_group_names = set()
                if isinstance(existing_groups, list):
                    existing_group_names = {g.get('title', '') for g in existing_groups if isinstance(g, dict)}
                elif isinstance(existing_groups, dict) and 'items' in existing_groups:
                    existing_group_names = {g.get('title', '') for g in existing_groups.get('items', []) if isinstance(g, dict)}
                
                logger.info(f"Found {len(existing_group_names)} existing groups")
            except Exception as e:
                logger.warning(f"Could not fetch existing groups: {e}")
                existing_group_names = set()
            
            # Create each subject group
            for group_config in subject_groups:
                try:
                    name = group_config.get('name')
                    if not name:
                        logger.warning(f"Subject group missing name: {group_config}")
                        continue
                    
                    # Skip if group already exists
                    if name in existing_group_names:
                        logger.info(f"Subject group '{name}' already exists, skipping")
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
        """Configure user accounts - API not yet available."""
        accounts = self.config.get('accounts', {})
        if not accounts:
            logger.info("No accounts to configure")
            return
        logger.warning("Accounts configuration requires API endpoint - not yet implemented")
    
    async def configure_inquiries(self):
        """Configure inquiries - API not yet available."""
        inquiries = self.config.get('inquiries', [])
        if not inquiries:
            logger.info("No inquiries to configure")
            return
        logger.warning(f"Inquiries configuration requires API endpoint - not yet implemented ({len(inquiries)} inquiries skipped)")
    
    async def configure_mass_import(self):
        """Upload mass import - API not yet available."""
        mass_import = self.config.get('mass_import', {})
        file_path = mass_import.get('file_path')
        if not file_path:
            logger.info("No mass import file specified")
            return
        logger.warning(f"Mass import upload requires API endpoint - not yet implemented (file: {file_path})")
    
    async def configure_rancher(self):
        """Configure Rancher environment variables."""
        env_vars = self.config.get('env_vars', {})
        if not env_vars:
            logger.info("No Rancher environment variables to set")
            return
        
        logger.info("Configuring Rancher environment variables...")
        rancher_config = self.config['rancher']
        async with RancherAutomation(
            base_url=rancher_config.get('base_url', f"https://{rancher_config['ip_address']}:{rancher_config['port']}"),
            username=rancher_config['username'],
            password=rancher_config['password'],
            headless=False
        ) as rancher:
            await rancher.set_environment_variables(env_vars)
    
    async def upload_files(self):
        """Upload files - API not yet available."""
        logger.warning("File uploads require API endpoint - not yet implemented")
    
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
            10: lambda: asyncio.run(automation.configure_rancher()),
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


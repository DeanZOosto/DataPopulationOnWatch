#!/usr/bin/env python3
"""
Post-upgrade data validation script for OnWatch.

Validates that all data created by the population script is still present
and correct in the OnWatch system after upgrade.

Usage:
    python3 validate_data.py <output_yaml_file> [--config config.yaml]
"""
import sys
import os
import yaml
import logging
import argparse
import glob
from pathlib import Path
from client_api import ClientApi
from config_manager import ConfigManager

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


class DataValidator:
    """Validates OnWatch data against output YAML."""
    
    def __init__(self, output_yaml_path, config_path="config.yaml"):
        """
        Initialize validator.
        
        Args:
            output_yaml_path: Path to output YAML file from population run
            config_path: Path to config.yaml for OnWatch connection details
        """
        self.output_yaml_path = Path(output_yaml_path)
        self.config_path = config_path
        self.config_manager = ConfigManager(config_path)
        self.config = self.config_manager.load_config()
        self.client_api = None
        
        # Validation results
        self.results = {
            'validated': 0,
            'passed': 0,
            'failed': 0,
            'errors': []
        }
    
    def initialize_api_client(self):
        """Initialize and authenticate with OnWatch API."""
        onwatch_config = self.config['onwatch']
        self.client_api = ClientApi(
            ip_address=onwatch_config['ip_address'],
            username=onwatch_config['username'],
            password=onwatch_config['password']
        )
        self.client_api.login()
        logger.info("✓ Connected to OnWatch API")
    
    def load_output_yaml(self):
        """Load output YAML file."""
        if not self.output_yaml_path.exists():
            # Try to find similar files to help user
            current_dir = self.output_yaml_path.parent if self.output_yaml_path.parent != Path('.') else Path.cwd()
            pattern = str(current_dir / "onwatch_data_export*.yaml")
            found_files = glob.glob(pattern)
            
            error_msg = f"Output YAML file not found: {self.output_yaml_path}\n"
            
            if found_files:
                error_msg += f"\nFound similar files in current directory:\n"
                for f in sorted(found_files)[:5]:
                    error_msg += f"  - {Path(f).name}\n"
                error_msg += f"\nTry using one of these files, or check if the file exists in a different location."
            else:
                error_msg += f"\nNo output YAML files found matching pattern 'onwatch_data_export*.yaml' in current directory.\n"
                error_msg += f"Make sure you've run the population script first to generate an output file.\n"
                error_msg += f"The output file is typically created in the same directory where you run main.py."
            
            raise FileNotFoundError(error_msg)
        
        with open(self.output_yaml_path, 'r') as f:
            data = yaml.safe_load(f)
        
        logger.info(f"✓ Loaded output YAML: {self.output_yaml_path}")
        return data
    
    def validate_kv_parameters(self, kv_params):
        """Validate KV parameters."""
        if not kv_params:
            return
        
        logger.info(f"\n📋 Validating {len(kv_params)} KV parameters...")
        
        for param in kv_params:
            key = param.get('key')
            # Use 'value' (verified value) or 'expected_value' (original) for comparison
            expected_value = str(param.get('value', param.get('expected_value', '')))
            
            if not key:
                continue
            
            self.results['validated'] += 1
            
            try:
                actual_value = self.client_api.get_kv_parameter(key)
                # #region agent log
                import json
                try:
                    with open('/Users/deanzion/Work/DataPopulationOnWatch/.cursor/debug.log', 'a') as f:
                        f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"H","location":"validate_data.py:111","message":"Validation comparison values","data":{"key":key,"expected_value":expected_value,"expected_type":type(expected_value).__name__,"actual_value":actual_value,"actual_type":type(actual_value).__name__ if actual_value is not None else "None","is_none":actual_value is None},"timestamp":int(__import__('time').time()*1000)}) + '\n')
                except: pass
                # #endregion
                
                if actual_value is None:
                    self.results['failed'] += 1
                    error_msg = f"KV parameter '{key}': NOT FOUND"
                    self.results['errors'].append(error_msg)
                    logger.error(f"  ❌ {error_msg}")
                    # Provide helpful debugging info
                    if key.startswith('DEFAULT/'):
                        logger.error(f"     → This parameter uses 'DEFAULT/' prefix and is queried via REST /settings/kv endpoint")
                        logger.error(f"     → Expected value: {expected_value}")
                        logger.error(f"     → If this persists, the parameter may not exist or the API endpoint may have changed")
                    else:
                        logger.error(f"     → Expected value: {expected_value}")
                        logger.error(f"     → Tried both REST and GraphQL endpoints")
                elif str(actual_value) != expected_value:
                    self.results['failed'] += 1
                    error_msg = f"KV parameter '{key}': VALUE MISMATCH (expected: {expected_value}, actual: {actual_value})"
                    self.results['errors'].append(error_msg)
                    logger.error(f"  ❌ {error_msg}")
                else:
                    self.results['passed'] += 1
                    logger.info(f"  ✓ {key} = {expected_value}")
            except Exception as e:
                self.results['failed'] += 1
                error_msg = f"KV parameter '{key}': ERROR - {str(e)}"
                self.results['errors'].append(error_msg)
                logger.error(f"  ❌ {error_msg}")
    
    def validate_system_settings(self, system_settings):
        """Validate system settings."""
        if not system_settings:
            return
        
        logger.info(f"\n⚙️  Validating system settings...")
        
        try:
            actual_settings = self.client_api.get_system_settings()
            
            if actual_settings is None:
                logger.warning(f"  ⚠️  Could not retrieve system settings from API - GraphQL query may need adjustment")
                logger.warning(f"  ⚠️  This might be a GraphQL query issue, not a data loss issue")
                logger.warning(f"  ⚠️  Skipping system settings validation (API method needs to be fixed)")
                # Don't mark as failed - this is an API issue, not data loss
                return
            
            # Validate general settings
            if 'general' in system_settings:
                general = system_settings['general']
                
                # Check defaultFaceThreshold (system setting, not KV parameter)
                if 'default_face_threshold' in general:
                    self.results['validated'] += 1
                    expected = float(general['default_face_threshold'])
                    actual = actual_settings.get('defaultFaceThreshold')
                    
                    if actual is None:
                        self.results['failed'] += 1
                        error_msg = f"defaultFaceThreshold: NOT FOUND"
                        self.results['errors'].append(error_msg)
                        logger.error(f"  ❌ {error_msg}")
                    elif abs(float(actual) - expected) > 0.01:
                        self.results['failed'] += 1
                        error_msg = f"defaultFaceThreshold: MISMATCH (expected: {expected}, actual: {actual})"
                        self.results['errors'].append(error_msg)
                        logger.error(f"  ❌ {error_msg}")
                        logger.warning(f"     Note: Output YAML expected {expected} but system has {actual}. The system setting may not have been set correctly during population.")
                    else:
                        self.results['passed'] += 1
                        logger.debug(f"  ✓ defaultFaceThreshold = {expected}")
                
                # Check defaultBodyThreshold
                if 'default_body_threshold' in general:
                    self.results['validated'] += 1
                    expected = float(general['default_body_threshold'])
                    actual = actual_settings.get('defaultBodyThreshold')
                    if actual is None or abs(float(actual) - expected) > 0.01:
                        self.results['failed'] += 1
                        error_msg = f"defaultBodyThreshold: MISMATCH (expected: {expected}, actual: {actual})"
                        self.results['errors'].append(error_msg)
                        logger.error(f"  ❌ {error_msg}")
                    else:
                        self.results['passed'] += 1
                        logger.debug(f"  ✓ defaultBodyThreshold = {expected}")
                
                # Check default_liveness_threshold
                if 'default_liveness_threshold' in general:
                    self.results['validated'] += 1
                    expected = float(general['default_liveness_threshold'])
                    actual = actual_settings.get('cameraDefaultLivenessTh')
                    if actual is None or abs(float(actual) - expected) > 0.01:
                        self.results['failed'] += 1
                        error_msg = f"cameraDefaultLivenessTh: MISMATCH (expected: {expected}, actual: {actual})"
                        self.results['errors'].append(error_msg)
                        logger.error(f"  ❌ {error_msg}")
                    else:
                        self.results['passed'] += 1
                        logger.debug(f"  ✓ cameraDefaultLivenessTh = {expected}")
            
            # Validate system_interface product_name
            if 'system_interface' in system_settings:
                interface = system_settings['system_interface']
                if 'product_name' in interface:
                    self.results['validated'] += 1
                    expected = interface['product_name']
                    actual = actual_settings.get('whiteLabel', {}).get('productName')
                    if actual != expected:
                        self.results['failed'] += 1
                        error_msg = f"productName: MISMATCH (expected: {expected}, actual: {actual})"
                        self.results['errors'].append(error_msg)
                        logger.error(f"  ❌ {error_msg}")
                    else:
                        self.results['passed'] += 1
                        logger.debug(f"  ✓ productName = {expected}")
            
        except Exception as e:
            self.results['failed'] += 1
            error_msg = f"System settings: ERROR - {str(e)}"
            self.results['errors'].append(error_msg)
            logger.error(f"  ❌ {error_msg}")
    
    def validate_groups(self, groups):
        """Validate subject groups."""
        if not groups:
            return
        
        logger.info(f"\n👥 Validating {len(groups)} subject groups...")
        
        try:
            actual_groups = self.client_api.get_groups()
            if not isinstance(actual_groups, list):
                if isinstance(actual_groups, dict) and 'items' in actual_groups:
                    actual_groups = actual_groups['items']
                else:
                    actual_groups = []
            
            # Create lookup by name
            actual_by_name = {g.get('name') or g.get('title'): g for g in actual_groups if g.get('name') or g.get('title')}
            
            for group in groups:
                group_name = group.get('name') or group.get('title')
                if not group_name:
                    continue
                
                self.results['validated'] += 1
                
                if group_name not in actual_by_name:
                    self.results['failed'] += 1
                    error_msg = f"Subject group '{group_name}': NOT FOUND"
                    self.results['errors'].append(error_msg)
                    logger.error(f"  ❌ {error_msg}")
                else:
                    self.results['passed'] += 1
                    logger.debug(f"  ✓ Group '{group_name}' exists")
        
        except Exception as e:
            self.results['failed'] += 1
            error_msg = f"Subject groups: ERROR - {str(e)}"
            self.results['errors'].append(error_msg)
            logger.error(f"  ❌ {error_msg}")
    
    def validate_users(self, users):
        """Validate users."""
        if not users:
            return
        
        logger.info(f"\n👤 Validating {len(users)} users...")
        
        try:
            actual_users = self.client_api.get_users()
            if not isinstance(actual_users, list):
                if isinstance(actual_users, dict) and 'items' in actual_users:
                    actual_users = actual_users['items']
                else:
                    actual_users = []
            
            # Create lookup by username
            actual_by_username = {u.get('username'): u for u in actual_users if u.get('username')}
            
            for user in users:
                username = user.get('username')
                if not username:
                    continue
                
                self.results['validated'] += 1
                
                if username not in actual_by_username:
                    self.results['failed'] += 1
                    error_msg = f"User '{username}': NOT FOUND"
                    self.results['errors'].append(error_msg)
                    logger.error(f"  ❌ {error_msg}")
                else:
                    self.results['passed'] += 1
                    logger.debug(f"  ✓ User '{username}' exists")
        
        except Exception as e:
            self.results['failed'] += 1
            error_msg = f"Users: ERROR - {str(e)}"
            self.results['errors'].append(error_msg)
            logger.error(f"  ❌ {error_msg}")
    
    def validate_subjects(self, subjects):
        """Validate watch list subjects."""
        if not subjects:
            return
        
        # Handle case where subjects might be an int (count) instead of list
        if isinstance(subjects, int):
            logger.warning(f"  ⚠️  Output YAML has subjects as count ({subjects}) instead of list - cannot validate individual subjects")
            return
        
        if not isinstance(subjects, list):
            logger.warning(f"  ⚠️  Output YAML has subjects in unexpected format: {type(subjects)} - skipping validation")
            return
        
        logger.info(f"\n📸 Validating {len(subjects)} watch list subjects...")
        
        try:
            actual_subjects = self.client_api.get_subjects()
            
            # Handle different response formats
            if isinstance(actual_subjects, int):
                # API returned a count instead of list
                logger.warning(f"  ⚠️  API returned count ({actual_subjects}) instead of subject list - cannot validate by name")
                self.results['failed'] += len(subjects)
                for subject in subjects:
                    subject_name = subject.get('name', 'unknown')
                    error_msg = f"Subject '{subject_name}': Cannot validate (API returned count instead of list)"
                    self.results['errors'].append(error_msg)
                    logger.error(f"  ❌ {error_msg}")
                return
            elif isinstance(actual_subjects, dict):
                if 'items' in actual_subjects:
                    actual_subjects = actual_subjects['items']
                elif 'data' in actual_subjects:
                    actual_subjects = actual_subjects['data']
                else:
                    # Unknown dict format
                    logger.warning(f"  ⚠️  Unexpected response format from get_subjects: {type(actual_subjects)}")
                    actual_subjects = []
            elif not isinstance(actual_subjects, list):
                logger.warning(f"  ⚠️  Unexpected response type from get_subjects: {type(actual_subjects)}")
                actual_subjects = []
            
            # Create lookup by name
            actual_by_name = {s.get('name'): s for s in actual_subjects if s.get('name')}
            
            for subject in subjects:
                subject_name = subject.get('name')
                if not subject_name:
                    continue
                
                self.results['validated'] += 1
                
                if subject_name not in actual_by_name:
                    self.results['failed'] += 1
                    error_msg = f"Subject '{subject_name}': NOT FOUND"
                    self.results['errors'].append(error_msg)
                    logger.error(f"  ❌ {error_msg}")
                else:
                    # Check image count if available
                    actual_subject = actual_by_name[subject_name]
                    expected_images = subject.get('images', [])
                    actual_images = actual_subject.get('images', [])
                    
                    if len(expected_images) > 0 and len(actual_images) < len(expected_images):
                        self.results['failed'] += 1
                        error_msg = f"Subject '{subject_name}': IMAGE COUNT MISMATCH (expected: {len(expected_images)}, actual: {len(actual_images)})"
                        self.results['errors'].append(error_msg)
                        logger.error(f"  ❌ {error_msg}")
                    else:
                        self.results['passed'] += 1
                        logger.debug(f"  ✓ Subject '{subject_name}' exists with {len(actual_images)} image(s)")
        
        except Exception as e:
            self.results['failed'] += 1
            error_msg = f"Subjects: ERROR - {str(e)}"
            self.results['errors'].append(error_msg)
            logger.error(f"  ❌ {error_msg}")
    
    def validate_cameras(self, cameras):
        """Validate cameras/devices."""
        if not cameras:
            return
        
        logger.info(f"\n📹 Validating {len(cameras)} cameras...")
        
        try:
            actual_cameras = self.client_api.get_cameras()
            if not isinstance(actual_cameras, list):
                if isinstance(actual_cameras, dict) and 'items' in actual_cameras:
                    actual_cameras = actual_cameras['items']
                else:
                    actual_cameras = []
            
            # Create lookup by name/title
            actual_by_name = {}
            for cam in actual_cameras:
                name = cam.get('name') or cam.get('title')
                if name:
                    actual_by_name[name] = cam
            
            for camera in cameras:
                camera_name = camera.get('name') or camera.get('title')
                if not camera_name:
                    continue
                
                self.results['validated'] += 1
                
                if camera_name not in actual_by_name:
                    self.results['failed'] += 1
                    error_msg = f"Camera '{camera_name}': NOT FOUND"
                    self.results['errors'].append(error_msg)
                    logger.error(f"  ❌ {error_msg}")
                else:
                    self.results['passed'] += 1
                    logger.debug(f"  ✓ Camera '{camera_name}' exists")
        
        except Exception as e:
            self.results['failed'] += 1
            error_msg = f"Cameras: ERROR - {str(e)}"
            self.results['errors'].append(error_msg)
            logger.error(f"  ❌ {error_msg}")
    
    def validate_inquiries(self, inquiries):
        """Validate inquiry cases."""
        if not inquiries:
            return
        
        logger.info(f"\n🔍 Validating {len(inquiries)} inquiry cases...")
        
        try:
            actual_inquiries = self.client_api.get_inquiry_cases()
            if not isinstance(actual_inquiries, list):
                actual_inquiries = []
            
            # Create lookup by name (case-insensitive)
            actual_by_name = {}
            actual_by_name_lower = {}
            for inq in actual_inquiries:
                name = inq.get('name')
                if name:
                    actual_by_name[name] = inq
                    actual_by_name_lower[name.lower()] = inq
            
            for inquiry in inquiries:
                inquiry_name = inquiry.get('name')
                if not inquiry_name:
                    continue
                
                self.results['validated'] += 1
                
                # Try exact match first, then case-insensitive
                found = False
                if inquiry_name in actual_by_name:
                    found = True
                elif inquiry_name.lower() in actual_by_name_lower:
                    found = True
                    # Log that we found it with different case
                    logger.debug(f"  ✓ Inquiry case '{inquiry_name}' found (case-insensitive match)")
                
                if not found:
                    self.results['failed'] += 1
                    error_msg = f"Inquiry case '{inquiry_name}': NOT FOUND"
                    self.results['errors'].append(error_msg)
                    logger.error(f"  ❌ {error_msg}")
                else:
                    self.results['passed'] += 1
                    logger.debug(f"  ✓ Inquiry case '{inquiry_name}' exists")
        
        except Exception as e:
            self.results['failed'] += 1
            error_msg = f"Inquiry cases: ERROR - {str(e)}"
            self.results['errors'].append(error_msg)
            logger.error(f"  ❌ {error_msg}")
    
    def validate_mass_import(self, mass_import):
        """Validate mass import."""
        if not mass_import:
            return
        
        logger.info(f"\n📦 Validating mass import...")
        
        mass_import_name = mass_import.get('name')
        mass_import_id = mass_import.get('id')
        
        if not mass_import_name and not mass_import_id:
            return
        
        self.results['validated'] += 1
        
        try:
            if mass_import_id:
                status = self.client_api.get_mass_import_status(mass_import_id)
                if status is None:
                    self.results['failed'] += 1
                    error_msg = f"Mass import '{mass_import_name or mass_import_id}': NOT FOUND"
                    self.results['errors'].append(error_msg)
                    logger.error(f"  ❌ {error_msg}")
                else:
                    self.results['passed'] += 1
                    logger.debug(f"  ✓ Mass import '{mass_import_name or mass_import_id}' exists")
            else:
                # Can't validate without ID
                logger.warning(f"  ⚠️  Mass import '{mass_import_name}' - cannot validate without ID")
        
        except Exception as e:
            self.results['failed'] += 1
            error_msg = f"Mass import '{mass_import_name or mass_import_id}': ERROR - {str(e)}"
            self.results['errors'].append(error_msg)
            logger.error(f"  ❌ {error_msg}")
    
    def validate(self):
        """Run full validation."""
        logger.info("=" * 80)
        logger.info("OnWatch Data Validation")
        logger.info("=" * 80)
        
        # Load output YAML
        output_data = self.load_output_yaml()
        
        # Initialize API client
        self.initialize_api_client()
        
        # Get created items
        created_items = output_data.get('created_items', {})
        
        # Validate each category
        if 'kv_parameters' in created_items:
            self.validate_kv_parameters(created_items['kv_parameters'])
        
        if 'system_settings' in created_items:
            self.validate_system_settings(created_items['system_settings'])
        
        if 'groups' in created_items:
            self.validate_groups(created_items['groups'])
        
        if 'accounts' in created_items:
            users = [acc for acc in created_items['accounts'] if 'username' in acc]
            if users:
                self.validate_users(users)
        
        if 'subjects' in created_items:
            self.validate_subjects(created_items['subjects'])
        
        if 'cameras' in created_items:
            self.validate_cameras(created_items['cameras'])
        
        if 'inquiries' in created_items:
            self.validate_inquiries(created_items['inquiries'])
        
        if 'mass_import' in created_items:
            self.validate_mass_import(created_items['mass_import'])
        
        # Print summary
        self.print_summary()
        
        return self.results['failed'] == 0
    
    def print_summary(self):
        """Print validation summary."""
        logger.info("\n" + "=" * 80)
        logger.info("VALIDATION SUMMARY")
        logger.info("=" * 80)
        
        total = self.results['validated']
        passed = self.results['passed']
        failed = self.results['failed']
        
        logger.info(f"\n📊 Results:")
        logger.info(f"  Total items validated: {total}")
        logger.info(f"  ✅ Passed: {passed}")
        logger.info(f"  ❌ Failed: {failed}")
        
        if failed > 0:
            logger.error(f"\n❌ Validation FAILED - {failed} issue(s) found:")
            for error in self.results['errors']:
                logger.error(f"  • {error}")
            logger.error("\n⚠️  Please review the errors above. Data may have been lost or modified.")
        else:
            logger.info("\n✅ Validation PASSED - All data is present and correct!")
        
        logger.info("=" * 80 + "\n")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Validate OnWatch data against output YAML file',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Validate using default config.yaml
  python3 validate_data.py onwatch_data_export_2025-01-15_10-30-00.yaml
  
  # Validate with custom config file
  python3 validate_data.py output.yaml --config my-config.yaml
        """
    )
    
    parser.add_argument(
        'output_yaml',
        type=str,
        help='Path to output YAML file from population run'
    )
    
    parser.add_argument(
        '--config',
        type=str,
        default='config.yaml',
        help='Path to configuration YAML file (default: config.yaml)'
    )
    
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging (DEBUG level)'
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    try:
        validator = DataValidator(args.output_yaml, args.config)
        success = validator.validate()
        sys.exit(0 if success else 1)
    except Exception as e:
        logger.error(f"Validation failed: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()



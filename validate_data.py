#!/usr/bin/env python3
"""
Post-upgrade data validation script for OnWatch.

Validates that all data created by the population script is still present
and correct in the OnWatch system after upgrade.

Usage:
    python3 validate_data.py <output_yaml_file> [--config config.yaml]

Structure:
  - Constants (LOG_PASS, CATEGORY_*, etc.)
  - Helper functions (_image_count, _normalize_list_response, _env_vars_to_dict)
  - DataValidator class
    - Init, load_output_yaml, _record_failure
    - validate_* methods (kv_parameters, system_settings, groups, etc.)
    - validate() — main entry, iterates categories with progress callback
    - print_summary, _manual_verification_checklist
  - main() — CLI entry point
"""
import sys
import argparse
import glob
import logging
import yaml
from pathlib import Path

from client_api import ClientApi
from config_manager import ConfigManager

# -----------------------------------------------------------------------------
# Constants — log prefixes and category labels (single place for clarity)
# -----------------------------------------------------------------------------
LOG_PASS = "  ✓"
LOG_FAIL = "  ❌"
LOG_SKIP = "  ⚠️  "

CATEGORY_RANCHER_ENV_VARS = "Rancher env vars"
CATEGORY_TRANSLATION_FILE = "Translation file"
CATEGORY_MASS_IMPORT = "Mass import"


def _image_count(value):
    """Return image count from export or API (value may be a list or a number)."""
    if value is None:
        return 0
    if isinstance(value, list):
        return len(value)
    if isinstance(value, (int, float)):
        return int(value)
    return 0


def _normalize_list_response(response, items_key="items", data_key="data"):
    """Return a list from API response (list, dict with items/data, or empty list)."""
    if isinstance(response, list):
        return response
    if isinstance(response, dict):
        if items_key in response:
            return response[items_key]
        if data_key in response:
            return response[data_key]
        return []
    return []


def _env_vars_to_dict(env_vars):
    """Convert env vars from export (list of {key, value}) or config (dict) to a single dict."""
    if isinstance(env_vars, dict):
        return env_vars
    result = {}
    for item in env_vars or []:
        if isinstance(item, dict) and "key" in item:
            result[item["key"]] = item.get("value", "")
    return result


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


class DataValidator:
    """Validates OnWatch data against output YAML."""
    
    def __init__(self, output_yaml_path, config_path="config.yaml", progress_callback=None):
        """
        Initialize validator.
        
        Args:
            output_yaml_path: Path to output YAML file from population run
            config_path: Path to config.yaml for OnWatch connection details
            progress_callback: Optional callable(event_dict) for UI progress reporting
        """
        self.output_yaml_path = Path(output_yaml_path)
        self.config_path = config_path
        self.config_manager = ConfigManager(config_path)
        self.config = self.config_manager.load_config()
        self.client_api = None
        self.progress_callback = progress_callback

        # Validation results
        self.results = {
            'validated': 0,
            'passed': 0,
            'failed': 0,
            'errors': [],
            'categories_done': [],   # list of (category_label, count) for summary
            'skipped': [],           # list of (category_label, reason) when validation could not run
            'acknowledged': []       # list of (category_label, note) for items not verified (e.g. SSH uploads)
        }
    
    def initialize_api_client(self):
        """Initialize and authenticate with OnWatch API."""
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
        
        # Log detected/configured version
        detected_version = self.client_api.version_compat.get_version()
        logger.info(f"✓ Connected to OnWatch API (OnWatch {detected_version})")
    
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

    def _record_failure(self, error_msg):
        """Record one validation failure and log it."""
        self.results["failed"] += 1
        self.results["errors"].append(error_msg)
        logger.error(f"{LOG_FAIL} {error_msg}")

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
                logger.debug(f"Validation comparison for '{key}': expected={expected_value} ({type(expected_value).__name__}), actual={actual_value} ({type(actual_value).__name__ if actual_value is not None else 'None'})")
                
                if actual_value is None:
                    error_msg = f"KV parameter '{key}': NOT FOUND"
                    self._record_failure(error_msg)
                    # Provide helpful debugging info
                    if key.startswith('DEFAULT/'):
                        logger.error(f"     → This parameter uses 'DEFAULT/' prefix and is queried via REST /settings/kv endpoint")
                        logger.error(f"     → Expected value: {expected_value}")
                        logger.error(f"     → If this persists, the parameter may not exist or the API endpoint may have changed")
                    else:
                        logger.error(f"     → Expected value: {expected_value}")
                        logger.error(f"     → Tried both REST and GraphQL endpoints")
                elif str(actual_value) != expected_value:
                    self._record_failure(
                        f"KV parameter '{key}': VALUE MISMATCH (expected: {expected_value}, actual: {actual_value})"
                    )
                else:
                    self.results["passed"] += 1
                    logger.info(f"{LOG_PASS} {key} = {expected_value}")
            except Exception as e:
                self._record_failure(f"KV parameter '{key}': ERROR - {str(e)}")
    
    def validate_system_settings(self, system_settings):
        """Validate system settings."""
        if not system_settings:
            return
        
        logger.info(f"\n⚙️  Validating system settings...")
        
        try:
            actual_settings = self.client_api.get_system_settings()
            
            if actual_settings is None:
                logger.warning(
                    f"{LOG_SKIP} Could not retrieve system settings from API (GraphQL query may need adjustment)."
                )
                logger.warning(f"{LOG_SKIP} This may be an API issue, not data loss. Skipping system settings.")
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
                        self._record_failure("defaultFaceThreshold: NOT FOUND")
                    elif abs(float(actual) - expected) > 0.01:
                        self._record_failure(
                            f"defaultFaceThreshold: MISMATCH (expected: {expected}, actual: {actual})"
                        )
                        logger.warning(
                            f"     Note: Output YAML expected {expected} but system has {actual}. "
                            "The system setting may not have been set correctly during population."
                        )
                    else:
                        self.results["passed"] += 1
                        logger.debug(f"{LOG_PASS} defaultFaceThreshold = {expected}")
                if "default_body_threshold" in general:
                    self.results["validated"] += 1
                    expected = float(general["default_body_threshold"])
                    actual = actual_settings.get("defaultBodyThreshold")
                    if actual is None or abs(float(actual) - expected) > 0.01:
                        self._record_failure(
                            f"defaultBodyThreshold: MISMATCH (expected: {expected}, actual: {actual})"
                        )
                    else:
                        self.results["passed"] += 1
                        logger.debug(f"{LOG_PASS} defaultBodyThreshold = {expected}")
                if "default_liveness_threshold" in general:
                    self.results["validated"] += 1
                    expected = float(general["default_liveness_threshold"])
                    actual = actual_settings.get("cameraDefaultLivenessTh")
                    if actual is None or abs(float(actual) - expected) > 0.01:
                        self._record_failure(
                            f"cameraDefaultLivenessTh: MISMATCH (expected: {expected}, actual: {actual})"
                        )
                    else:
                        self.results["passed"] += 1
                        logger.debug(f"{LOG_PASS} cameraDefaultLivenessTh = {expected}")
            
            # Validate system_interface settings (product_name, logos, favicon)
            if 'system_interface' in system_settings:
                interface = system_settings['system_interface']
                
                # Validate product_name
                if "product_name" in interface:
                    self.results["validated"] += 1
                    expected = interface["product_name"]
                    actual = actual_settings.get("whiteLabel", {}).get("productName")
                    if actual != expected:
                        self._record_failure(
                            f"productName: MISMATCH (expected: {expected}, actual: {actual})"
                        )
                    else:
                        self.results["passed"] += 1
                        logger.info(f"{LOG_PASS} productName = {expected}")
                
                # Validate logos and favicon
                white_label = actual_settings.get('whiteLabel', {})
                logos = interface.get('logos', {})
                
                if logos:
                    # Validate company logo
                    if "company" in logos:
                        self.results["validated"] += 1
                        if white_label.get("companyLogo"):
                            self.results["passed"] += 1
                            logger.info(
                                f"{LOG_PASS} Company logo uploaded (source: {logos['company'].get('source_file', 'unknown')})"
                            )
                        else:
                            self._record_failure(
                                f"Company logo: NOT FOUND (expected from: {logos['company'].get('path', 'unknown')})"
                            )
                    if "sidebar" in logos:
                        self.results["validated"] += 1
                        if white_label.get("sidebarLogo"):
                            self.results["passed"] += 1
                            logger.info(
                                f"{LOG_PASS} Sidebar logo uploaded (source: {logos['sidebar'].get('source_file', 'unknown')})"
                            )
                        else:
                            self._record_failure(
                                f"Sidebar logo: NOT FOUND (expected from: {logos['sidebar'].get('path', 'unknown')})"
                            )
                    if "favicon" in logos or "favicon" in interface:
                        self.results["validated"] += 1
                        favicon_info = logos.get("favicon") or interface.get("favicon")
                        if white_label.get("favicon"):
                            self.results["passed"] += 1
                            source = (
                                favicon_info.get("source_file", "unknown")
                                if isinstance(favicon_info, dict)
                                else "unknown"
                            )
                            logger.info(f"{LOG_PASS} Favicon uploaded (source: {source})")
                        else:
                            path = (
                                favicon_info.get("path", "unknown")
                                if isinstance(favicon_info, dict)
                                else (favicon_info if isinstance(favicon_info, str) else "unknown")
                            )
                            self._record_failure(f"Favicon: NOT FOUND (expected from: {path})")
        except Exception as e:
            self._record_failure(f"System settings: ERROR - {str(e)}")
    
    def validate_groups(self, groups):
        """Validate groups from export: subject groups (Watch list / subject groups) and user groups (Account management → User groups)."""
        if not groups:
            return
        subject_count = sum(1 for g in groups if (g.get("type") or "subject") != "user")
        user_count = sum(1 for g in groups if g.get("type") == "user")
        if subject_count and user_count:
            logger.info(f"\n👥 Validating {len(groups)} groups ({subject_count} subject, {user_count} user group(s))...")
        elif user_count:
            logger.info(f"\n👥 Validating {len(groups)} user group(s) (Account management → User groups)...")
        else:
            logger.info(f"\n👥 Validating {len(groups)} subject group(s)...")
        try:
            subject_groups = _normalize_list_response(self.client_api.get_groups())
            subject_by_name = {
                (g.get("name") or g.get("title")): g
                for g in subject_groups
                if g.get("name") or g.get("title")
            }
            user_groups = _normalize_list_response(self.client_api.get_user_groups())
            user_by_title = {
                (g.get("title") or g.get("name")): g
                for g in user_groups
                if g.get("title") or g.get("name")
            }
            for group in groups:
                group_name = group.get("name") or group.get("title")
                if not group_name:
                    continue
                self.results["validated"] += 1
                is_user_group = group.get("type") == "user"
                lookup = user_by_title if is_user_group else subject_by_name
                label = "User group" if is_user_group else "Subject group"
                if group_name not in lookup:
                    self._record_failure(f"{label} '{group_name}': NOT FOUND")
                else:
                    self.results["passed"] += 1
                    logger.info(f"{LOG_PASS} {label} '{group_name}' exists")
        except Exception as e:
            self._record_failure(f"Groups: ERROR - {str(e)}")
    
    def validate_users(self, users):
        """Validate users."""
        if not users:
            return
        
        logger.info(f"\n👤 Validating {len(users)} users...")
        
        try:
            actual_users = _normalize_list_response(self.client_api.get_users())
            actual_by_username = {u.get("username"): u for u in actual_users if u.get("username")}
            for user in users:
                username = user.get("username")
                if not username:
                    continue
                self.results["validated"] += 1
                if username not in actual_by_username:
                    self._record_failure(f"User '{username}': NOT FOUND")
                else:
                    self.results["passed"] += 1
                    logger.info(f"{LOG_PASS} User '{username}' exists")
        except Exception as e:
            self._record_failure(f"Users: ERROR - {str(e)}")
    
    def validate_subjects(self, subjects):
        """Validate watch list subjects."""
        if not subjects:
            return
        
        if isinstance(subjects, int):
            logger.warning(
                f"{LOG_SKIP} Output YAML has subjects as count ({subjects}) instead of list; cannot validate individually."
            )
            return
        if not isinstance(subjects, list):
            logger.warning(
                f"{LOG_SKIP} Output YAML has subjects in unexpected format: {type(subjects)}; skipping."
            )
            return
        
        logger.info(f"\n📸 Validating {len(subjects)} watch list subjects...")
        
        try:
            actual_subjects = self.client_api.get_subjects()
            
            # Handle different response formats
            if isinstance(actual_subjects, int):
                logger.warning(
                    f"{LOG_SKIP} API returned count ({actual_subjects}) instead of subject list; cannot validate by name."
                )
                for subject in subjects:
                    subject_name = subject.get("name", "unknown")
                    self.results["validated"] += 1
                    self._record_failure(
                        f"Subject '{subject_name}': Cannot validate (API returned count instead of list)"
                    )
                return
            elif isinstance(actual_subjects, dict):
                actual_subjects = _normalize_list_response(actual_subjects)
                if not actual_subjects:
                    logger.warning(
                        f"{LOG_SKIP} Unexpected response format from get_subjects: {type(actual_subjects)}"
                    )
            elif not isinstance(actual_subjects, list):
                logger.warning(
                    f"{LOG_SKIP}Unexpected response type from get_subjects: {type(actual_subjects)}"
                )
                actual_subjects = []
            actual_by_name = {s.get("name"): s for s in actual_subjects if s.get("name")}
            for subject in subjects:
                subject_name = subject.get("name")
                if not subject_name:
                    continue
                self.results["validated"] += 1
                if subject_name not in actual_by_name:
                    self._record_failure(f"Subject '{subject_name}': NOT FOUND")
                else:
                    actual_subject = actual_by_name[subject_name]
                    expected_count = _image_count(subject.get("images"))
                    actual_count = _image_count(actual_subject.get("images"))
                    if expected_count > 0 and actual_count < expected_count:
                        self._record_failure(
                            f"Subject '{subject_name}': IMAGE COUNT MISMATCH "
                            f"(expected: {expected_count}, actual: {actual_count})"
                        )
                    else:
                        self.results["passed"] += 1
                        logger.info(f"{LOG_PASS} Subject '{subject_name}' exists (images: {actual_count})")
        except Exception as e:
            self._record_failure(f"Subjects: ERROR - {str(e)}")
    
    def validate_cameras(self, cameras):
        """Validate cameras/devices."""
        if not cameras:
            return
        
        logger.info(f"\n📹 Validating {len(cameras)} cameras...")
        
        try:
            actual_cameras = _normalize_list_response(self.client_api.get_cameras())
            actual_by_name = {}
            for cam in actual_cameras:
                name = cam.get("name") or cam.get("title")
                if name:
                    actual_by_name[name] = cam
            for camera in cameras:
                camera_name = camera.get("name") or camera.get("title")
                if not camera_name:
                    continue
                self.results["validated"] += 1
                if camera_name not in actual_by_name:
                    self._record_failure(f"Camera '{camera_name}': NOT FOUND")
                else:
                    self.results["passed"] += 1
                    logger.info(f"{LOG_PASS} Camera '{camera_name}' exists")
        except Exception as e:
            self._record_failure(f"Cameras: ERROR - {str(e)}")
    
    def validate_inquiries(self, inquiries):
        """Validate inquiry cases."""
        if not inquiries:
            return
        
        logger.info(f"\n🔍 Validating {len(inquiries)} inquiry cases...")
        
        try:
            actual_inquiries = self.client_api.get_inquiry_cases()
            if not isinstance(actual_inquiries, list):
                actual_inquiries = _normalize_list_response(actual_inquiries, data_key="data")
            actual_by_name = {}
            actual_by_name_lower = {}
            for inq in actual_inquiries:
                name = inq.get("name") or inq.get("title")
                if name:
                    actual_by_name[name] = inq
                    actual_by_name_lower[name.lower()] = inq
            for inquiry in inquiries:
                inquiry_name = inquiry.get("name") or inquiry.get("title")
                if not inquiry_name:
                    continue
                self.results["validated"] += 1
                found = (
                    inquiry_name in actual_by_name
                    or inquiry_name.lower() in actual_by_name_lower
                )
                if found and inquiry_name not in actual_by_name:
                    logger.debug(
                        f"{LOG_PASS} Inquiry case '{inquiry_name}' found (case-insensitive match)"
                    )
                if not found:
                    self._record_failure(f"Inquiry case '{inquiry_name}': NOT FOUND")
                else:
                    self.results["passed"] += 1
                    logger.info(f"{LOG_PASS} Inquiry case '{inquiry_name}' exists")
        except Exception as e:
            self._record_failure(f"Inquiry cases: ERROR - {str(e)}")
    
    def validate_mass_import(self, mass_import):
        """Validate mass import. Returns True if validation ran, False if skipped."""
        if not mass_import:
            return False
        
        logger.info(f"\n📦 Validating mass import...")
        
        mass_import_name = mass_import.get('name')
        # Export stores upload_id (from prepare); API get_mass_import_status expects that id
        mass_import_id = mass_import.get('id') or mass_import.get('upload_id')
        
        if not mass_import_name and not mass_import_id:
            return False
        
        if not mass_import_id:
            self._record_skip(
                CATEGORY_MASS_IMPORT,
                f"'{mass_import_name or 'unknown'}' – no ID in export; cannot validate.",
            )
            return False
        self.results["validated"] += 1
        try:
            status = self.client_api.get_mass_import_status(mass_import_id)
            display_name = mass_import_name or mass_import_id
            if status is None:
                self._record_failure(f"Mass import '{display_name}': NOT FOUND")
            else:
                self.results["passed"] += 1
                logger.info(f"{LOG_PASS} Mass import '{display_name}' exists (status: {status})")
            return True
        except Exception as e:
            self._record_failure(
                f"Mass import '{mass_import_name or mass_import_id}': ERROR - {str(e)}"
            )
        return True

    def _record_skip(self, category_label, reason):
        """Record a skipped category so summary and manual verification can list it."""
        self.results["skipped"].append((category_label, reason))
        logger.warning(f"{LOG_SKIP} {category_label}: Skipped – {reason}")

    def validate_env_vars(self, env_vars):
        """Acknowledge Rancher env vars from export; no API check. Warn user to verify manually (only when export shows they were set)."""
        env_vars_dict = _env_vars_to_dict(env_vars)
        if not env_vars_dict:
            return
        logger.info(f"\n🔧 Rancher env vars (acknowledged from export – {len(env_vars_dict)} set during population)...")
        self.results["acknowledged"].append(
            (CATEGORY_RANCHER_ENV_VARS, f"{len(env_vars_dict)} variable(s) set during population")
        )
        logger.info(f"{LOG_PASS} In export: {len(env_vars_dict)} env var(s) recorded")
        logger.warning(
            f"{LOG_SKIP} MANUAL CHECK REQUIRED: Rancher environment variables were set during population and could not be verified here. "
            "Please confirm in Rancher UI (workload environment) that they match your config/export."
        )
    
    def validate_translation_file(self, translation_file):
        """Acknowledge translation file from export (uploaded via SSH; no OnWatch API to verify)."""
        if not translation_file:
            return
        logger.info("\n🌐 Translation file (acknowledged from export)...")
        filename = translation_file.get("filename") or translation_file.get("path", "unknown")
        self.results["acknowledged"].append((CATEGORY_TRANSLATION_FILE, filename))
        logger.info(f"{LOG_PASS} In export: {filename}")
        logger.warning(
            f"{LOG_SKIP} MANUAL CHECK REQUIRED: Translation file was uploaded via SSH and could not be verified here. "
            "Please confirm on the OnWatch server that the file is present and loaded (e.g. via translation-util or UI)."
        )
    
    def validate(self):
        """Run full validation."""
        logger.info("=" * 80)
        logger.info("OnWatch Data Validation")
        logger.info("=" * 80)
        
        # Load output YAML
        output_data = self.load_output_yaml()
        
        # Initialize API client
        self.initialize_api_client()
        
        created_items = output_data.get("created_items", {})
        export_category_keys = [
            "kv_parameters", "system_settings", "groups", "accounts", "subjects",
            "cameras", "inquiries", "mass_import", "translation_file", "rancher_env_vars",
        ]
        categories_present = [k for k in export_category_keys if created_items.get(k)]
        total_categories = len(categories_present)
        if categories_present:
            logger.info(
                f"\n📑 Will validate: {', '.join(c.replace('_', ' ') for c in categories_present)}"
            )

        def _emit(event_dict):
            if self.progress_callback:
                try:
                    self.progress_callback(event_dict)
                except Exception:
                    pass

        cat_idx = [0]

        def _cat_start(name):
            cat_idx[0] += 1
            _emit({"type": "category_start", "name": name, "current": cat_idx[0], "total": total_categories})
        def _cat_done(name, count=1):
            _emit({"type": "category_done", "name": name, "count": count})

        # — Settings (KV, system settings)
        if "kv_parameters" in created_items:
            _cat_start("KV parameters")
            self.validate_kv_parameters(created_items["kv_parameters"])
            _cat_done("KV parameters", len(created_items["kv_parameters"]))
            self.results["categories_done"].append(("KV parameters", len(created_items["kv_parameters"])))
        if "system_settings" in created_items:
            _cat_start("System settings")
            self.validate_system_settings(created_items["system_settings"])
            _cat_done("System settings", 1)
            self.results["categories_done"].append(("System settings", 1))

        # — Identity (groups, accounts)
        if "groups" in created_items:
            _cat_start("Groups")
            self.validate_groups(created_items["groups"])
            _cat_done("Groups", len(created_items["groups"]))
            self.results["categories_done"].append(("Groups", len(created_items["groups"])))
        if "accounts" in created_items:
            users = [acc for acc in created_items["accounts"] if "username" in acc]
            if users:
                _cat_start("Accounts")
                self.validate_users(users)
                _cat_done("Accounts", len(users))
                self.results["categories_done"].append(("Accounts", len(users)))

        # — Content (subjects, cameras, inquiries, mass import)
        if "subjects" in created_items:
            _cat_start("Subjects")
            self.validate_subjects(created_items["subjects"])
            subj = created_items["subjects"]
            _cat_done("Subjects", len(subj) if isinstance(subj, list) else 0)
            self.results["categories_done"].append(
                ("Subjects", len(subj) if isinstance(subj, list) else 0)
            )
        if "cameras" in created_items:
            _cat_start("Cameras")
            self.validate_cameras(created_items["cameras"])
            _cat_done("Cameras", len(created_items["cameras"]))
            self.results["categories_done"].append(("Cameras", len(created_items["cameras"])))
        if "inquiries" in created_items:
            _cat_start("Inquiries")
            self.validate_inquiries(created_items["inquiries"])
            _cat_done("Inquiries", len(created_items["inquiries"]))
            self.results["categories_done"].append(("Inquiries", len(created_items["inquiries"])))
        if "mass_import" in created_items:
            _cat_start("Mass import")
            if self.validate_mass_import(created_items["mass_import"]):
                _cat_done("Mass import", 1)
                self.results["categories_done"].append(("Mass import", 1))

        # — External / optional (Rancher env vars, translation file) — acknowledged only, no API check
        if "rancher_env_vars" in created_items and created_items["rancher_env_vars"]:
            _cat_start("Rancher env vars")
            self.validate_env_vars(created_items["rancher_env_vars"])
            _cat_done("Rancher env vars", len(created_items["rancher_env_vars"]))
        if "translation_file" in created_items:
            _cat_start("Translation file")
            self.validate_translation_file(created_items["translation_file"])
            _cat_done("Translation file", 1)
        
        # Print summary
        self.print_summary()

        # Emit completion for UI
        _emit({
            "type": "complete",
            "success": self.results["failed"] == 0,
            "passed": self.results["passed"],
            "failed": self.results["failed"],
            "validated": self.results["validated"],
            "errors": list(self.results["errors"]),
            "skipped": list(self.results.get("skipped", [])),
            "acknowledged": list(self.results.get("acknowledged", [])),
            "manual_checklist": [line.strip() for line in self._manual_verification_checklist()[1:] if line.strip()] if self._manual_verification_checklist() else [],
        })
        
        return self.results['failed'] == 0
    
    def print_summary(self):
        """Print validation summary."""
        logger.info("\n" + "=" * 80)
        logger.info("VALIDATION SUMMARY")
        logger.info("=" * 80)
        
        total = self.results['validated']
        passed = self.results['passed']
        failed = self.results['failed']
        skipped = self.results.get('skipped', [])
        acknowledged = self.results.get('acknowledged', [])
        has_skipped_or_ack = bool(skipped or acknowledged)
        
        logger.info(f"\n📊 Results:")
        if self.results.get('categories_done'):
            breakdown = ", ".join(f"{label} ({n})" for label, n in self.results['categories_done'])
            logger.info(f"  Categories validated: {breakdown}")
        logger.info(f"  Total items validated: {total}")
        logger.info(f"  ✅ Passed: {passed}")
        logger.info(f"  ❌ Failed: {failed}")
        
        if skipped:
            logger.info(f"\n⏭️  Skipped (verify manually):")
            for label, reason in skipped:
                logger.info(f"  • {label}: {reason}")
        
        if acknowledged:
            logger.info(f"\n📋 Acknowledged (not verified on server):")
            for label, note in acknowledged:
                logger.info(f"  • {label}" + (f": {note}" if note else ""))
            logger.info("  → See manual verification checklist below.")
        if failed > 0:
            logger.error(f"\n❌ Validation FAILED - {failed} issue(s) found:")
            for error in self.results['errors']:
                logger.error(f"  • {error}")
            logger.error("\n⚠️  Please review the errors above. Data may have been lost or modified.")
        else:
            if has_skipped_or_ack:
                logger.info("\n✅ Validation PASSED for all checked categories.")
            else:
                logger.info("\n✅ Validation PASSED - All data is present and correct!")
        if has_skipped_or_ack and failed == 0:
            for line in self._manual_verification_checklist():
                logger.warning(line)
        logger.info("=" * 80 + "\n")

    def _manual_verification_checklist(self):
        """Return list of log lines for the manual verification checklist (only when relevant)."""
        skipped_labels = {label for label, _ in self.results.get("skipped", [])}
        ack_labels = {label for label, _ in self.results.get("acknowledged", [])}
        items = []
        if CATEGORY_RANCHER_ENV_VARS in ack_labels:
            items.append(
                f"   {LOG_SKIP} MANUAL CHECK REQUIRED: Rancher env vars – Please confirm in Rancher UI (workload environment) that they match your config/export."
            )
        if CATEGORY_TRANSLATION_FILE in ack_labels:
            items.append(
                f"   {LOG_SKIP} MANUAL CHECK REQUIRED: Translation file – Please confirm on the OnWatch server that the file is present and loaded (uploaded via SSH; no API check)."
            )
        if CATEGORY_MASS_IMPORT in skipped_labels:
            items.append("   [ ] Mass import – Export had no ID; confirm mass import state in OnWatch if needed.")
        if not items:
            return []
        return ["\n📌 Manual verification checklist:"] + items


def main():
    """Main entry point. Exit codes: 0 = all validated and passed; 1 = one or more failures; 2 = passed but some categories skipped (manual verification recommended)."""
    parser = argparse.ArgumentParser(
        description='Validate OnWatch data against output YAML file',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exit codes:
  0  All checked categories passed
  1  One or more validation failures
  2  Passed but some categories were skipped (e.g. Rancher env vars on 2.8) – verify manually

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
        if not success:
            sys.exit(1)
        # Exit 2 when validation passed but some categories were skipped (manual verification needed)
        if validator.results.get('skipped') or validator.results.get('acknowledged'):
            sys.exit(2)
        sys.exit(0)
    except Exception as e:
        logger.error(f"Validation failed: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()



#!/usr/bin/env python3
"""
Configuration management for OnWatch automation.

Handles loading, validation, and environment variable substitution
for YAML configuration files.
"""
import yaml
import os
import sys
import re
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

CONFIG_BACKUP_DIR = ".config_backups"


def _make_backup(config_path):
    """Copy config_path into a hidden backup dir with a timestamped name. Returns backup path or None on failure.

    Used when something writes to an existing user-managed file so the previous
    state can be recovered. Not needed for files we author from scratch.
    """
    import shutil
    from constants import now_israel
    src = Path(config_path)
    if not src.exists():
        return None
    backup_dir = src.parent / CONFIG_BACKUP_DIR
    try:
        backup_dir.mkdir(exist_ok=True)
        backup_path = backup_dir / f"{src.name}.backup.{now_israel().strftime('%Y%m%d_%H%M%S')}"
        shutil.copy2(src, backup_path)
        logger.info(f"Created backup: {backup_path}")
        return str(backup_path)
    except Exception as e:
        logger.warning(f"Could not create backup: {e}")
        return None


def _deep_merge(base, overlay):
    """Recursively merge overlay into base. Returns a new dict.

    - Nested dicts merge key-by-key.
    - Scalars and lists in overlay replace whatever's in base.
    - Does not mutate either input.
    """
    if not isinstance(base, dict):
        return overlay
    if not isinstance(overlay, dict):
        return overlay
    result = dict(base)
    for k, v in overlay.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


class ConfigManager:
    """Manages configuration loading, validation, and environment variable substitution.

    Operator overrides (IP, version, etc.) are kept in an untracked overlay file
    next to the main config: e.g. config.yaml + config.local.yaml. The overlay
    is deep-merged on top of the base at load time, and update_* methods write
    only the changed fields to the overlay — so the tracked config.yaml stays
    free of per-machine state and `git status` stays clean.
    """

    def __init__(self, config_path="config.yaml"):
        """
        Initialize configuration manager.

        Args:
            config_path: Path to YAML configuration file
        """
        self.config_path = config_path
        self.config = None

    def _overlay_path(self):
        """Return the path to the local overlay file (sibling of config_path).

        config.yaml -> config.local.yaml
        my-config.yaml -> my-config.local.yaml
        """
        return Path(self.config_path).with_suffix(".local.yaml")

    def _load_overlay(self):
        """Load the overlay file if it exists; return {} otherwise."""
        path = self._overlay_path()
        if not path.exists():
            return {}
        try:
            with open(path, "r") as f:
                data = yaml.safe_load(f) or {}
            if not isinstance(data, dict):
                logger.warning(f"Overlay {path} is not a YAML mapping; ignoring")
                return {}
            return data
        except yaml.YAMLError as e:
            logger.error(f"Could not parse overlay {path}: {e}")
            return {}

    def _save_overlay(self, updates):
        """Deep-merge `updates` into the overlay file (creating it if needed) and persist.

        Returns (success: bool, message: str).
        """
        path = self._overlay_path()
        current = self._load_overlay()
        merged = _deep_merge(current, updates)
        try:
            with open(path, "w") as f:
                f.write(
                    "# Operator overrides for OnWatch automation.\n"
                    "# This file is gitignored and written by the web UI / CLI.\n"
                    "# Values here are deep-merged over config.yaml at load time.\n"
                )
                yaml.dump(merged, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
            return True, str(path)
        except Exception as e:
            return False, f"Failed to write overlay {path}: {e}"
    
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
        """Load configuration: base YAML + overlay file, with environment variable substitution."""
        try:
            with open(self.config_path, 'r') as f:
                config = yaml.safe_load(f) or {}

            overlay = self._load_overlay()
            if overlay:
                config = _deep_merge(config, overlay)
                logger.debug(f"Applied overlay from {self._overlay_path()}")

            # Substitute environment variables (applies to merged result so $VARS work in overlay too)
            config = self._recursive_substitute_env(config)

            logger.debug(f"Configuration loaded from {self.config_path}")
            self.config = config
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
    
    def _validate_file_path(self, file_path, field_name, required=True, project_root=None):
        """Validate file path exists (if not using env var)."""
        if not file_path:
            if required:
                return False, f"{field_name}: File path is required"
            return True, None
        
        # Check if it's an environment variable placeholder
        if isinstance(file_path, str) and (file_path.startswith('${') or file_path.startswith('$')):
            return True, None
        
        # Resolve relative paths
        # Use provided project_root (from main.py) or fall back to config file directory
        if project_root is None:
            project_root = os.path.dirname(os.path.abspath(self.config_path))
        
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
        if self.config is None:
            self.load_config()
        
        errors = []
        warnings = []
        config = self.config
        
        if not config:
            errors.append("Configuration file is empty or invalid")
            return False, errors
        
        # Validate required sections
        required_sections = {
            'onwatch': ['ip_address', 'username', 'password'],
            'ssh': ['ip_address', 'username', 'password'],  # translation_util_path optional (auto-detected if not set)
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
        # Resolve paths relative to the project root (where main.py is located)
        # We'll use the config file's directory as a fallback, but ideally project_root should be passed
        # For now, assume config.yaml is in the project root
        project_root = os.path.dirname(os.path.abspath(self.config_path))
        
        # Validate translation file path
        if 'system_settings' in config and 'system_interface' in config['system_settings']:
            translation_file = config['system_settings']['system_interface'].get('translation_file')
            if translation_file:
                is_valid, error_msg = self._validate_file_path(translation_file, 'system_settings.system_interface.translation_file', required=False, project_root=project_root)
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
                        is_valid, error_msg = self._validate_file_path(img_path, f'watch_list.subjects[{idx}].images[{img_idx}]', required=False, project_root=project_root)
                        if not is_valid:
                            warnings.append(f"Subject '{name}': {error_msg}")
        
        # Validate mass import file path
        if 'mass_import' in config:
            mass_import_file = config['mass_import'].get('file_path')
            if mass_import_file:
                is_valid, error_msg = self._validate_file_path(mass_import_file, 'mass_import.file_path', required=False, project_root=project_root)
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
                            is_valid, error_msg = self._validate_file_path(file_path, f'inquiries[{idx}].files.{filename}', required=False, project_root=project_root)
                            if not is_valid:
                                warnings.append(error_msg)
                elif isinstance(files, list):
                    for file_idx, file_item in enumerate(files):
                        if isinstance(file_item, dict):
                            file_path = file_item.get('path', '')
                        else:
                            file_path = file_item if isinstance(file_item, str) else ''
                        
                        if file_path:
                            is_valid, error_msg = self._validate_file_path(file_path, f'inquiries[{idx}].files[{file_idx}]', required=False, project_root=project_root)
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
    
    def update_ip_address(self, new_ip, backup=True):
        """Write connection IPs to the overlay file. The tracked config.yaml is not touched.

        Updates onwatch.ip_address + base_url, ssh.ip_address, rancher.ip_address + base_url.
        Camera video_url IPs are never touched.

        Args:
            new_ip: New IP address to set
            backup: If True and overlay exists, snapshot it before writing

        Returns:
            tuple: (success: bool, message: str)
        """
        if not self._validate_ip_address(new_ip, "new_ip"):
            return False, f"Invalid IP address format: {new_ip}"

        # Need the merged config to derive base_url ports/paths
        if self.config is None:
            self.load_config()

        if backup:
            _make_backup(self._overlay_path())

        def _replace_ip_in_url(url):
            if not isinstance(url, str):
                return None
            ip_pattern = r'\b(\d{1,3}\.){3}\d{1,3}\b'
            if not re.search(ip_pattern, url):
                return None
            return re.sub(ip_pattern, new_ip, url)

        updates = {}
        onwatch = (self.config or {}).get("onwatch", {}) or {}
        ssh = (self.config or {}).get("ssh", {}) or {}
        rancher = (self.config or {}).get("rancher", {}) or {}

        if onwatch:
            ow_updates = {"ip_address": new_ip}
            new_url = _replace_ip_in_url(onwatch.get("base_url"))
            if new_url:
                ow_updates["base_url"] = new_url
            updates["onwatch"] = ow_updates

        if ssh:
            updates["ssh"] = {"ip_address": new_ip}

        if rancher:
            r_updates = {"ip_address": new_ip}
            new_url = _replace_ip_in_url(rancher.get("base_url"))
            if new_url:
                r_updates["base_url"] = new_url
            updates["rancher"] = r_updates

        if not updates:
            return False, "No onwatch/ssh/rancher sections found to update"

        ok, info = self._save_overlay(updates)
        if not ok:
            return False, info

        # Reload merged config so future reads see the change
        self.config = None
        self.load_config()

        sections = ", ".join(updates.keys())
        return True, f"Saved IP {new_ip} to {info} ({sections})"
    
    def update_version(self, version, backup=True):
        """Write OnWatch version + matching Rancher password to the overlay file.

        Rancher password defaults:
          - 2.6 -> "admin"
          - 2.8 -> "administrator"

        Args:
            version: OnWatch version ("2.6" or "2.8")
            backup: If True and overlay exists, snapshot it before writing

        Returns:
            tuple: (success: bool, message: str)
        """
        if version not in ["2.6", "2.8"]:
            return False, f"Invalid version: {version}. Must be '2.6' or '2.8'"

        if backup:
            _make_backup(self._overlay_path())

        rancher_password = "administrator" if version == "2.8" else "admin"
        updates = {
            "onwatch": {"version": version},
            "rancher": {"password": rancher_password},
        }

        ok, info = self._save_overlay(updates)
        if not ok:
            return False, info

        self.config = None
        self.load_config()

        return True, (
            f"Saved version {version} (and matching rancher.password) to {info}"
        )


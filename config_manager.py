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

logger = logging.getLogger(__name__)


class ConfigManager:
    """Manages configuration loading, validation, and environment variable substitution."""
    
    def __init__(self, config_path="config.yaml"):
        """
        Initialize configuration manager.
        
        Args:
            config_path: Path to YAML configuration file
        """
        self.config_path = config_path
        self.config = None
    
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
        """
        Update connection IP addresses in the configuration file.
        
        Updates only connection-related IPs (not camera IPs):
        - onwatch.ip_address
        - onwatch.base_url (replaces IP in URL)
        - ssh.ip_address
        - rancher.base_url (replaces IP in URL)
        
        Does NOT update:
        - Camera video_url IPs (devices[].video_url) - these are immutable
        
        Args:
            new_ip: New IP address to set
            backup: If True, create a backup of the original config file
            
        Returns:
            tuple: (success: bool, message: str)
        """
        import yaml
        
        # Validate IP address format
        if not self._validate_ip_address(new_ip, "new_ip"):
            return False, f"Invalid IP address format: {new_ip}"
        
        # Load current config
        if self.config is None:
            self.load_config()
        
        # Create backup if requested
        if backup:
            import shutil
            from datetime import datetime
            backup_path = f"{self.config_path}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            try:
                shutil.copy2(self.config_path, backup_path)
                logger.info(f"Created backup: {backup_path}")
            except Exception as e:
                logger.warning(f"Could not create backup: {e}")
        
        # Update specific connection IPs in config dict (preserves camera IPs)
        replacement_count = 0
        
        # Update onwatch.ip_address
        if 'onwatch' in self.config and 'ip_address' in self.config['onwatch']:
            old_ip = self.config['onwatch']['ip_address']
            if old_ip != new_ip:
                self.config['onwatch']['ip_address'] = new_ip
                replacement_count += 1
                logger.debug(f"Updated onwatch.ip_address: {old_ip} -> {new_ip}")
        
        # Update onwatch.base_url (IP in URL)
        if 'onwatch' in self.config and 'base_url' in self.config['onwatch']:
            base_url = self.config['onwatch']['base_url']
            # Extract IP from URL and replace
            ip_pattern = r'\b(\d{1,3}\.){3}\d{1,3}\b'
            if re.search(ip_pattern, base_url):
                new_base_url = re.sub(ip_pattern, new_ip, base_url)
                if new_base_url != base_url:
                    self.config['onwatch']['base_url'] = new_base_url
                    replacement_count += 1
                    logger.debug(f"Updated onwatch.base_url: {base_url} -> {new_base_url}")
        
        # Update ssh.ip_address
        if 'ssh' in self.config and 'ip_address' in self.config['ssh']:
            old_ip = self.config['ssh']['ip_address']
            if old_ip != new_ip:
                self.config['ssh']['ip_address'] = new_ip
                replacement_count += 1
                logger.debug(f"Updated ssh.ip_address: {old_ip} -> {new_ip}")
        
        # Update rancher.base_url (IP in URL)
        if 'rancher' in self.config and 'base_url' in self.config['rancher']:
            base_url = self.config['rancher']['base_url']
            # Extract IP from URL and replace
            ip_pattern = r'\b(\d{1,3}\.){3}\d{1,3}\b'
            if re.search(ip_pattern, base_url):
                new_base_url = re.sub(ip_pattern, new_ip, base_url)
                if new_base_url != base_url:
                    self.config['rancher']['base_url'] = new_base_url
                    replacement_count += 1
                    logger.debug(f"Updated rancher.base_url: {base_url} -> {new_base_url}")
        
        if replacement_count == 0:
            return False, "No connection IP addresses found to update in config file"
        
        # Write back to file using targeted line-by-line replacement (preserves formatting and comments)
        try:
            # Read file as lines
            with open(self.config_path, 'r') as f:
                lines = f.readlines()
            
            # Update specific lines only (preserves rest of file)
            ip_pattern = r'\b(\d{1,3}\.){3}\d{1,3}\b'
            updated_lines = []
            i = 0
            in_onwatch_section = False
            in_ssh_section = False
            in_rancher_section = False
            
            while i < len(lines):
                line = lines[i]
                original_line = line
                
                # Track which section we're in
                if re.match(r'^onwatch:\s*$', line):
                    in_onwatch_section = True
                    in_ssh_section = False
                    in_rancher_section = False
                elif re.match(r'^ssh:\s*$', line):
                    in_onwatch_section = False
                    in_ssh_section = True
                    in_rancher_section = False
                elif re.match(r'^rancher:\s*$', line):
                    in_onwatch_section = False
                    in_ssh_section = False
                    in_rancher_section = True
                elif line.strip() and not line.strip().startswith('#'):
                    # If we hit a new top-level key, reset section flags
                    if re.match(r'^[a-z_]+:\s*$', line):
                        in_onwatch_section = False
                        in_ssh_section = False
                        in_rancher_section = False
                
                # Update onwatch.ip_address line
                if in_onwatch_section and re.match(r'^\s*ip_address:\s*"' + ip_pattern, line):
                    line = re.sub(ip_pattern, new_ip, line)
                    replacement_count += 1
                    logger.debug(f"Updated onwatch.ip_address line: {original_line.strip()} -> {line.strip()}")
                
                # Update onwatch.base_url line - simple string replacement
                elif in_onwatch_section and 'base_url' in line and 'https://' in line:
                    # Find IP in the line and replace it - simple and safe
                    # Line format: base_url: "https://10.1.71.14"
                    old_line = line
                    # Find the IP address in the URL and replace it
                    line = re.sub(r'https://' + ip_pattern, 'https://' + new_ip, line)
                    if line != old_line:
                        replacement_count += 1
                        logger.debug(f"Updated onwatch.base_url line: {original_line.strip()} -> {line.strip()}")
                
                # Update ssh.ip_address line
                elif in_ssh_section and re.match(r'^\s*ip_address:\s*"' + ip_pattern, line):
                    line = re.sub(ip_pattern, new_ip, line)
                    replacement_count += 1
                    logger.debug(f"Updated ssh.ip_address line: {original_line.strip()} -> {line.strip()}")
                
                # Update rancher.base_url line - simple string replacement
                elif in_rancher_section and 'base_url' in line and 'https://' in line:
                    # Find IP in the line and replace it - simple and safe
                    # Line format: base_url: "https://10.1.71.14:9443"
                    old_line = line
                    # Find the IP address in the URL and replace it (preserves https:// and :9443)
                    line = re.sub(r'https://' + ip_pattern, 'https://' + new_ip, line)
                    if line != old_line:
                        replacement_count += 1
                        logger.debug(f"Updated rancher.base_url line: {original_line.strip()} -> {line.strip()}")
                
                updated_lines.append(line)
                i += 1
            
            # Write back
            with open(self.config_path, 'w') as f:
                f.writelines(updated_lines)
            
            # Reload config to reflect changes
            self.config = None
            self.load_config()
            
            return True, f"Successfully updated {replacement_count} connection IP address(es) to {new_ip} (camera IPs preserved)"
        except Exception as e:
            return False, f"Failed to write config file: {e}"


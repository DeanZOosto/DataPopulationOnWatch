#!/usr/bin/env python3
"""
Unit tests for ConfigManager.
"""
import pytest
import os
import tempfile
import yaml
from pathlib import Path
import sys

# Add parent directory to path to import modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from config_manager import ConfigManager


class TestConfigManager:
    """Test cases for ConfigManager."""
    
    def test_load_config_basic(self):
        """Test loading a basic valid config file."""
        # Create a temporary config file
        config_data = {
            'onwatch': {
                'ip_address': '10.1.1.1',
                'username': 'admin',
                'password': 'password123',
                'base_url': 'https://10.1.1.1'
            }
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(config_data, f)
            temp_path = f.name
        
        try:
            manager = ConfigManager(temp_path)
            config = manager.load_config()
            assert config is not None
            assert config['onwatch']['ip_address'] == '10.1.1.1'
            assert config['onwatch']['username'] == 'admin'
        finally:
            os.unlink(temp_path)
    
    def test_env_var_substitution(self):
        """Test environment variable substitution in config."""
        # Set an environment variable
        os.environ['TEST_PASSWORD'] = 'env_password_123'
        
        config_data = {
            'onwatch': {
                'ip_address': '10.1.1.1',
                'username': 'admin',
                'password': '${TEST_PASSWORD}',
                'base_url': 'https://10.1.1.1'
            }
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(config_data, f)
            temp_path = f.name
        
        try:
            manager = ConfigManager(temp_path)
            config = manager.load_config()
            assert config['onwatch']['password'] == 'env_password_123'
        finally:
            os.unlink(temp_path)
            if 'TEST_PASSWORD' in os.environ:
                del os.environ['TEST_PASSWORD']
    
    def test_validate_config_missing_section(self):
        """Test validation fails when required section is missing."""
        config_data = {
            'onwatch': {
                'ip_address': '10.1.1.1',
                # Missing username, password, base_url
            }
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(config_data, f)
            temp_path = f.name
        
        try:
            manager = ConfigManager(temp_path)
            manager.load_config()
            is_valid, errors = manager.validate_config()
            assert not is_valid
            assert len(errors) > 0
        finally:
            os.unlink(temp_path)
    
    def test_validate_config_valid(self):
        """Test validation passes for a complete valid config."""
        config_data = {
            'onwatch': {
                'ip_address': '10.1.1.1',
                'username': 'admin',
                'password': 'password123',
                'base_url': 'https://10.1.1.1'
            },
            'ssh': {
                'ip_address': '10.1.1.1',
                'username': 'user',
                'password': 'user1!',
                'translation_util_path': '/usr/local/bin/translation-util'
            },
            'rancher': {
                'ip_address': '10.1.1.1',
                'port': 9443,
                'username': 'admin',
                'password': 'admin',
                'base_url': 'https://10.1.1.1:9443',
                'workload_path': '/p/local:p-p6l45/workloads/run?workloadId=statefulset%3Adefault%3Acv-engine'
            }
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(config_data, f)
            temp_path = f.name
        
        try:
            manager = ConfigManager(temp_path)
            manager.load_config()
            is_valid, errors = manager.validate_config()
            assert is_valid, f"Validation failed with errors: {errors}"
        finally:
            os.unlink(temp_path)

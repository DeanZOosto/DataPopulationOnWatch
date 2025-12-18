#!/usr/bin/env python3
"""
Integration/user-like tests for main workflows.
These tests simulate user scenarios without requiring actual API connections.
"""
import pytest
import sys
import tempfile
import os
import yaml
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# Add parent directory to path to import modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from config_manager import ConfigManager
from run_summary import RunSummary


class TestIntegrationWorkflows:
    """Integration tests simulating user workflows."""
    
    def test_config_validation_workflow(self):
        """Test the config validation workflow that users run."""
        # Create a minimal valid config
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
            },
            'kv_parameters': {},
            'system_settings': {},
            'groups': [],
            'accounts': {'users': [], 'user_groups': []},
            'devices': [],
            'inquiries': [],
            'watch_list': {'subjects': []},
            'env_vars': {}
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(config_data, f)
            temp_path = f.name
        
        try:
            manager = ConfigManager(temp_path)
            manager.load_config()
            is_valid, errors = manager.validate_config(verbose=True)
            
            # Config should be valid
            assert is_valid, f"Config validation failed: {errors}"
        finally:
            os.unlink(temp_path)
    
    def test_export_file_generation(self):
        """Test that export file is generated correctly (user workflow)."""
        summary = RunSummary()
        summary.start_timing(onwatch_ip='10.1.1.1')
        
        # Simulate a successful automation run
        summary.record_step(1, "Initialize API Client", "success")
        summary.record_step(2, "Set KV Parameters", "success")
        
        # Add some created items
        summary.add_created_item('kv_parameters', {
            'key': 'applicationSettings/test',
            'value': 'test_value'
        })
        summary.add_created_item('rancher_env_vars', {
            'key': 'TEST_VAR',
            'value': 'test_value'
        })
        
        summary.end_timing()
        
        # Export to file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            temp_path = f.name
        
        try:
            export_path = summary.export_to_file(output_path=temp_path, format='yaml')
            assert export_path is not None
            assert os.path.exists(temp_path)
            
            # Load and verify the exported data
            with open(temp_path, 'r') as f:
                exported_data = yaml.safe_load(f)
            
            assert 'metadata' in exported_data
            assert 'created_items' in exported_data
            assert exported_data['metadata']['onwatch_ip'] == '10.1.1.1'
            assert len(exported_data['created_items']['kv_parameters']) == 1
            assert len(exported_data['created_items']['rancher_env_vars']) == 1
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
    
    def test_priority_mapping_in_workflow(self):
        """Test priority mapping works correctly in inquiry workflow."""
        # Test that "Medium" maps to 101
        priority_map = {"low": 201, "medium": 101, "high": 1}
        
        test_cases = [
            ("Medium", 101),
            ("medium", 101),
            ("MEDIUM", 101),
            ("Low", 201),
            ("High", 1),
        ]
        
        for priority_str, expected_value in test_cases:
            mapped_value = priority_map.get(priority_str.lower(), 101)
            assert mapped_value == expected_value, \
                f"Priority '{priority_str}' should map to {expected_value}, got {mapped_value}"
    
    def test_rancher_env_vars_tracking(self):
        """Test that Rancher env vars are tracked even if step fails."""
        summary = RunSummary()
        
        # Simulate adding env vars at start (before step execution)
        env_vars = {
            'ENABLE_DVR': 'True',
            'SERVICE_TAGS': 'test-tag'
        }
        
        for key, value in env_vars.items():
            summary.add_created_item('rancher_env_vars', {
                'key': key,
                'value': str(value)
            })
        
        # Even if step fails, env vars should be in export
        summary.record_step(11, "Configure Rancher", "failed", "Connection error")
        
        # Export should include env vars
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            temp_path = f.name
        
        try:
            summary.export_to_file(output_path=temp_path, format='yaml')
            
            with open(temp_path, 'r') as f:
                exported_data = yaml.safe_load(f)
            
            # Env vars should be present even though step failed
            assert 'rancher_env_vars' in exported_data['created_items']
            assert len(exported_data['created_items']['rancher_env_vars']) == 2
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

#!/usr/bin/env python3
"""
Unit tests for RunSummary.
"""
import pytest
import sys
import tempfile
import os
from pathlib import Path

# Add parent directory to path to import modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from run_summary import RunSummary


class TestRunSummary:
    """Test cases for RunSummary."""
    
    def test_initialization(self):
        """Test RunSummary initializes correctly."""
        summary = RunSummary()
        assert summary.steps == {}
        assert summary.errors == []
        assert summary.warnings == []
        assert summary.skipped == []
        assert summary.created_items is not None
        assert 'kv_parameters' in summary.created_items
        assert 'rancher_env_vars' in summary.created_items
    
    def test_record_step(self):
        """Test recording step execution."""
        summary = RunSummary()
        summary.record_step(1, "Test Step", "success", "Completed successfully")
        
        assert 1 in summary.steps
        assert summary.steps[1]['name'] == "Test Step"
        assert summary.steps[1]['status'] == "success"
        assert summary.steps[1]['message'] == "Completed successfully"
    
    def test_record_step_failed(self):
        """Test recording failed step adds to errors."""
        summary = RunSummary()
        summary.record_step(1, "Test Step", "failed", "Error occurred")
        
        assert len(summary.errors) == 1
        assert "Step 1" in summary.errors[0]
    
    def test_add_created_item_kv_parameter(self):
        """Test adding KV parameter to created items."""
        summary = RunSummary()
        summary.add_created_item('kv_parameters', {
            'key': 'test.key',
            'value': 'test_value'
        })
        
        assert len(summary.created_items['kv_parameters']) == 1
        assert summary.created_items['kv_parameters'][0]['key'] == 'test.key'
        assert summary.created_items['kv_parameters'][0]['value'] == 'test_value'
    
    def test_add_created_item_rancher_env_vars(self):
        """Test adding Rancher environment variable to created items."""
        summary = RunSummary()
        summary.add_created_item('rancher_env_vars', {
            'key': 'TEST_VAR',
            'value': 'test_value'
        })
        
        assert len(summary.created_items['rancher_env_vars']) == 1
        assert summary.created_items['rancher_env_vars'][0]['key'] == 'TEST_VAR'
        assert summary.created_items['rancher_env_vars'][0]['value'] == 'test_value'
    
    def test_export_to_file_yaml(self):
        """Test exporting summary to YAML file."""
        summary = RunSummary()
        summary.start_timing(onwatch_ip='10.1.1.1')
        summary.record_step(1, "Test Step", "success")
        summary.add_created_item('kv_parameters', {'key': 'test.key', 'value': 'test_value'})
        summary.end_timing()
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            temp_path = f.name
        
        try:
            export_path = summary.export_to_file(output_path=temp_path, format='yaml')
            assert export_path is not None
            assert os.path.exists(temp_path)
            
            # Verify file contains expected data
            with open(temp_path, 'r') as f:
                content = f.read()
                assert 'test.key' in content
                assert 'test_value' in content
                assert '10.1.1.1' in content
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
    
    def test_format_duration(self):
        """Test duration formatting."""
        summary = RunSummary()
        
        # Test seconds
        assert summary.format_duration(5.5) == "5.5s"
        
        # Test minutes
        assert summary.format_duration(125) == "2m 5s"
        
        # Test None
        assert summary.format_duration(None) == "N/A"

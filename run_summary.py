#!/usr/bin/env python3
"""
Run summary tracking and reporting for OnWatch automation.

Tracks step execution results, errors, warnings, and skipped items,
then generates a comprehensive summary report.
"""
import logging
import time
import json
import yaml
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class RunSummary:
    """Track and report automation run summary."""
    
    def __init__(self):
        self.steps = {}
        self.errors = []
        self.warnings = []
        self.skipped = []
        self.manual_actions_needed = []
        
        # Timing tracking
        self.start_time = None
        self.end_time = None
        self.step_timings = {}  # step_num -> {'start': time, 'end': time, 'duration': seconds}
        
        # Track what was actually created/set on OnWatch
        self.created_items = {
            'kv_parameters': [],
            'system_settings': {},
            'groups': [],
            'accounts': [],
            'subjects': [],
            'cameras': [],
            'inquiries': [],
            'mass_import': None,
            'rancher_env_vars': [],
            'translation_file': None
        }
        
        # Metadata for export
        self.onwatch_ip = None
        self.onwatch_version = None  # OnWatch version (2.6 or 2.8)
        self.run_timestamp = None
    
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
    
    def add_error(self, item_type, item_name, error_detail=""):
        """Record an error for an individual item (not a step-level error)."""
        error_msg = f"{item_type}: {item_name}"
        if error_detail:
            error_msg += f" - {error_detail}"
        self.errors.append(error_msg)
    
    def start_timing(self, onwatch_ip=None):
        """Start timing for the automation run."""
        self.start_time = time.time()
        self.run_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.onwatch_ip = onwatch_ip
    
    def record_step_timing(self, step_num, start_time, end_time):
        """Record timing for a specific step."""
        duration = end_time - start_time
        self.step_timings[step_num] = {
            'start': start_time,
            'end': end_time,
            'duration': duration
        }
    
    def end_timing(self):
        """End timing for the automation run."""
        self.end_time = time.time()
    
    def get_total_duration(self):
        """Get total run duration in seconds."""
        if self.start_time and self.end_time:
            return self.end_time - self.start_time
        return None
    
    def format_duration(self, seconds):
        """Format duration in human-readable format."""
        if seconds is None:
            return "N/A"
        if seconds < 60:
            return f"{seconds:.1f}s"
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"
    
    def add_created_item(self, category, item_data):
        """
        Track an item that was created/set on OnWatch.
        
        Args:
            category: One of 'kv_parameters', 'groups', 'accounts', 'subjects', 
                     'cameras', 'inquiries', 'mass_import', 'rancher_env_vars', 
                     'translation_file', 'system_settings', 'logo'
            item_data: Dictionary with item details
        """
        if category == 'mass_import':
            self.created_items['mass_import'] = item_data
        elif category == 'translation_file':
            self.created_items['translation_file'] = item_data
        elif category == 'system_settings':
            # Merge system settings
            self.created_items['system_settings'].update(item_data)
        elif category == 'logo':
            # Add logo to system_interface section
            if 'system_interface' not in self.created_items['system_settings']:
                self.created_items['system_settings']['system_interface'] = {}
            if 'logos' not in self.created_items['system_settings']['system_interface']:
                self.created_items['system_settings']['system_interface']['logos'] = []
            self.created_items['system_settings']['system_interface']['logos'].append(item_data)
        elif category in self.created_items:
            self.created_items[category].append(item_data)
        else:
            logger.warning(f"Unknown category for created item: {category}")
    
    def print_summary(self):
        """Print a comprehensive summary of the run."""
        logger.info("\n" + "=" * 80)
        logger.info("AUTOMATION RUN SUMMARY")
        logger.info("=" * 80)
        
        # Step-by-step status with timing
        logger.info("\n📋 Step Status:")
        for step_num in sorted(self.steps.keys()):
            step = self.steps[step_num]
            status_icon = {
                'success': '✅',
                'failed': '❌',
                'skipped': '⏭️',
                'partial': '⚠️'
            }.get(step['status'], '❓')
            
            # Add timing if available
            timing_str = ""
            if step_num in self.step_timings:
                duration = self.step_timings[step_num]['duration']
                timing_str = f" ({self.format_duration(duration)})"
            
            logger.info(f"  {status_icon} Step {step_num}: {step['name']} - {step['status'].upper()}{timing_str}")
            if step['message']:
                logger.info(f"     {step['message']}")
        
        # Statistics
        total_steps = len(self.steps)
        successful = sum(1 for s in self.steps.values() if s['status'] == 'success')
        failed = sum(1 for s in self.steps.values() if s['status'] == 'failed')
        skipped_steps = sum(1 for s in self.steps.values() if s['status'] == 'skipped')
        
        # Total duration
        total_duration = self.get_total_duration()
        duration_str = self.format_duration(total_duration) if total_duration else "N/A"
        
        logger.info(f"\n📊 Statistics:")
        logger.info(f"  Total Steps: {total_steps}")
        logger.info(f"  ✅ Successful: {successful} (items created/updated)")
        logger.info(f"  ❌ Failed: {failed}")
        logger.info(f"  ⏭️  Skipped Steps: {skipped_steps}")
        logger.info(f"  ⏭️  Skipped Items: {len(self.skipped)} (items already exist - expected behavior)")
        logger.info(f"  ❌ Errors: {len(self.errors)}")
        if total_duration:
            logger.info(f"  ⏱️  Total Duration: {duration_str}")
        
        # Skipped items details
        if self.skipped:
            logger.info(f"\n⏭️  Skipped Items Details ({len(self.skipped)}):")
            for item in self.skipped[:20]:  # Show first 20
                logger.info(f"  - {item}")
            if len(self.skipped) > 20:
                logger.info(f"  ... and {len(self.skipped) - 20} more")
        
        # Errors details
        if self.errors:
            logger.error(f"\n❌ ERROR Details ({len(self.errors)}):")
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
        
        # Created Items Summary (for transparency)
        logger.info(f"\n📦 Created Items Summary:")
        created_counts = {}
        for category, items in self.created_items.items():
            if items:
                if isinstance(items, list):
                    count = len(items)
                    created_counts[category] = count
                    logger.info(f"  • {category.replace('_', ' ').title()}: {count} item(s)")
                elif isinstance(items, dict) and items:
                    # For system_settings, show what was configured
                    if category == 'system_settings':
                        logger.info(f"  • System Settings: Configured")
                        # Show logos if present
                        if 'system_interface' in items and 'logos' in items['system_interface']:
                            logos = items['system_interface']['logos']
                            if isinstance(logos, dict):
                                logo_types = list(logos.keys())
                                logger.info(f"    - Logos/Favicon: {', '.join(logo_types)}")
                            elif isinstance(logos, list) and logos:
                                logger.info(f"    - Logos/Favicon: {len(logos)} uploaded")
                    else:
                        created_counts[category] = 1
                        logger.info(f"  • {category.replace('_', ' ').title()}: Configured")
                elif items is not None:
                    created_counts[category] = 1
                    logger.info(f"  • {category.replace('_', ' ').title()}: Uploaded/Configured")
        
        if not created_counts and not any(isinstance(v, dict) and v for v in self.created_items.values()):
            logger.info("  (No items created - all may have been skipped)")
        
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
    
    def export_to_file(self, output_path=None, format='yaml'):
        """
        Export created items to a file for post-upgrade validation.
        
        Args:
            output_path: Path to output file (if None, auto-generates filename)
            format: 'yaml' or 'json'
        
        Returns:
            Path to exported file
        """
        if output_path is None:
            # Auto-generate filename with timestamp
            timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
            filename = f"onwatch_data_export_{timestamp}.{format}"
            output_path = Path(filename)
        
        output_path = Path(output_path)
        
        # Prepare export data
        export_data = {
            'metadata': {
                'generated_at': self.run_timestamp or datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'onwatch_ip': self.onwatch_ip or 'unknown',
                'onwatch_version': getattr(self, 'onwatch_version', None),  # Version if available
                'total_duration': self.format_duration(self.get_total_duration()),
                'run_status': {
                    'total_steps': len(self.steps),
                    'successful_steps': sum(1 for s in self.steps.values() if s['status'] == 'success'),
                    'failed_steps': sum(1 for s in self.steps.values() if s['status'] == 'failed'),
                    'skipped_items_count': len(self.skipped),
                    'errors_count': len(self.errors)
                }
            },
            'created_items': {}
        }
        
        # Only include non-empty categories
        for category, items in self.created_items.items():
            if items:  # Skip empty lists, None, and empty dicts
                if isinstance(items, dict) and items:  # system_settings
                    # Clean up system_settings: remove empty icons field
                    cleaned_items = self._clean_system_settings(items)
                    export_data['created_items'][category] = cleaned_items
                elif isinstance(items, list) and items:  # lists
                    export_data['created_items'][category] = items
                elif items is not None:  # mass_import, translation_file
                    export_data['created_items'][category] = items
        
        # Write to file
        try:
            with open(output_path, 'w') as f:
                if format.lower() == 'yaml':
                    yaml.dump(export_data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
                else:  # json
                    json.dump(export_data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"📄 Exported OnWatch data to: {output_path.absolute()}")
            return str(output_path.absolute())
        except Exception as e:
            logger.error(f"Failed to export data to {output_path}: {e}")
            return None
    
    def _clean_system_settings(self, settings):
        """
        Clean system settings for export.
        Removes empty fields and ensures logos are properly structured.
        """
        cleaned = settings.copy()
        if 'system_interface' in cleaned and isinstance(cleaned['system_interface'], dict):
            cleaned_interface = cleaned['system_interface'].copy()
            # Remove empty icons field (if it exists and is empty)
            if 'icons' in cleaned_interface and not cleaned_interface['icons']:
                del cleaned_interface['icons']
            # Ensure logos are properly included if they exist
            # Logos are stored in system_interface.logos as a list from add_created_item
            if 'logos' in cleaned_interface and isinstance(cleaned_interface['logos'], list):
                # Convert list of logo dicts to a more readable structure
                logos_dict = {}
                for logo_item in cleaned_interface['logos']:
                    logo_type = logo_item.get('type')
                    if logo_type:
                        logos_dict[logo_type] = {
                            'source_file': logo_item.get('source_file', ''),
                            'path': logo_item.get('path', '')  # Config path (relative)
                        }
                if logos_dict:
                    cleaned_interface['logos'] = logos_dict
            cleaned['system_interface'] = cleaned_interface
        return cleaned


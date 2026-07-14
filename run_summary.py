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

from constants import now_israel

logger = logging.getLogger(__name__)

EXPORTS_DIR = "exports"


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
        self.run_timestamp = now_israel().strftime('%Y-%m-%d %H:%M:%S')
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
    
    def get_manual_checklist_for_ui(self):
        """Build manual verification checklist for UI (population run)."""
        items = []
        for action in self.manual_actions_needed:
            items.append(action)
        if self.created_items.get('rancher_env_vars'):
            items.append(
                "MANUAL CHECK REQUIRED: Rancher env vars – Please confirm in Rancher UI (workload environment) that they match your config/export."
            )
        if self.created_items.get('cameras'):
            cam_count = len(self.created_items.get('cameras') or [])
            items.append(
                f"MANUAL ACTION REQUIRED: {cam_count} camera(s) were created and are left LIVE and CONNECTED. "
                "You are responsible for DISABLING these streams before running the upgrade, so alerts reach a "
                "steady state you can validate against afterwards."
            )
        for w in self.warnings:
            if 'manual' in w.lower():
                items.append(w)
        return items

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
        total_steps = len(self.steps)
        logger.info(f"\n📋 Step Status (1–{total_steps}):")
        for i, step_num in enumerate(sorted(self.steps.keys()), start=1):
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
            
            logger.info(f"  {i}. {status_icon} {step['name']} – {step['status'].upper()}{timing_str}")
            if step['message']:
                logger.info(f"      {step['message']}")
        
        # Statistics
        successful = sum(1 for s in self.steps.values() if s['status'] == 'success')
        failed = sum(1 for s in self.steps.values() if s['status'] == 'failed')
        skipped_steps = sum(1 for s in self.steps.values() if s['status'] == 'skipped')
        
        # Total duration
        total_duration = self.get_total_duration()
        duration_str = self.format_duration(total_duration) if total_duration else "N/A"
        
        logger.info(f"\n📊 Statistics:")
        logger.info(f"  Total Steps: {len(self.steps)}")
        logger.info(f"  ✅ Successful: {successful} (items created/updated)")
        logger.info(f"  ❌ Failed: {failed}")
        logger.info(f"  ⏭️  Skipped Steps: {skipped_steps}")
        logger.info(f"  ⏭️  Skipped Items: {len(self.skipped)} (items already exist - expected behavior)")
        logger.info(f"  ❌ Errors: {len(self.errors)}")
        if total_duration:
            logger.info(f"  ⏱️  Total Duration: {duration_str}")
        
        # Skipped items details
        if self.skipped:
            logger.info(f"\n⏭️  Skipped Items ({len(self.skipped)}):")
            for i, item in enumerate(self.skipped[:20], start=1):
                logger.info(f"  {i}. {item}")
            if len(self.skipped) > 20:
                logger.info(f"  ... and {len(self.skipped) - 20} more")
        
        # Errors details
        if self.errors:
            logger.error(f"\n❌ Errors ({len(self.errors)}):")
            for i, error in enumerate(self.errors, start=1):
                logger.error(f"  {i}. {error}")
        
        # Manual actions needed (yellow – things user may need to do)
        if self.manual_actions_needed:
            logger.warning(f"\n⚠️  Manual action required ({len(self.manual_actions_needed)}):")
            for i, action in enumerate(self.manual_actions_needed, start=1):
                logger.warning(f"  {i}. {action}")
            logger.warning("  → Please review the items above and complete them manually in the UI.")
        
        # Warnings
        if self.warnings:
            logger.warning(f"\n⚠️  Warnings ({len(self.warnings)}):")
            for i, warning in enumerate(self.warnings[:10], start=1):
                logger.warning(f"  {i}. {warning}")
            if len(self.warnings) > 10:
                logger.warning(f"  ... and {len(self.warnings) - 10} more warnings")
        
        # Created Items Summary (for transparency)
        logger.info("\n📦 Created items:")
        created_counts = {}
        idx = 0
        for category, items in self.created_items.items():
            if items:
                idx += 1
                label = category.replace('_', ' ').title()
                if isinstance(items, list):
                    count = len(items)
                    created_counts[category] = count
                    logger.info(f"  {idx}. {label}: {count} item(s)")
                elif isinstance(items, dict) and items:
                    if category == 'system_settings':
                        created_counts[category] = 1
                        logger.info(f"  {idx}. System Settings: Configured")
                        if 'system_interface' in items and 'logos' in items['system_interface']:
                            logos = items['system_interface']['logos']
                            if isinstance(logos, dict):
                                logger.info(f"      – Logos/Favicon: {', '.join(logos.keys())}")
                            elif isinstance(logos, list) and logos:
                                logger.info(f"      – Logos/Favicon: {len(logos)} uploaded")
                    else:
                        created_counts[category] = 1
                        logger.info(f"  {idx}. {label}: Configured")
                elif items is not None:
                    created_counts[category] = 1
                    logger.info(f"  {idx}. {label}: Uploaded/Configured")
        if not created_counts and not any(isinstance(v, dict) and v for v in self.created_items.values()):
            logger.info("  (none – all may have been skipped)")
        
        # Remind about disabling streams if any cameras were created (easy to miss otherwise)
        cameras_list = self.created_items.get('cameras') or []
        if cameras_list:
            logger.warning("")
            logger.warning("⚠️  IMPORTANT – DO NOT SKIP:")
            logger.warning("   %d camera(s) are left LIVE and CONNECTED. Disable these streams before running the", len(cameras_list))
            logger.warning("   upgrade so alerts reach a steady state you can validate against afterwards.")
            logger.warning("")
        
        # Final status
        logger.info("\n" + "=" * 80)
        if failed == 0 and not self.manual_actions_needed:
            logger.info("✅ AUTOMATION COMPLETED SUCCESSFULLY")
        elif failed > 0:
            logger.error(f"❌ AUTOMATION COMPLETED WITH {failed} FAILED STEP(S)")
            logger.warning("  → Please review the errors above and take manual action if needed.")
        else:
            logger.warning("⚠️  AUTOMATION COMPLETED WITH WARNINGS")
            logger.warning("  → Please review the warnings and manual actions above.")
        logger.info("=" * 80 + "\n")
    
    def export_to_file(self, output_path=None, format='yaml', name_prefix=None):
        """
        Export created items to a file for post-upgrade validation.
        
        Args:
            output_path: Path to output file (if None, auto-generates filename)
            format: 'yaml' or 'json'
            name_prefix: Optional name prefix. When provided, filename is {name}_data_inserted_{timestamp}.{format}
        
        Returns:
            Path to exported file
        """
        if output_path is None:
            timestamp = now_israel().strftime('%Y-%m-%d_%H-%M-%S')
            if name_prefix:
                # Sanitize: alphanumeric and underscore only
                safe = "".join(c for c in name_prefix if c.isalnum() or c == "_").strip("_") or "data"
                filename = f"{safe}_data_inserted_{timestamp}.{format}"
            else:
                filename = f"onwatch_data_inserted_{timestamp}.{format}"
            exports_dir = Path(EXPORTS_DIR)
            exports_dir.mkdir(exist_ok=True)
            output_path = exports_dir / filename

        output_path = Path(output_path)
        # Ensure parent dir exists (covers callers that pass an explicit path under exports/)
        if output_path.parent and str(output_path.parent) not in ("", "."):
            output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Prepare export data
        export_data = {
            'metadata': {
                'generated_at': self.run_timestamp or now_israel().strftime('%Y-%m-%d %H:%M:%S'),
                'onwatch_ip': self.onwatch_ip or 'unknown',
                'onwatch_version': getattr(self, 'onwatch_version', None),  # Version if available
                'total_duration': self.format_duration(self.get_total_duration()),
                'run_status': {
                    'total_steps': len(self.steps),
                    'successful_steps': sum(1 for s in self.steps.values() if s['status'] == 'success'),
                    'failed_steps': sum(1 for s in self.steps.values() if s['status'] == 'failed'),
                    'skipped_steps': sum(1 for s in self.steps.values() if s['status'] == 'skipped'),  # steps not run (e.g. all items already existed)
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
    
    def checkpoint_to_file(self, format='yaml', name_prefix=None):
        """
        Save current state to checkpoint file (overwrites). Use after each step so
        partial progress is saved if run gets stuck.
        
        Returns:
            Path to checkpoint file, or None on failure
        """
        if name_prefix:
            safe = "".join(c for c in name_prefix if c.isalnum() or c == "_").strip("_") or "data"
            filename = f"{safe}_data_inserted_checkpoint.{format}"
        else:
            filename = f"onwatch_data_inserted_checkpoint.{format}"
        exports_dir = Path(EXPORTS_DIR)
        exports_dir.mkdir(exist_ok=True)
        return self.export_to_file(output_path=exports_dir / filename, format=format, name_prefix=name_prefix)
    
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
                        logo_entry = {
                            'source_file': logo_item.get('source_file', ''),
                            'path': logo_item.get('path', '')  # Config path (relative)
                        }
                        # Include registration status if available (for tracking failures)
                        if 'registered' in logo_item:
                            logo_entry['registered'] = logo_item['registered']
                        # Include error message if registration failed
                        if 'error' in logo_item:
                            logo_entry['error'] = logo_item['error']
                        logos_dict[logo_type] = logo_entry
                if logos_dict:
                    cleaned_interface['logos'] = logos_dict
            cleaned['system_interface'] = cleaned_interface
        return cleaned


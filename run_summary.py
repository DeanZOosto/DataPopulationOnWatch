#!/usr/bin/env python3
"""
Run summary tracking and reporting for OnWatch automation.

Tracks step execution results, errors, warnings, and skipped items,
then generates a comprehensive summary report.
"""
import logging

logger = logging.getLogger(__name__)


class RunSummary:
    """Track and report automation run summary."""
    
    def __init__(self):
        self.steps = {}
        self.errors = []
        self.warnings = []
        self.skipped = []
        self.manual_actions_needed = []
    
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
    
    def print_summary(self):
        """Print a comprehensive summary of the run."""
        logger.info("\n" + "=" * 80)
        logger.info("AUTOMATION RUN SUMMARY")
        logger.info("=" * 80)
        
        # Step-by-step status
        logger.info("\n📋 Step Status:")
        for step_num in sorted(self.steps.keys()):
            step = self.steps[step_num]
            status_icon = {
                'success': '✅',
                'failed': '❌',
                'skipped': '⏭️',
                'partial': '⚠️'
            }.get(step['status'], '❓')
            
            logger.info(f"  {status_icon} Step {step_num}: {step['name']} - {step['status'].upper()}")
            if step['message']:
                logger.info(f"     {step['message']}")
        
        # Statistics
        total_steps = len(self.steps)
        successful = sum(1 for s in self.steps.values() if s['status'] == 'success')
        failed = sum(1 for s in self.steps.values() if s['status'] == 'failed')
        skipped_steps = sum(1 for s in self.steps.values() if s['status'] == 'skipped')
        
        logger.info(f"\n📊 Statistics:")
        logger.info(f"  Total Steps: {total_steps}")
        logger.info(f"  ✅ Successful: {successful}")
        logger.info(f"  ❌ Failed: {failed}")
        logger.info(f"  ⏭️  Skipped Steps: {skipped_steps}")
        logger.info(f"  ⏭️  Skipped Items: {len(self.skipped)}")
        logger.info(f"  ❌ Errors: {len(self.errors)}")
        
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


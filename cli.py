"""
CLI entry point for OnWatch Data Population Automation.
Parses arguments, configures logging, and dispatches to automation steps or full run.
"""
import argparse
import asyncio
import logging
import sys

from config_manager import ConfigManager
from main import (
    AUTOMATION_STEPS,
    STEP_LIST,
    OnWatchAutomation,
    _clean_excepthook,
    _original_excepthook,
    _preview_dataset,
    logger,
)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='OnWatch Data Population Automation',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Validate configuration
  python3 main.py --validate

  # Run full automation
  python3 main.py

  # Run with custom config file
  python3 main.py --config my-config.yaml

  # Run specific step
  python3 main.py --step populate-watchlist

  # Dry-run mode (validate and show what would be executed)
  python3 main.py --dry-run

  # Preview dataset that will be populated
  python3 main.py --preview-data

  # Verbose logging
  python3 main.py --verbose

  # Quiet mode (errors only)
  python3 main.py --quiet
        """
    )
    parser.add_argument(
        '--config',
        type=str,
        default='config.yaml',
        help='Path to configuration YAML file (default: config.yaml)'
    )
    parser.add_argument(
        '--step',
        type=str,
        choices=[step_id for step_id, _, _ in STEP_LIST],
        help='Run only a specific step. Use --list-steps to see descriptions.'
    )
    parser.add_argument(
        '--validate',
        action='store_true',
        help='Validate configuration file and exit (does not run automation)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Validate config and show what would be executed without making API calls'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging (DEBUG level)'
    )
    parser.add_argument(
        '--quiet',
        action='store_true',
        help='Enable quiet mode (ERROR level only)'
    )
    parser.add_argument(
        '--log-file',
        type=str,
        help='Save logs to file (e.g., --log-file automation.log)'
    )
    parser.add_argument(
        '--version',
        action='version',
        version='OnWatch Data Population Automation v1.0'
    )
    parser.add_argument(
        '--list-steps',
        action='store_true',
        help='List all available automation steps and exit'
    )
    parser.add_argument(
        '--set-ip',
        type=str,
        metavar='IP_ADDRESS',
        help='Update all IP addresses in config.yaml to the specified IP address. Updates onwatch, ssh, and rancher IPs automatically. Creates a backup of the original config file.'
    )
    parser.add_argument(
        '--set-version',
        type=str,
        metavar='VERSION',
        choices=['2.6', '2.8'],
        help='Update OnWatch version in config.yaml (2.6 or 2.8). Automatically updates Rancher password based on version (2.6="admin", 2.8="administrator"). Can be used with --set-ip or independently.'
    )
    parser.add_argument(
        '--preview-data',
        action='store_true',
        help='Preview the dataset that will be populated (shows all configured data) and exit'
    )

    args = parser.parse_args()

    # Handle list-steps
    if args.list_steps:
        print("\nAvailable Automation Steps:")
        print("=" * 70)
        for step_id, step_name, description in STEP_LIST:
            print(f"  --step {step_id:24s}  {step_name}")
            print(f"  {'':26s}  {description}\n")
        sys.exit(0)

    # Handle preview-data
    if args.preview_data:
        _preview_dataset(args.config)
        sys.exit(0)

    # Configure logging
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        sys.excepthook = _original_excepthook
    elif args.quiet:
        logging.getLogger().setLevel(logging.ERROR)
        sys.excepthook = _clean_excepthook
    else:
        sys.excepthook = _clean_excepthook

    if args.log_file:
        file_handler = logging.FileHandler(args.log_file)
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
        logging.getLogger().addHandler(file_handler)

    # Handle --set-ip
    if args.set_ip:
        config_manager = ConfigManager(config_path=args.config)
        success, message = config_manager.update_ip_address(args.set_ip, backup=True)
        if success:
            logger.info(f"✓ {message}")
            logger.info(f"✓ Configuration file updated: {args.config}")
            logger.info("✓ You can now run the automation with: python3 main.py")
            if args.set_version:
                success2, message2 = config_manager.update_version(args.set_version, backup=False)
                if success2:
                    logger.info(f"✓ {message2}")
                else:
                    logger.warning(f"⚠️  {message2}")
        else:
            logger.error(f"❌ {message}")
            sys.exit(1)
        sys.exit(0)

    # Handle --set-version
    if args.set_version:
        config_manager = ConfigManager(config_path=args.config)
        success, message = config_manager.update_version(args.set_version, backup=True)
        if success:
            logger.info(f"✓ {message}")
            logger.info(f"✓ Configuration file updated: {args.config}")
            logger.info("✓ You can now run the automation with: python3 main.py")
        else:
            logger.error(f"❌ {message}")
            sys.exit(1)
        sys.exit(0)

    automation = OnWatchAutomation(config_path=args.config)

    # Handle step execution
    step_mapping = {
        step_id: (method_name, is_async)
        for (step_id, _, _), (_, _, method_name, is_async, _, _, _) in zip(STEP_LIST, AUTOMATION_STEPS)
    }
    if args.step:
        if args.step not in step_mapping:
            logger.error(f"Invalid step: {args.step}. Use --list-steps to see available steps.")
            sys.exit(1)
        method_name, is_async = step_mapping[args.step]
        if args.step in ['set-kv-params', 'populate-watchlist']:
            automation.initialize_api_client()
        fn = getattr(automation, method_name)
        if is_async:
            asyncio.run(fn())
        else:
            fn()
        return

    # Handle validate-only mode
    if args.validate:
        is_valid, errors = automation.validate_config(verbose=True)
        if is_valid:
            logger.info("\n✓ Configuration is valid")
            sys.exit(0)
        else:
            logger.error(f"\n❌ Configuration validation failed with {len(errors)} error(s)")
            sys.exit(1)

    # Handle dry-run mode
    if args.dry_run:
        is_valid, errors = automation.validate_config(verbose=True)
        if not is_valid:
            logger.error(f"\n❌ Configuration validation failed. Cannot proceed with dry-run.")
            sys.exit(1)
        logger.info("\n" + "=" * 80)
        logger.info("DRY-RUN MODE: Showing what would be executed")
        logger.info("=" * 80)
        logger.info("\nThe following steps would be executed:")
        for i, (_, step_name, _) in enumerate(STEP_LIST, 1):
            logger.info(f"  {i}. {step_name}")
        logger.info("\n✓ Dry-run completed - no actual changes were made")
        sys.exit(0)

    # Run full automation
    try:
        asyncio.run(automation.run())
    except Exception as e:
        error_message = str(e)
        logger.error(f"\n❌ FATAL ERROR: {error_message}")
        logger.error("Automation stopped due to fatal error")
        root_logger = logging.getLogger()
        if root_logger.level <= logging.DEBUG:
            logger.debug("\nFull traceback (verbose mode):")
            logger.debug("", exc_info=True)
        sys.exit(1)

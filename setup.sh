#!/bin/bash
# Quick setup script for OnWatch automation

echo "Setting up OnWatch Data Population Automation..."
echo ""

# Check Python version
python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "Python version: $python_version"

# Install dependencies
echo "Installing Python dependencies..."
pip3 install -r requirements.txt

# Note: Playwright is only needed for Rancher automation (Step 10)
# If you're using Rancher automation, install Playwright browsers:
# playwright install chromium

echo ""
echo "Setup complete!"
echo ""
echo "Next steps:"
echo "1. Edit config.yaml with your settings"
echo "2. Run: python3 main.py"
echo ""


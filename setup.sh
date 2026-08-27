#!/bin/bash
set -e

echo "Starting setup..."

# Uncomment this command if `uv` is not installed on your system.
# curl -LsSf https://astral.sh/uv/install.sh | sh

echo "Installing Python dependencies..."
uv add -r requirements.txt
uv sync

echo "Installing Playwright browsers..."
# The main.py script specifically launches Firefox, so we only need to install that browser
# U can also download chrome or other browsers ...
uv run python -m playwright install firefox

echo "Setup complete! Don't forget to set up your .env file."

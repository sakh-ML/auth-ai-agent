
# Uncomment this command if `uv` is not installed on your system.
# curl -LsSf https://astral.sh/uv/install.sh | sh


uv add -r requirements.txt
uv sync

uv run playwright install


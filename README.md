# Automated Authentication

## Installation

1. If `uv` is not installed on your system, uncomment the installation command in `setup.sh`.

2. Run the setup script:

```bash
./setup.sh
```

## Usage

Before running the application, export the required environment variables:

```bash
export OPENAI_API_KEY="your_openai_api_key"
export TOTP_SECRET="your_totp_secret"
```

Then run the application:

```bash
uv run src/main.py
```

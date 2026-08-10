# Automated Authentication Study Agent

A fully AI-driven browser automation agent designed for controlled user studies. It performs DOM classification, dynamic 2FA generation, and secure local credential management.

## Installation

1. If `uv` is not installed on your system, uncomment the installation command in `setup.sh`.

2. Run the setup script:

```bash
chmod +x setup.sh
./setup.sh
```

## Configuration

The agent uses a `.env` file to manage secrets securely.

Create a `.env` file in the root directory and add your Academic Cloud AI API key:

```env
SAIA_API_KEY="your_saia_api_key_here"
```

## Usage

The application now strictly requires a `--mode` flag to define the agent's behavior for the session. Participants never choose this; it is set by the experimenter.

```bash
uv run python src/main.py --mode <MODE> [--url <START_URL>]
```

### Available Modes
* `A` : **Manual** - Agent observes and learns credentials but never automates actions.
* `B` : **Assisted** - Agent asks the user for permission via a UI overlay before acting.
* `C1`: **Autonomous Slow** - Fully autonomous with human-like typing pacing and visual overlays. Interruptible via the Escape key.
* `C2`: **Autonomous Fast** - Fully autonomous, instant execution with no overlays.

### Examples
Run the agent in Assisted mode on the default onboarding portal (http://localhost:5001/):
```bash
uv run python src/main.py --mode B
```

Run the agent in Autonomous Fast mode with a custom starting URL:
```bash
uv run python src/main.py --mode C2 --url http://127.0.0.1:5002/
```

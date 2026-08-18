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

The application now strictly requires a `--participant_id` and a `--mode` flag to define, respectively, which participant the session belongs to and the agent's behavior for that session. Participants never choose these; they are set by the experimenter.

```bash
uv run python src/main.py --participant_id <ID> --mode <MODE> [--url <START_URL>]
```

* `--participant_id`: Integer ID for the participant running the session. Used to name and separate that participant's log files (see [Logging](#logging) below).
* `--mode`: One of `A`, `B`, `C1`, `C2` (see below).
* `--url`: Optional. Defaults to `http://31.70.108.229/set-password`.

### Available Modes
* `A` : **Manual** - Agent observes and learns credentials but never automates actions.
* `B` : **Assisted** - Agent asks the user for permission via a UI overlay before acting.
* `C1`: **Autonomous Slow** - Fully autonomous with human-like typing pacing and visual overlays. Interruptible via the Escape key.
* `C2`: **Autonomous Fast** - Fully autonomous, instant execution with no overlays.

### Examples
Run the agent for participant 7 in Assisted mode on the default onboarding portal (http://31.70.108.229/set-password):
```bash
uv run python src/main.py --participant_id 7 --mode B
```

Run the agent for participant 12 in Autonomous Fast mode with a custom starting URL:
```bash
uv run python src/main.py --participant_id 12 --mode C2 --url http://127.0.0.1:5002/
```

## Logging

Each session's logs are stored separately by participant and mode. A new log
file is created for every run, so existing logs are never overwritten or
appended to. Logs are written both to the session log file and to the console,
with millisecond-precision timestamps.

```
logs/participant_<ID>/participant_<ID>_<MODE>.log
logs/participant_<ID>/participant_<ID>_<MODE>_2.log   # second run, same participant + mode
logs/participant_<ID>/participant_<ID>_<MODE>_3.log   # third run, and so on
```

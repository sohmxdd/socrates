# Socrates — Live Testing & Video Demo Guide

This guide details how to test Socrates locally on your machine (including Windows PowerShell) and record a high-impact demo video.

---

## 1. Quick Local Setup

### Step 1: Set Your Groq API Key
In PowerShell:
```powershell
$env:GROQ_API_KEY="your_groq_api_key_here"
```
Or set it permanently in your User Environment Variables.

### Step 2: Install Socrates in Editable Mode
```powershell
pip install -e .
```

### Step 3: Source the PowerShell Shell Hook
In your current PowerShell session (or in `$PROFILE`):
```powershell
. .\shell\socrates.ps1
```
*Tip: To find your profile path, type `$PROFILE` in PowerShell. If you want Socrates active in every PowerShell window, add that dot-source line to your profile file.*

---

## 2. Interactive Terminal Testing ("Ragebait Socrates")

### Test In Any Project Directory
Navigate to any directory or create a new test project:
```powershell
mkdir C:\temp\my-test-project
cd C:\temp\my-test-project

# Initialize Socrates with ambient commentary enabled (90% trigger rate)
socrates init --commentary --rate 0.9
```

Now, every command you run in this directory triggers Socrates' ambient observation engine:
```powershell
# 1. Check git status
git status
# -> Next prompt displays:
# Socrates observes: Still checking git status, as if the repository might evolve on its own.

# 2. Simulate a repeated failure (ragebait trigger)
pytest
pytest
pytest
# -> Socrates observes: You have run pytest three times, hoping the same code will magically change. The failure remains, a reminder that miracles are not a debugging strategy.

# 3. Simulate a secret leak (critical intervention in cyan)
$env:AWS_ACCESS_KEY_ID="AKIAIOSFODNN7EXAMPLE"
# -> Next prompt:
# Socrates: An AWS Access Key ID sits plainly in that command...
```

---

## 3. Instant CLI Inspection & Testing

You can also test Socrates directly via CLI without waiting for prompt hooks:

```powershell
# Check current configuration & scope
socrates commentary status

# Test commentary generation for any command
socrates commentary test "git status"
socrates commentary test "pytest" --exit-code 1 --retries 3
socrates commentary test "cargo build" --exit-code 101

# Toggle on/off
socrates commentary off --local
socrates commentary on --rate 1.0 --local
```

---

## 4. Running the Interactive Demo Showcase for Video

For recorded presentations or pitch videos, use the built-in interactive showcase:

```powershell
python scripts\demo.py -i
```

This presents a clean interactive menu covering:
- **[1] Leaked Secret:** Live AWS key detection (local regex evaluation).
- **[2] Forgotten Git Push:** Background daemon unpushed commit sweep.
- **[3] Silent Failure:** Exit code 0 with missing binary artifact.
- **[4] Stuck Process:** Runtime anomaly vs historical baseline.
- **[5] Socratic vs Quiet:** Philosophical contempt vs factual quiet mode.
- **[6] Custom Command Test:** Type any command on the fly.
- **[7] Ambient Commentary:** Live Groq ragebait philosophical observation.
- **[8] Desperate Retry Loop:** Mocking repeated failed commands.
- **[A] Run All Scenarios:** Automated end-to-end presentation sequence.

---

## 5. Suggested 60-Second Video Script

1. **(0:00 - 0:10) The Hook:**
   - Introduce Socrates: *"A passive terminal agent that stays silent until something goes wrong — and occasionally delivers surgical philosophical commentary on your habits."*
2. **(0:10 - 0:25) Ambient Ragebait Commentary:**
   - Run `python scripts\demo.py -i` -> Option 8 (Desperate Retry Loop).
   - Show the amber `Socrates observes:` output dynamically mocking the developer's 3rd consecutive failed test run.
3. **(0:25 - 0:40) Secret Leak Intervention:**
   - Option 1 (Leaked Secret).
   - Show the cyan `Socrates:` immediate alert catching an AWS access key entered in the shell.
4. **(0:40 - 0:55) Project-Local Customization:**
   - Show `socrates init --commentary` in a directory. Show that each workspace can tune Socrates independently.
5. **(0:55 - 1:00) Closing:**
   - Show `socrates status` or `socrates config show`.
   - *"Watches everything. Speaks only when necessary. Keeps your code and your ego in check."*

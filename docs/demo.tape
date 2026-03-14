# NeuroStack Demo — VHS tape
# Pre-requisite: bash docs/demo-setup.sh
#
# Record: ~/go/bin/vhs docs/demo.tape

Output docs/demo.gif
Output docs/demo.webm

Set Shell "bash"
Set FontSize 16
Set Width 1200
Set Height 700
Set Padding 20
Set TypingSpeed 60ms
Set Theme "Catppuccin Mocha"
Set WindowBar Colorful
Set WindowBarSize 40

# Set environment to use the pre-seeded demo vault
Env NEUROSTACK_VAULT_ROOT "/tmp/neurostack-demo-vhs/vault"
Env NEUROSTACK_DB_DIR "/tmp/neurostack-demo-vhs/db"

# Wrap neurostack to suppress stderr warnings (lite mode embedding fallback)
Hide
Type `neurostack() { command neurostack "$@" 2>/dev/null; }`
Enter
Sleep 500ms
Type "clear"
Enter
Sleep 500ms
Show

# --- Scene 1: Stats — show the vault at a glance ---
Sleep 750ms
Type "neurostack stats"
Sleep 1500ms
Enter
Sleep 4500ms

# --- Scene 2: Search — find notes by keyword ---
Enter
Type "neurostack search 'spaced repetition'"
Sleep 1500ms
Enter
Sleep 6s

# --- Scene 3: Graph — explore connections ---
Enter
Type "neurostack graph research/memory-consolidation.md"
Sleep 1500ms
Enter
Sleep 6s

# --- Scene 4: Brief — morning briefing ---
Enter
Type "neurostack brief"
Sleep 1500ms
Enter
Sleep 7500ms

# --- End ---
Sleep 3s

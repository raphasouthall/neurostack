# neurostack record-usage demo
Output docs/screenshots/cli/record-usage.gif

Set Shell "bash"
Set FontSize 16
Set Width 1200
Set Height 700
Set Padding 20
Set TypingSpeed 60ms
Set Theme "Catppuccin Mocha"
Set WindowBar Colorful
Set WindowBarSize 40

Env NEUROSTACK_VAULT_ROOT "/tmp/neurostack-demo-vhs/vault"
Env NEUROSTACK_DB_DIR "/tmp/neurostack-demo-vhs/db"

Hide
Type `neurostack() { command neurostack "$@" 2>/dev/null; }`
Enter
Sleep 500ms
Type "clear"
Enter
Sleep 500ms
Show

Sleep 500ms
Type "neurostack record-usage research/spaced-repetition.md"
Sleep 1500ms
Enter
Sleep 3s

Sleep 2s

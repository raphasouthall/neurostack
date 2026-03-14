# neurostack tiered - E2E blog post demo
Output docs/screenshots/e2e-tiered.gif

Set Shell "bash"
Set FontSize 16
Set Width 1200
Set Height 700
Set Padding 20
Set TypingSpeed 60ms
Set Theme "Catppuccin Mocha"
Set WindowBar Colorful
Set WindowBarSize 40

Env NEUROSTACK_VAULT_ROOT "/tmp/neurostack-e2e-vhs/vault"
Env NEUROSTACK_DB_DIR "/tmp/neurostack-e2e-vhs/db"
Env NEUROSTACK_LLM_MODEL "qwen2.5:3b"
Env NEUROSTACK_LLM_URL "http://localhost:11434"
Env NEUROSTACK_EMBED_URL "http://localhost:11435"

Hide
Type `neurostack() { command neurostack "$@" 2>/dev/null; }`
Enter
Sleep 500ms
Type "clear"
Enter
Sleep 500ms
Show

Sleep 500ms
Type `neurostack tiered "how does sleep help memory" --top-k 3`
Sleep 1500ms
Enter
Sleep 8s

Sleep 2s

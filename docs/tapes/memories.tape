# neurostack memories demo
Output docs/screenshots/cli/memories.gif

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
Type "neurostack memories add 'deployment requires VPN' --type convention"
Sleep 1500ms
Enter
Sleep 3s

Enter
Type "neurostack memories add 'auth token expires in 1h' --type observation"
Sleep 1500ms
Enter
Sleep 3s

Enter
Type "neurostack memories list"
Sleep 1500ms
Enter
Sleep 4s

Enter
Type "neurostack memories search 'deploy'"
Sleep 1500ms
Enter
Sleep 4s

Sleep 2s

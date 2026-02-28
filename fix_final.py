import re

with open('tracker_gui.py', 'r') as f:
    content = f.read()

# Fix the three broken multiline strings

# Pattern 1: settings.\n\n" followed by "Are you sure
content = content.replace(
    '"This will delete all local progress and settings.\n\n"\n            "Are you sure? This cannot be undone!"',
    '"This will delete all local progress and settings. Are you sure? This cannot be undone!"'
)

# Pattern 2: cleared!\nRestart
content = content.replace(
    '"App data cleared!\nRestart the tracker to start fresh."',
    '"App data cleared! Restart the tracker to start fresh."'
)

# Pattern 3: configured.\n\n" followed by "Go to
content = content.replace(
    '"No API key configured.\n\n"\n                "Go to Settings',
    '"No API key configured. Go to Settings'
)

with open('tracker_gui.py', 'w') as f:
    f.write(content)

print('Fixed!')

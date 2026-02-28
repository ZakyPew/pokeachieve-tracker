# Read the file
with open('tracker_gui.py', 'r') as f:
    content = f.read()

# Fix all broken multiline strings - replace actual newlines in strings with \n escape
# The issue is strings like:
# "line1
# 
# line2"

import re

# Pattern to find broken strings: quote, text, newline, newline, quote
# Replace with: quote, text + space + text, quote
pattern = r'"([^"]*)\n\n"([^"]*)"'
replacement = r'"\1\2"'

# Apply multiple times to catch all
for _ in range(5):
    new_content = re.sub(pattern, replacement, content)
    if new_content == content:
        break
    content = new_content

# Also fix the pattern where there's just a newline in the middle
pattern2 = r'"([^"]*)\n\n([^"]*)"'
replacement2 = r'"\1 \2"'
for _ in range(5):
    new_content = re.sub(pattern2, replacement2, content)
    if new_content == content:
        break
    content = new_content

# Write back
with open('tracker_gui.py', 'w') as f:
    f.write(content)

print("Fixed multiline strings!")

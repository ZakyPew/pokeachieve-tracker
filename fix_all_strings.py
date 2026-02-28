# Read the file
with open('tracker_gui.py', 'r') as f:
    lines = f.readlines()

# Find and fix any remaining broken strings
new_lines = []
i = 0
while i < len(lines):
    line = lines[i]
    # Check if this line has an unterminated string
    if '"App data cleared!' in line and not line.strip().endswith('"'):
        # This is a broken string - need to merge with next lines
        # Get the content
        content = line.rstrip()
        i += 1
        while i < len(lines) and not lines[i].strip().endswith('")'):
            content += ' ' + lines[i].strip()
            i += 1
        # Add the last line
        if i < len(lines):
            content += ' ' + lines[i].strip()
            i += 1
        new_lines.append(content + '\n')
    else:
        new_lines.append(line)
        i += 1

# Write back
with open('tracker_gui.py', 'w') as f:
    f.writelines(new_lines)

print("Fixed remaining strings!")

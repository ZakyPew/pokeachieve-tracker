# Read the file
with open('tracker_gui.py', 'r') as f:
    lines = f.readlines()

# We need to merge:
# Line with: "This will delete all local progress and settings.\n
# Empty line
# Line with: "\n
# Line with: "Are you sure? This cannot be undone!",

# Find the pattern and fix it
result = []
i = 0
while i < len(lines):
    line = lines[i]
    
    # Check if this line ends with a period and newline inside a string
    if 'settings.\n' in line and '"' in line:
        # This is the start of a broken multiline string
        # Get the part before the closing quote
        prefix = line.rstrip()
        i += 1
        # Skip empty line
        if i < len(lines) and lines[i].strip() == '"':
            i += 1
        # Get the next part
        if i < len(lines):
            suffix = lines[i].strip()
            # Merge them
            merged = prefix.replace('.\n', '. ') + suffix.lstrip('"') + '\n'
            result.append(merged)
            i += 1
        else:
            result.append(line)
            i += 1
    # Check for the other broken string pattern
    elif 'App data cleared!\n' in line and '"' in line:
        prefix = line.rstrip()
        i += 1
        if i < len(lines):
            suffix = lines[i].strip()
            merged = prefix.replace('!\n', '! ') + suffix.lstrip('"') + '\n'
            result.append(merged)
            i += 1
        else:
            result.append(line)
            i += 1
    else:
        result.append(line)
        i += 1

with open('tracker_gui.py', 'w') as f:
    f.writelines(result)

print("Fixed!")

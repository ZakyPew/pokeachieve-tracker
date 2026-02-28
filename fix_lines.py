# Read the file
with open('tracker_gui.py', 'r') as f:
    lines = f.readlines()

# Fix lines 1622-1624 (indices 1621-1623)
# The string is broken across 3 lines - merge them
broken_start = lines[1621]  # Line 1622 - "This will delete all local progress and settings. \n
broken_mid = lines[1622]    # Line 1623 - just \n
broken_end = lines[1623]    # Line 1624 - "\n

# Replace with single line
fixed_line = '            "This will delete all local progress and settings. Are you sure? This cannot be undone!",\n'

# Remove the broken lines and insert fixed line
new_lines = lines[:1621] + [fixed_line] + lines[1624:]

# Write back
with open('tracker_gui.py', 'w') as f:
    f.writelines(new_lines)

print("Fixed!")

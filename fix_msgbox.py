with open('tracker_gui.py', 'r') as f:
    lines = f.readlines()

# Fix the mess at lines 1651-1653 (indices 1650-1652)
lines[1650] = '            msgbox.showwarning("Not Connected", "No API key configured. Go to Settings → API to add your API key.")\n'
del lines[1651:1654]

with open('tracker_gui.py', 'w') as f:
    f.writelines(lines)

print('Fixed!')

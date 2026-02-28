import re

with open('tracker_gui.py', 'r') as f:
    lines = f.readlines()

# Find and print lines around 1620
for i, line in enumerate(lines[1615:1630], start=1616):
    print(f"{i}: {repr(line)}")

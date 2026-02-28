"""Fix for tracker_gui.py syntax error"""

# Read the file
with open('tracker_gui.py', 'r') as f:
    content = f.read()

# Fix the broken strings in _clear_app_data
old_str = '''msgbox.showinfo("Success", "App data cleared!
Restart the tracker to start fresh.")'''
new_str = '''msgbox.showinfo("Success", "App data cleared! Restart the tracker to start fresh.")'''

content = content.replace(old_str, new_str)

# Write back
with open('tracker_gui.py', 'w') as f:
    f.write(content)

print("Fixed!")

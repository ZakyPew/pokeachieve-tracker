# Fix the API header construction
with open('tracker_gui.py', 'r') as f:
    content = f.read()

# Find and fix the headers initialization
old_headers = '''self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }'''

new_headers = '''self.api_key = api_key.strip() if api_key else ""
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }'''

content = content.replace(old_headers, new_headers)

with open('tracker_gui.py', 'w') as f:
    f.write(content)

print('Fixed API key header!')

# Fix the _sync_with_server method to use correct endpoint and _request method
with open('tracker_gui.py', 'r') as f:
    content = f.read()

# Fix the sync method to use _request instead of session.get
old_sync = '''            # Fetch achievements from server
            response = self.api.session.get(f"{self.api.base_url}/achievements")'''

new_sync = '''            # Fetch achievements from server
            success, data = self.api._request("GET", "/users/me/achievements")'''

content = content.replace(old_sync, new_sync)

# Also fix the response handling
old_response = '''            if response.status_code == 200:
                server_achievements = response.json()
                
                # Update local tracker
                for ach in server_achievements:
                    if ach.get('unlocked'):
                        self.tracker.unlocked_achievements.add(ach['id'])
                
                # Save to local file
                self._save_progress()
                
                msgbox.showinfo("Sync Complete", 
                    f"Synced {len(server_achievements)} achievements from server!")'''

new_response = '''            if success:
                server_achievements = data if isinstance(data, list) else data.get('achievements', [])
                
                # Update local tracker
                for ach in server_achievements:
                    if isinstance(ach, dict) and ach.get('unlocked'):
                        self.tracker.unlocked_achievements.add(ach.get('id') or ach.get('achievement_id'))
                
                # Save to local file
                self._save_progress()
                
                msgbox.showinfo("Sync Complete", 
                    f"Synced {len(server_achievements)} achievements from server!")'''

content = content.replace(old_response, new_response)

# Also fix the error handling
old_error = '''            else:
                msgbox.showerror("Sync Failed", f"Server error: {response.status_code}")'''

new_error = '''            else:
                msgbox.showerror("Sync Failed", f"Server error: {data.get('detail', 'Unknown error')}")'''

content = content.replace(old_error, new_error)

with open('tracker_gui.py', 'w') as f:
    f.write(content)

print('Fixed _sync_with_server method!')

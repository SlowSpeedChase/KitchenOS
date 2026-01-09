"""Apple Reminders integration via AppleScript."""

import subprocess


def add_to_reminders(items, list_name="Shopping"):
    """Add items to Apple Reminders list.

    Args:
        items: List of formatted ingredient strings
        list_name: Name of Reminders list
    """
    for item in items:
        # Escape quotes for AppleScript
        escaped = item.replace('"', '\\"')

        script = f'''
        tell application "Reminders"
            tell list "{list_name}"
                make new reminder with properties {{name:"{escaped}"}}
            end tell
        end tell
        '''
        subprocess.run(['osascript', '-e', script], check=True)


def clear_reminders_list(list_name="Shopping"):
    """Remove all items from a Reminders list."""
    script = f'''
    tell application "Reminders"
        tell list "{list_name}"
            delete every reminder
        end tell
    end tell
    '''
    subprocess.run(['osascript', '-e', script], check=True)


def create_reminders_list(list_name="Shopping"):
    """Create a Reminders list if it doesn't exist."""
    script = f'''
    tell application "Reminders"
        if not (exists list "{list_name}") then
            make new list with properties {{name:"{list_name}"}}
        end if
    end tell
    '''
    subprocess.run(['osascript', '-e', script], check=True)

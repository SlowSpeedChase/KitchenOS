# Creating an Automator App for YouTube Video Info

Since I can't directly create Automator applications programmatically, here are the steps to create a drag-and-drop app:

## Method 1: Automator Application

1. **Open Automator** (Applications > Automator)
2. **Choose "Application"** as the document type
3. **Add "Run AppleScript" action** from the library
4. **Replace the default script** with this code:

```applescript
on run {input, parameters}
    try
        -- Get the first item if multiple items were dropped
        if (count of input) > 0 then
            set userInput to item 1 of input as string
        else
            -- If no input, prompt user
            set userInput to text returned of (display dialog "Enter YouTube URL or Video ID:" default answer "" with title "YouTube Video Info Fetcher")
        end if
        
        if userInput is "" then
            return input
        end if
        
        -- Set the paths
        set scriptPath to "/Users/chaseeasterling/Documents/GitHub/yt_vid_info/main.py"
        set pythonPath to "/Users/chaseeasterling/Documents/GitHub/yt_vid_info/.venv/bin/python"
        
        -- Create and run the command
        set shellCommand to quoted form of pythonPath & " " & quoted form of scriptPath & " " & quoted form of userInput
        set commandResult to do shell script shellCommand
        
        -- Display results
        display dialog commandResult with title "YouTube Video Info" buttons {"Copy to Clipboard", "OK"} default button "OK"
        
        if button returned of result is "Copy to Clipboard" then
            set the clipboard to commandResult
        end if
        
    on error errorMessage
        display dialog "Error: " & errorMessage with title "Error" buttons {"OK"} default button "OK"
    end try
    
    return input
end run
```

5. **Save as "YouTube Info Fetcher.app"** on your Desktop
6. **Test it** by double-clicking or dragging YouTube URLs to it

## Method 2: Quick Script Menu Access

1. **Open Script Editor** (Applications > Utilities > Script Editor)
2. **Paste the advanced AppleScript** (from run_youtube_info_advanced.applescript)
3. **Save as "YouTube Info Fetcher"** in `~/Library/Scripts/`
4. **Enable Script Menu** in Script Editor preferences
5. **Access from menu bar** 📜 icon

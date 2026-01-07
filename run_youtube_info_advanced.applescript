-- Advanced YouTube Video Info Fetcher AppleScript
-- Features: Clipboard detection, better UI, save to file option

on run
    try
        -- Try to get URL from clipboard if it looks like a YouTube URL
        set clipboardContent to ""
        try
            set clipboardContent to (the clipboard as string)
        end try
        
        set defaultInput to ""
        if clipboardContent contains "youtube.com" or clipboardContent contains "youtu.be" then
            set defaultInput to clipboardContent
        end if
        
        -- Prompt user for YouTube URL or video ID
        set dialogResult to display dialog "Enter YouTube URL or Video ID:" & return & return & "💡 Tip: If you have a YouTube URL in your clipboard, it will be pre-filled." default answer defaultInput with title "YouTube Video Info Fetcher" buttons {"Cancel", "Process Video"} default button "Process Video"
        
        set userInput to text returned of dialogResult
        
        if userInput is "" then
            display dialog "No input provided. Exiting." with title "Error" buttons {"OK"} default button "OK"
            return
        end if
        
        -- Set the paths
        set scriptPath to "/Users/chaseeasterling/Documents/Documents - Chase's MacBook Air - 1/GitHub/YT-Vid-Recipie/main.py"
        set pythonPath to "/Users/chaseeasterling/Documents/Documents - Chase's MacBook Air - 1/GitHub/YT-Vid-Recipie/.venv/bin/python"
        
        -- Create the command
        set shellCommand to quoted form of pythonPath & " " & quoted form of scriptPath & " " & quoted form of userInput
        
        -- Show progress with spinning indicator
        display dialog "🔄 Fetching video information..." & return & return & "This may take a few seconds..." with title "Processing" buttons {"Cancel"} giving up after 3
        
        -- Run the command and capture output
        set commandResult to do shell script shellCommand
        
        -- Extract video ID for filename
        set videoId to extractVideoId(userInput)
        
        -- Display options dialog
        set optionsResult to display dialog "✅ Video information retrieved successfully!" & return & return & "What would you like to do?" with title "Success!" buttons {"Just View", "Save to File", "Copy & View"} default button "Copy & View"
        
        set userChoice to button returned of optionsResult
        
        if userChoice is "Copy & View" or userChoice is "Just View" then
            if userChoice is "Copy & View" then
                set the clipboard to commandResult
                display notification "Results copied to clipboard!" with title "YouTube Info"
            end if
            
            -- Show results in a dialog (truncated if too long)
            set resultPreview to commandResult
            if length of commandResult > 1000 then
                set resultPreview to (text 1 thru 1000 of commandResult) & "..." & return & return & "📝 Full results " & (if userChoice is "Copy & View" then "copied to clipboard" else "available in saved file")
            end if
            
            display dialog resultPreview with title "YouTube Video Info - " & videoId buttons {"OK"} default button "OK"
        end if
        
        if userChoice is "Save to File" then
            -- Save to file
            set fileName to "youtube_info_" & videoId & "_" & getCurrentDateTime() & ".txt"
            set filePath to (path to desktop as string) & fileName
            
            try
                set fileRef to open for access file filePath with write permission
                write commandResult to fileRef
                close access fileRef
                
                display dialog "✅ Results saved to:" & return & fileName & return & return & "Location: Desktop" with title "File Saved" buttons {"Open File", "OK"} default button "OK"
                
                if button returned of result is "Open File" then
                    tell application "Finder"
                        open file filePath
                    end tell
                end if
                
            on error
                display dialog "❌ Error saving file to Desktop" with title "Error" buttons {"OK"} default button "OK"
            end try
        end if
        
    on error errorMessage number errorNumber
        if errorNumber is -128 then
            -- User cancelled
            return
        else
            display dialog "❌ Error: " & errorMessage & return & return & "Make sure:" & return & "• Python environment is set up correctly" & return & "• Valid YouTube URL/ID provided" & return & "• Internet connection is available" with title "Error" buttons {"OK"} default button "OK"
        end if
    end try
end run

-- Helper function to extract video ID from URL or return original if already an ID
on extractVideoId(input)
    try
        if input contains "v=" then
            set AppleScript's text item delimiters to "v="
            set videoId to text item 2 of input
            set AppleScript's text item delimiters to "&"
            set videoId to text item 1 of videoId
            set AppleScript's text item delimiters to ""
            return videoId
        else
            return input
        end if
    on error
        return "unknown"
    end try
end extractVideoId

-- Helper function to get current date/time for filename
on getCurrentDateTime()
    set currentDate to current date
    set dateString to year of currentDate as string
    set dateString to dateString & "-" & (month of currentDate as integer) as string
    set dateString to dateString & "-" & day of currentDate as string
    set dateString to dateString & "_" & time string of currentDate
    -- Replace colons with dashes for filename compatibility
    set AppleScript's text item delimiters to ":"
    set dateItems to text items of dateString
    set AppleScript's text item delimiters to "-"
    set dateString to dateItems as string
    set AppleScript's text item delimiters to ""
    return dateString
end getCurrentDateTime

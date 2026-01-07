-- YouTube to Keyboard Maestro Integration Script
-- This script fetches YouTube info and triggers Keyboard Maestro workflows

on run
    try
        -- Get clipboard content for YouTube URL detection
        set clipboardContent to ""
        try
            set clipboardContent to (the clipboard as string)
        end try
        
        set defaultInput to ""
        if clipboardContent contains "youtube.com" or clipboardContent contains "youtu.be" then
            set defaultInput to clipboardContent
        end if
        
        -- Prompt for YouTube URL/ID
        set dialogResult to display dialog "Enter YouTube URL or Video ID:" & return & return & "💡 Tip: Results will be processed and sent to your chosen app via Keyboard Maestro." default answer defaultInput with title "YouTube → App Integration" buttons {"Cancel", "Process & Send"} default button "Process & Send"
        
        set userInput to text returned of dialogResult
        
        if userInput is "" then
            display dialog "No input provided. Exiting." with title "Error" buttons {"OK"} default button "OK"
            return
        end if
        
        -- Set paths
        set scriptPath to "/Users/chaseeasterling/Documents/Documents - Chase's MacBook Air - 1/GitHub/YT-Vid-Recipie/main.py"
        set pythonPath to "/Users/chaseeasterling/Documents/Documents - Chase's MacBook Air - 1/GitHub/YT-Vid-Recipie/.venv/bin/python"
        
        -- Show processing dialog
        display dialog "🔄 Fetching video information..." & return & return & "Will automatically send to your app when complete." with title "Processing" buttons {"Cancel"} giving up after 2
        
        -- Run the Python script
        set shellCommand to quoted form of pythonPath & " " & quoted form of scriptPath & " " & quoted form of userInput
        set commandResult to do shell script shellCommand
        
        -- Extract video ID and create formatted output
        set videoId to extractVideoId(userInput)
        set currentDateTime to getCurrentDateTime()
        
        -- Create formatted output with metadata
        set formattedOutput to "=== YOUTUBE VIDEO INFO ===" & return & return
        set formattedOutput to formattedOutput & "Video ID: " & videoId & return
        set formattedOutput to formattedOutput & "Processed: " & currentDateTime & return
        set formattedOutput to formattedOutput & "Source URL: " & userInput & return
        set formattedOutput to formattedOutput & return & commandResult
        
        -- Choose target application workflow
        set appChoice to display dialog "✅ Video info retrieved!" & return & return & "Choose target application:" with title "Send to App" buttons {"ChatGPT/Claude", "Notes App", "Custom KM Macro"} default button "ChatGPT/Claude"
        
        set targetApp to button returned of appChoice
        
        -- Store in Keyboard Maestro named clipboard
        do shell script "osascript -e 'tell application \"Keyboard Maestro Engine\" to setvariable \"YouTubeVideoInfo\" to " & quoted form of formattedOutput & "'"
        
        -- Store metadata in separate variables
        do shell script "osascript -e 'tell application \"Keyboard Maestro Engine\" to setvariable \"YouTubeVideoID\" to " & quoted form of videoId & "'"
        do shell script "osascript -e 'tell application \"Keyboard Maestro Engine\" to setvariable \"YouTubeSourceURL\" to " & quoted form of userInput & "'"
        
        -- Trigger appropriate Keyboard Maestro macro based on choice
        if targetApp is "ChatGPT/Claude" then
            triggerKMMacro("YouTube-to-ChatGPT")
        else if targetApp is "Notes App" then
            triggerKMMacro("YouTube-to-Notes")
        else if targetApp is "Custom KM Macro" then
            -- Prompt for custom macro name
            set customMacro to text returned of (display dialog "Enter Keyboard Maestro macro name:" default answer "YouTube-to-Custom" with title "Custom Macro")
            triggerKMMacro(customMacro)
        end if
        
        -- Show success message
        display dialog "🚀 Content sent to " & targetApp & "!" & return & return & "The Keyboard Maestro macro should now be running." with title "Success" buttons {"OK"} default button "OK"
        
    on error errorMessage number errorNumber
        if errorNumber is -128 then
            return -- User cancelled
        else
            display dialog "❌ Error: " & errorMessage & return & return & "Make sure:" & return & "• Keyboard Maestro is running" & return & "• Python environment is set up" & return & "• Valid YouTube URL provided" with title "Error" buttons {"OK"} default button "OK"
        end if
    end try
end run

-- Trigger Keyboard Maestro macro
on triggerKMMacro(macroName)
    try
        do shell script "osascript -e 'tell application \"Keyboard Maestro Engine\" to do script \"" & macroName & "\"'"
    on error
        display dialog "⚠️ Could not trigger Keyboard Maestro macro: " & macroName & return & return & "Make sure:" & return & "• Keyboard Maestro is running" & return & "• Macro exists and is enabled" with title "Macro Error" buttons {"OK"} default button "OK"
    end try
end triggerKMMacro

-- Extract video ID from URL
on extractVideoId(input)
    try
        if input contains "v=" then
            set AppleScript's text item delimiters to "v="
            set videoId to text item 2 of input
            set AppleScript's text item delimiters to "&"
            set videoId to text item 1 of videoId
            set AppleScript's text item delimiters to ""
            return videoId
        else if input contains "youtu.be/" then
            set AppleScript's text item delimiters to "youtu.be/"
            set videoId to text item 2 of input
            set AppleScript's text item delimiters to "?"
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

-- Get formatted current date/time
on getCurrentDateTime()
    set currentDate to current date
    return (currentDate as string)
end getCurrentDateTime

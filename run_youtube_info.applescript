-- YouTube Video Info Fetcher AppleScript
-- This script prompts for a YouTube URL/ID and runs the Python script

on run
	try
		-- Prompt user for YouTube URL or video ID
		set userInput to text returned of (display dialog "Enter YouTube URL or Video ID:" default answer "" with title "YouTube Video Info Fetcher")
		
		if userInput is "" then
			display dialog "No input provided. Exiting." with title "Error" buttons {"OK"} default button "OK"
			return
		end if
		
		-- Set the paths
		set scriptPath to "/Users/chaseeasterling/Documents/Documents - Chase's MacBook Air - 1/GitHub/YT-Vid-Recipie/main.py"
		set pythonPath to "/Users/chaseeasterling/Documents/Documents - Chase's MacBook Air - 1/GitHub/YT-Vid-Recipie/.venv/bin/python"
		
		-- Create the command
		set shellCommand to quoted form of pythonPath & " " & quoted form of scriptPath & " " & quoted form of userInput
		
		-- Show progress dialog
		display dialog "Fetching video information..." with title "Processing" buttons {"Cancel"} giving up after 2
		
		-- Run the command and capture output
		set commandResult to do shell script shellCommand
		
		-- Display the result in a scrollable text window
		display dialog commandResult with title "YouTube Video Info" buttons {"Copy to Clipboard", "OK"} default button "OK"
		
		-- If user clicked "Copy to Clipboard"
		if button returned of result is "Copy to Clipboard" then
			set the clipboard to commandResult
			display dialog "Results copied to clipboard!" with title "Success" buttons {"OK"} default button "OK"
		end if
		
	on error errorMessage number errorNumber
		if errorNumber is -128 then
			-- User cancelled
			return
		else
			display dialog "Error: " & errorMessage with title "Error" buttons {"OK"} default button "OK"
		end if
	end try
end run

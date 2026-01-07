-- Test Keyboard Maestro Integration
-- Simple script to verify KM connection works

on run
    try
        -- Test 1: Check if Keyboard Maestro Engine is running
        tell application "System Events"
            set kmRunning to (name of processes) contains "Keyboard Maestro Engine"
        end tell
        
        if not kmRunning then
            display dialog "❌ Keyboard Maestro Engine is not running!" & return & return & "Please start Keyboard Maestro and try again." with title "KM Not Running" buttons {"OK"} default button "OK"
            return
        end if
        
        display dialog "✅ Keyboard Maestro Engine is running!" & return & return & "Testing variable storage and macro triggering..." with title "Testing KM Integration" buttons {"Continue", "Cancel"} default button "Continue"
        
        -- Test 2: Set a test variable
        set testContent to "This is a test message from AppleScript at " & (current date as string)
        
        do shell script "osascript -e 'tell application \"Keyboard Maestro Engine\" to setvariable \"TestVariable\" to " & quoted form of testContent & "'"
        
        display dialog "✅ Variable set successfully!" & return & return & "Variable name: TestVariable" & return & "Content: " & testContent with title "Variable Test" buttons {"Test Macro", "Cancel"} default button "Test Macro"
        
        -- Test 3: Try to trigger a test macro (create this in KM first)
        set macroChoice to display dialog "Choose a test:" & return & return & "1. Test basic macro trigger" & return & "2. Test variable retrieval" & return & "3. Skip macro test" with title "Macro Test" buttons {"Test Trigger", "Test Variable", "Skip"} default button "Test Trigger"
        
        set userChoice to button returned of macroChoice
        
        if userChoice is "Test Trigger" then
            -- Try to trigger a simple test macro
            try
                do shell script "osascript -e 'tell application \"Keyboard Maestro Engine\" to do script \"KM-Test-Basic\"'"
                display dialog "✅ Macro trigger sent!" & return & return & "If you created a 'KM-Test-Basic' macro in Keyboard Maestro, it should have run." with title "Trigger Test" buttons {"OK"} default button "OK"
            on error triggerError
                display dialog "⚠️ Macro trigger failed:" & return & triggerError & return & return & "Create a macro named 'KM-Test-Basic' in Keyboard Maestro to test this feature." with title "Macro Test" buttons {"OK"} default button "OK"
            end try
            
        else if userChoice is "Test Variable" then
            -- Try to retrieve the variable we just set
            try
                set retrievedValue to do shell script "osascript -e 'tell application \"Keyboard Maestro Engine\" to getvariable \"TestVariable\"'"
                display dialog "✅ Variable retrieved successfully!" & return & return & "Retrieved: " & retrievedValue with title "Variable Retrieval Test" buttons {"OK"} default button "OK"
            on error retrieveError
                display dialog "❌ Variable retrieval failed:" & return & retrieveError with title "Variable Test" buttons {"OK"} default button "OK"
            end try
        end if
        
        -- Test 4: Integration readiness check
        display dialog "🎯 Integration Test Complete!" & return & return & "Next steps:" & return & "1. Create Keyboard Maestro macros from templates" & return & "2. Test with youtube_to_km.applescript" & return & "3. Run your full workflow" with title "Ready for Integration" buttons {"Open Templates", "Done"} default button "Done"
        
        if button returned of result is "Open Templates" then
            -- Open the templates file
            tell application "Finder"
                open file ((path to current user folder as string) & "Documents:Documents - Chase's MacBook Air - 1:GitHub:YT-Vid-Recipie:km_macro_templates.md")
            end tell
        end if
        
    on error errorMessage number errorNumber
        if errorNumber is -128 then
            return -- User cancelled
        else
            display dialog "❌ Error during testing:" & return & errorMessage & return & return & "Make sure Keyboard Maestro is installed and running." with title "Test Error" buttons {"OK"} default button "OK"
        end if
    end try
end run

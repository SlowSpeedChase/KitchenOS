-- KitchenOS URI handler app
-- Catches kitchenos:// URLs (registered via Info.plist) and forwards the
-- full URL to handler.sh, which calls the local API server.
on open location this_URL
	set handlerScript to "/Users/chaseeasterling/Dev/KitchenOS/scripts/kitchenos-uri-handler/handler.sh"
	do shell script quoted form of handlerScript & " " & quoted form of this_URL
end open location

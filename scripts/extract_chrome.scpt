tell application "Google Chrome"
	set activeTab to active tab of front window
	set pageURL to URL of activeTab

	if pageURL contains "twitter.com" or pageURL contains "x.com" then
		set jsCode to "
		(function(){
			var c = {};
			document.cookie.split(';').forEach(function(x){
				var parts = x.trim().split('=');
				c[parts[0]] = parts[1];
			});
			if(!c.ct0 || !c.auth_token){
				return 'ERROR:not_logged_in';
			}
			return 'TOKEN:' + c.ct0 + ':' + c.auth_token;
		})()
		"
		set result to execute activeTab javascript jsCode
		return result
	else
		return "ERROR:not_on_twitter"
	end if
end tell

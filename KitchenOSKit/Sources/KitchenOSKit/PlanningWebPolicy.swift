import Foundation

public enum PlanningWebPolicy {
    public static func sameOrigin(_ url: URL, _ base: URL) -> Bool {
        func port(_ u: URL) -> Int { u.port ?? (u.scheme?.lowercased() == "https" ? 443 : 80) }
        return ["http", "https"].contains(url.scheme?.lowercased() ?? "") &&
            url.scheme?.lowercased() == base.scheme?.lowercased() &&
            url.host?.lowercased() == base.host?.lowercased() && port(url) == port(base) &&
            url.user == nil && url.password == nil
    }
    public static func plannerURL(base: URL, week: String, focusCookID: Int? = nil) -> URL? {
        guard sameOrigin(base, base), WeekDate.date(forWeekID: week) != nil, focusCookID == nil || (focusCookID! > 0 && focusCookID! <= 9_007_199_254_740_991) else { return nil }
        var c = URLComponents(url: base, resolvingAgainstBaseURL: false)
        c?.path = "/meal-planner"
        c?.queryItems = [URLQueryItem(name:"week",value:week),URLQueryItem(name:"view",value:"calendar")]
        if let focusCookID { c?.queryItems?.append(URLQueryItem(name: "focusCookID", value: String(focusCookID))) }
        c?.fragment = nil
        return c?.url
    }
    public static func authorizationScript(base: URL, token: String) -> String? {
        guard sameOrigin(base, base), let resource = Bundle.module.url(forResource:"planning-auth",withExtension:"js"),
              let script = try? String(contentsOf: resource, encoding:.utf8) else { return nil }
        var c = URLComponents(url:base,resolvingAgainstBaseURL:false)!
        c.path="";c.query=nil;c.fragment=nil
        // Browser origins omit default ports.
        if (c.scheme == "http" && c.port == 80) || (c.scheme == "https" && c.port == 443) { c.port=nil }
        guard let origin=c.string, let data=try? JSONEncoder().encode([origin,token]),let args=String(data:data,encoding:.utf8) else { return nil }
        return "(() => {\n" + script + "\ninstallPlanningAuthorization(..." + args + ");\n})();"
    }
}

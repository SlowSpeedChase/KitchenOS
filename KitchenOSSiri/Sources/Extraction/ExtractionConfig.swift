#if os(macOS)
import Foundation

/// Resolves filesystem locations for the local extraction pipeline.
///
/// The old menu-bar app hardcoded `/Users/chaseeasterling/KitchenOS/...`, which
/// is stale (the repo now lives at `~/Dev/KitchenOS`). This reads a single
/// project-root override from UserDefaults and derives everything from it, so a
/// move only needs one Settings change.
enum ExtractionConfig {
    static let projectRootKey = "kitchenos.projectRoot"

    /// Default repo location; overridable in Settings.
    static var defaultProjectRoot: String {
        NSHomeDirectory() + "/Dev/KitchenOS"
    }

    static var projectRoot: String {
        let stored = UserDefaults.standard.string(forKey: projectRootKey)
        let root = (stored?.isEmpty == false ? stored! : defaultProjectRoot)
        return (root as NSString).expandingTildeInPath
    }

    static var pythonPath: String { projectRoot + "/.venv/bin/python" }
    static var extractScriptPath: String { projectRoot + "/extract_recipe.py" }
    static var batchScriptPath: String { projectRoot + "/batch_extract.py" }
}
#endif

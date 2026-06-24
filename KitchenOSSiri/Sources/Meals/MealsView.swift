import SwiftUI
import KitchenOSKit

/// List composite meals; create / edit / delete.
struct MealsView: View {
    @State private var meals: [Meal] = []
    @State private var status = ""
    @State private var isLoading = false
    @State private var editing: Meal?
    @State private var creatingNew = false

    private var client: KitchenOSClient { KitchenOSClient(config: .resolved()) }

    var body: some View {
        List {
            if meals.isEmpty, !isLoading {
                Text(status.isEmpty ? "No meals yet." : status).foregroundStyle(.secondary)
            }
            ForEach(meals) { meal in
                Button { editing = meal } label: {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(meal.name).foregroundStyle(.primary)
                        Text(meal.subRecipes.map(\.recipe).joined(separator: ", "))
                            .font(.caption).foregroundStyle(.secondary).lineLimit(1)
                    }
                }
                .swipeActions {
                    Button(role: .destructive) { Task { await delete(meal) } } label: {
                        Label("Delete", systemImage: "trash")
                    }
                }
            }
        }
        .navigationTitle("Meals")
        .overlay { if isLoading { ProgressView() } }
        .toolbar {
            ToolbarItem { Button { creatingNew = true } label: { Image(systemName: "plus") } }
        }
        .sheet(item: $editing) { meal in
            MealEditor(original: meal) { await save($0, original: meal) }
        }
        .sheet(isPresented: $creatingNew) {
            MealEditor(original: nil) { await save($0, original: nil) }
        }
        .task { await load() }
        .refreshable { await load() }
    }

    private func load() async {
        isLoading = true
        defer { isLoading = false }
        do { meals = try await client.meals() }
        catch { status = "Error: \(error)" }
    }

    private func save(_ meal: Meal, original: Meal?) async {
        do {
            if let original { try await client.updateMeal(name: original.name, meal) }
            else { try await client.createMeal(meal) }
            await load()
        } catch { status = "Save failed: \(error)" }
    }

    private func delete(_ meal: Meal) async {
        do { try await client.deleteMeal(name: meal.name); await load() }
        catch { status = "Delete failed: \(error)" }
    }
}

/// Create or edit a meal. `original == nil` means a new meal.
private struct MealEditor: View {
    let original: Meal?
    let onSave: (Meal) async -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var name: String
    @State private var description: String
    @State private var tagsText: String
    @State private var subRecipes: [SubRecipe]
    @State private var pickingRecipe = false

    init(original: Meal?, onSave: @escaping (Meal) async -> Void) {
        self.original = original
        self.onSave = onSave
        _name = State(initialValue: original?.name ?? "")
        _description = State(initialValue: original?.description ?? "")
        _tagsText = State(initialValue: (original?.tags ?? []).joined(separator: ", "))
        _subRecipes = State(initialValue: original?.subRecipes ?? [])
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Meal") {
                    TextField("Name", text: $name).disabled(original != nil)
                    TextField("Description", text: $description)
                    TextField("Tags (comma-separated)", text: $tagsText)
                }
                Section("Recipes") {
                    ForEach($subRecipes) { $sub in
                        HStack {
                            Text(sub.recipe)
                            Spacer()
                            Stepper("×\(sub.servings)", value: $sub.servings, in: 1...12)
                                .fixedSize()
                        }
                    }
                    .onDelete { subRecipes.remove(atOffsets: $0) }
                    Button("Add recipe") { pickingRecipe = true }
                }
            }
            .navigationTitle(original == nil ? "New Meal" : "Edit Meal")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        Task {
                            await onSave(buildMeal()); dismiss()
                        }
                    }
                    .disabled(name.trimmingCharacters(in: .whitespaces).isEmpty || subRecipes.isEmpty)
                }
            }
            .sheet(isPresented: $pickingRecipe) {
                RecipePickerSheet { picked in
                    if let picked, !subRecipes.contains(where: { $0.recipe == picked }) {
                        subRecipes.append(SubRecipe(recipe: picked))
                    }
                }
            }
        }
        .frame(minWidth: 380, minHeight: 420)
    }

    private func buildMeal() -> Meal {
        let tags = tagsText.split(separator: ",")
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
        return Meal(name: name.trimmingCharacters(in: .whitespaces),
                    description: description, tags: tags, subRecipes: subRecipes)
    }
}

import ast
import unittest

from project_paths import PROJECT_ROOT


class PackageDependencyTests(unittest.TestCase):
    def test_asset_stages_do_not_import_engine_or_disc_packages(self) -> None:
        violations = []
        for package in ("font", "text", "visual", "fmv"):
            for path in sorted((PROJECT_ROOT / package).rglob("*.py")):
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                for node in ast.walk(tree):
                    modules = []
                    if isinstance(node, ast.Import):
                        modules.extend(alias.name for alias in node.names)
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        modules.append(node.module)
                    for module in modules:
                        if module == "engine" or module.startswith("engine."):
                            violations.append((path, node.lineno, module))
                        if module == "disc" or module.startswith("disc."):
                            violations.append((path, node.lineno, module))

        self.assertEqual(violations, [])

    def test_engine_does_not_import_invocation_scoped_roots_directly(self) -> None:
        scoped_roots = {
            "BUILD_ROOT",
            "EXTRACTED_ROOT",
            "FONT_GENERATED_ROOT",
            "TEXT_GENERATED_ROOT",
        }
        allowed = {
            PROJECT_ROOT / "engine/script/context.py",
            PROJECT_ROOT / "engine/script/equipment_ui/reference.py",
        }
        violations = []
        for path in sorted((PROJECT_ROOT / "engine/script").rglob("*.py")):
            if path in allowed:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            project_paths_aliases = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == "project_paths":
                    for alias in node.names:
                        if alias.name == "*" or alias.name in scoped_roots:
                            violations.append((path, node.lineno, alias.name))
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "project_paths":
                            project_paths_aliases.add(alias.asname or alias.name)

            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id in project_paths_aliases
                    and node.attr in scoped_roots
                ):
                    violations.append((path, node.lineno, node.attr))

        self.assertEqual(violations, [])

    def test_engine_does_not_reference_internal_text_source_paths(self) -> None:
        def path_parts(node: ast.AST) -> list[str]:
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                return [
                    part.casefold()
                    for part in node.value.replace("\\", "/").split("/")
                    if part not in {"", "."}
                ]
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
                return path_parts(node.left) + path_parts(node.right)
            if isinstance(node, ast.Call):
                return [part for argument in node.args for part in path_parts(argument)]
            return []

        violations = []
        for path in sorted((PROJECT_ROOT / "engine/script").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                parts = path_parts(node)
                pairs = set(zip(parts, parts[1:]))
                if ("runtime_ui", "sections") in pairs or ("text", "corpus") in pairs:
                    violations.append((path, node.lineno, "/".join(parts)))

        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()

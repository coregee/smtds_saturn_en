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


if __name__ == "__main__":
    unittest.main()

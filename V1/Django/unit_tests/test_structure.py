"""
Mistakes a reader of the code can find without running it.

Issue #7 was one: datahealth/views.py imported the module `tracks` and then
defined a view called `tracks`, so every `tracks.add(...)` hit a function.
Nothing ran those lines until someone uploaded a file.
"""

import ast
import pathlib

from django.test import SimpleTestCase

ROOT = pathlib.Path(__file__).resolve().parent.parent
APPS = ("config", "datahealth", "survey")
TEMPLATES = [ROOT / "templates"] + [ROOT / app / "templates" for app in APPS]


def sources():
    for app in APPS:
        for path in sorted((ROOT / app).rglob("*.py")):
            if "migrations" not in path.parts and "tests" not in path.parts:
                yield path, ast.parse(path.read_text(encoding="utf-8"), str(path))


def imported_names(tree):
    names = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for a in node.names:
                names[(a.asname or a.name).split(".")[0]] = node.lineno
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                names[a.asname or a.name] = node.lineno
    return names


def defined_names(tree):
    return {node.name for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))} | \
           {t.id for node in tree.body if isinstance(node, ast.Assign)
            for t in node.targets if isinstance(t, ast.Name)} | set(imported_names(tree))


class SourceTests(SimpleTestCase):

    def test_no_function_or_class_replaces_something_the_module_imported(self):
        for path, tree in sources():
            imported = imported_names(tree)
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) \
                        and node.name in imported:
                    with self.subTest(file=path.relative_to(ROOT), name=node.name):
                        self.fail(f"line {node.lineno} defines {node.name!r}, which line "
                                  f"{imported[node.name]} imported: the import is lost")

    def test_every_view_a_urlconf_names_exists(self):
        for path in (ROOT / app / "urls.py" for app in APPS):
            if not path.exists():
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            modules = {n for n in imported_names(tree) if (path.parent / f"{n}.py").exists()}
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                        and node.value.id in modules:
                    target = ast.parse((path.parent / f"{node.value.id}.py").read_text(encoding="utf-8"))
                    with self.subTest(urlconf=path.relative_to(ROOT), view=node.attr):
                        self.assertIn(node.attr, defined_names(target))

    def test_every_template_a_view_renders_exists(self):
        for path, tree in sources():
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                        and node.value.endswith(".html") and "/" in node.value \
                        and " " not in node.value:
                    with self.subTest(file=path.relative_to(ROOT), template=node.value):
                        self.assertTrue(any((folder / node.value).exists() for folder in TEMPLATES))

    def test_every_named_redirect_is_a_url_that_exists(self):
        urls = set()
        for app in APPS:
            path = ROOT / app / "urls.py"
            if path.exists():
                for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                    if isinstance(node, ast.keyword) and node.arg == "name" \
                            and isinstance(node.value, ast.Constant):
                        urls.add(node.value.value)
        for path, tree in sources():
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and getattr(node.func, "id", "") in ("redirect", "reverse") \
                        and node.args and isinstance(node.args[0], ast.Constant) \
                        and isinstance(node.args[0].value, str) \
                        and not any(c in node.args[0].value for c in "/:."):
                    with self.subTest(file=path.relative_to(ROOT), name=node.args[0].value):
                        self.assertIn(node.args[0].value, urls)

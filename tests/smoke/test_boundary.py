import ast
from pathlib import Path
import subprocess
import sys

import hathor
import hathor_smoke

def imported_modules(package_directory: Path, skip: tuple[str, ...] = ()) -> set[str]:
    '''
    Every module a package's source files import, by full dotted name
    '''
    found = set()
    for source in package_directory.rglob('*.py'):
        if any(part in skip for part in source.relative_to(package_directory).parts):
            continue
        for node in ast.walk(ast.parse(source.read_text(encoding='utf-8'))):
            if isinstance(node, ast.Import):
                found.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.add(node.module)
    return found

def is_part_of(module: str, package: str) -> bool:
    return module == package or module.startswith(f'{package}.')

def test_the_smoke_test_never_imports_hathor():
    # It only knows the server's public interface, so it can never run hathor's code (the client's
    # migrations, the telemetry setup). Tests may build a client; the package may not
    modules = imported_modules(Path(hathor_smoke.__file__).parent)
    assert modules
    assert not [module for module in modules if is_part_of(module, 'hathor')]

def test_hathor_never_imports_the_smoke_test():
    modules = imported_modules(Path(hathor.__file__).parent, skip=('plugins',))
    assert modules
    assert not [module for module in modules if is_part_of(module, 'hathor_smoke')]

def test_importing_the_command_does_not_load_hathor():
    # The source scan above misses an import that comes in through a dependency, this does not
    code = ('import sys, hathor_smoke.cli; '
            'sys.exit(any(name == "hathor" or name.startswith("hathor.") for name in sys.modules))')
    result = subprocess.run([sys.executable, '-c', code], check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr

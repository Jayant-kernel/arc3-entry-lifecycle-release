"""Verify this source-only release without importing policy or external modules."""
import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    manifest = json.loads((ROOT / 'MANIFEST.json').read_bytes())
    actual = {path.relative_to(ROOT).as_posix() for path in ROOT.rglob('*')
              if path.is_file() and '.git' not in path.relative_to(ROOT).parts}
    if actual != set(manifest['files']) | {'MANIFEST.json'}:
        raise ValueError('Unlisted or missing release member')
    for name, expected in manifest['files'].items():
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file():
            raise ValueError('Missing or unsafe manifest member')
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Release identity mismatch: ' + name)
    notebook = json.loads((ROOT / 'entry/notebook.ipynb').read_bytes())
    body = ''.join(notebook['cells'][1]['source'])
    tree = ast.parse(body)
    assignments = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == 'PAYLOAD'
                           for target in node.targets)]
    if len(assignments) != 1:
        raise ValueError('Unexpected PAYLOAD declaration')
    payload = ast.literal_eval(assignments[0].value)
    if not isinstance(payload, dict) or len(payload) != 9:
        raise ValueError('Unexpected PAYLOAD inventory')
    for name, content in payload.items():
        if (ROOT / 'entry' / name).read_bytes() != content:
            raise ValueError('Embedded payload mismatch')
    modules = list((ROOT / 'entry').glob('*.py'))
    for path in modules:
        compile(path.read_bytes(), str(path.name), 'exec')
    policy = ast.parse((ROOT / 'entry/entry_policy.py').read_bytes())
    cells = ast.literal_eval(policy.body[0].value)
    indexes = (4, 6, 8, 10, 12, 14, 16)
    for index in indexes:
        compile(cells[index], f'policy-cell-{index}', 'exec')
    compile(body, 'notebook-wrapper', 'exec')
    print(json.dumps(dict(manifest_files=len(manifest['files']), payload_files=len(payload),
                          modules_compiled=len(modules), policy_cells_compiled=len(indexes),
                          status='PASS', policy_executed=False, model_loaded=False)))


if __name__ == '__main__':
    main()

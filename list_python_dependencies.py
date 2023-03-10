import json
import os
import random
import re
import tomllib
from pathlib import Path

import requests
from packaging.requirements import Requirement

__version__ = '0.0.2'
__all__ = ('list_python_dependencies',)


def list_python_dependencies():
    path = Path(os.getenv('INPUT_PATH') or '.').expanduser().resolve()

    max_cases_v = os.environ.get('INPUT_MAX_CASES')
    if max_cases_v:
        max_cases = int(max_cases_v)
    else:
        max_cases = None

    first_last = os.getenv('INPUT_MODE', '').strip().lower() == 'first-last'

    print(f'list-dependencies __version__={__version__!r} path={path!r} max_cases={max_cases} first_last={first_last}')
    deps = load_deps(path)
    valid_versions = get_valid_versions(deps)
    print('')
    cases = get_test_cases(valid_versions, max_cases=max_cases, first_last=first_last)
    for case in cases:
        print(f'  {case}')
    print('')

    github_output = os.getenv('GITHUB_OUTPUT')
    env_name = 'PYTHON_DEPENDENCY_CASES'
    if github_output:
        json_value = json.dumps(cases)
        print('Setting output for future use:')
        print(f'  {env_name}={json_value}')
        with open(github_output, 'a') as f:
            f.write(f'{env_name}={json_value}\n')
    else:
        print(f'Warning: GITHUB_OUTPUT not set, cannot set {env_name}')


class OptionalRequirement(Requirement):
    pass


def load_deps(path: Path) -> list[Requirement]:
    py_pyroject = path / 'pyproject.toml'
    if py_pyroject.exists():
        with py_pyroject.open('rb') as f:
            pyproject = tomllib.load(f)
        deps = [Requirement(dep) for dep in pyproject['project']['dependencies']]
        option_deps = pyproject['project'].get('optional-dependencies')
        if option_deps:
            for extra_deps in option_deps.values():
                deps.extend([OptionalRequirement(dep) for dep in extra_deps])
        return deps

    setup_py = path / 'setup.py'
    if setup_py.exists():
        setup = setup_py.read_text()
        m = re.search(r'install_requires=(\[.+?])', setup, flags=re.S)
        if not m:
            raise RuntimeError('Could not find `install_requires` in setup.py')
        install_requires = eval(m.group(1))
        deps = [Requirement(dep) for dep in install_requires]
        m = re.search(r'extras_require=(\{.+?})', setup, flags=re.S)
        if m:
            for extra_deps in eval(m.group(1)).values():
                deps.extend(OptionalRequirement(dep) for dep in extra_deps)
        return deps

    raise RuntimeError(f'No {py_pyroject.name} or {setup_py.name} found in {path}')


OMIT_SENTINEL = '[omit]'


def get_valid_versions(deps: list[Requirement]) -> dict[str, list[str]]:
    session = requests.Session()
    valid_versions: dict[str, list[str]] = {}
    for dep in deps:
        resp = session.get(f'https://pypi.org/pypi/{dep.name}/json')
        resp.raise_for_status()
        versions = resp.json()['releases'].keys()
        compat_versions = [v for v in versions if v in dep.specifier]
        if not compat_versions:
            raise RuntimeError(f'No compatible versions found for {dep.name}')
        if isinstance(dep, OptionalRequirement):
            compat_versions.append(OMIT_SENTINEL)
        valid_versions[dep.name] = compat_versions
    return valid_versions


def get_test_cases(valid_versions: dict[str, list[str]], max_cases: int | None, first_last: bool) -> list[str]:
    min_versions = [(name, versions[0]) for name, versions in valid_versions.items()]
    cases: list[tuple[tuple[str, str], ...]] = []

    for name, versions in valid_versions.items():
        add_versions = []
        if first_last:
            # if first_last is True, we only add the last version, unless it's an "[omit]" sentinel,
            # in which case we also add teh last but one value which should be the last version
            if len(versions) > 1:
                add_versions = [versions[-1]]
                if len(versions) > 2 and add_versions[0] == OMIT_SENTINEL:
                    add_versions.insert(0, versions[-2])
        else:
            add_versions = versions[1:]

        for v in add_versions:
            case = [as_req(n, v if n == name else min_v) for n, min_v in min_versions]
            cases.append(tuple(case))

    min_versions_case = tuple(as_req(n, v) for n, v in min_versions)
    total_cases = len(cases) + 1
    if max_cases and total_cases > max_cases:
        print(f'{total_cases} cases generated, truncating to {max_cases}')
        trunc_cases = set(random.sample(cases, k=max_cases - 1))
        cases = [min_versions_case] + [case for case in cases if case in trunc_cases]
    else:
        print(f'{total_cases} cases generated')
        cases = [min_versions_case] + cases
    return [' '.join(case).replace('  ', ' ') for case in cases]


def as_req(name: str, version: str) -> str:
    if version == OMIT_SENTINEL:
        return ''
    else:
        return f'{name}=={version}'


if __name__ == '__main__':
    list_python_dependencies()

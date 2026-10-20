"""Find a configured sibling installation without depending on a versioned name."""
import shlex
import subprocess
import sys
from pathlib import Path
from .updater import install


def existing(path,source):
    path,source=Path(path).resolve(),Path(source).resolve()
    return path!=source and all((path/name).is_file() for name in ('config/profile.json','config/sending.json','acquisition_agent/__main__.py','state/agent.sqlite3'))


def candidates(source):
    source=Path(source).resolve()
    # Only inspect sibling app folders; do not scan personal files or credentials.
    return sorted((path.resolve() for path in source.parent.iterdir() if path.is_dir() and existing(path,source)),key=lambda p:p.name)


def select(source,ask=input,show=print):
    choices=candidates(source)
    if len(choices)==1:
        show('Found your existing installation: '+str(choices[0]))
        return choices[0]
    if choices:
        show('More than one installation has saved history. Choose the one you want to update:')
        for i,path in enumerate(choices,1):show(str(i)+'. '+str(path))
        value=ask('Installation number, or full existing folder path: ').strip()
        if value.isdigit():
            index=int(value)-1
            if not 0<=index<len(choices):raise ValueError('Choose a listed installation number')
            return choices[index]
    else:
        value=ask('Existing installation folder (drag it here, or enter its full path): ').strip()
    path=Path(value).expanduser()
    if not path.is_dir():
        parts=shlex.split(value)
        if len(parts)!=1:raise ValueError('Enter one existing installation folder')
        path=Path(parts[0]).expanduser()
    if not existing(path,source):raise ValueError('Select an existing Shine app with its saved state folder, not the extracted update')
    return path.resolve()


def main():
    source=Path(__file__).resolve().parent.parent
    print('Stop all Shine workspace and worker Terminal windows with Ctrl+C before updating.')
    target=select(source)
    install(source,target)
    print('Update saved. Open Run-Shine.command in your original installation to research, sync and send approved messages.')
    return subprocess.run([sys.executable,'-m','acquisition_agent','dashboard','--port','8766'],cwd=str(target)).returncode

if __name__=='__main__':
    try:raise SystemExit(main())
    except (ValueError,OSError,EOFError,KeyboardInterrupt) as exc:
        print('Update stopped: '+str(exc));raise SystemExit(1)

"""Private Terminal-only API setup. Never tests or purchases paid services."""
import getpass
import os
import tempfile
from pathlib import Path


def save_keys(root, values):
    path=Path(root)/'.env'
    if path.is_symlink():raise ValueError('Use a regular .env file, not a symlink')
    allowed={'OPENAI_API_KEY','FIRECRAWL_API_KEY'}
    if not values or not set(values)<=allowed:raise ValueError('Unsupported credential field')
    for value in values.values():
        if not isinstance(value,str) or not value or any(c.isspace() or c in "\"'" or ord(c)<32 for c in value):
            raise ValueError('Keys must be one unquoted token without spaces')
    lines=path.read_text().splitlines() if path.exists() else []
    lines=[line for line in lines if line.split('=',1)[0].strip() not in values]
    lines.extend(name+'='+value for name,value in values.items())
    fd,tmp=tempfile.mkstemp(prefix='.env-',dir=str(root))
    try:
        with os.fdopen(fd,'w') as handle:handle.write('\n'.join(lines)+'\n')
        os.chmod(tmp,0o600);os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def main():
    root=Path(__file__).resolve().parent.parent
    print('Automatic research setup — keys are hidden while you paste.')
    print('OpenAI API billing is separate from ChatGPT Plus. Use manual prepaid credit and disable auto-reload if you want manual top-ups.')
    print('Use Firecrawl Free. This tool never purchases credit or subscriptions.')
    print('Leave a field blank to keep its existing value. Never paste keys into chat.')
    values={}
    for name in ('OPENAI_API_KEY','FIRECRAWL_API_KEY'):
        value=getpass.getpass(name+': ').strip()
        if value:values[name]=value
    if values:save_keys(root,values)
    print('Setup finished. Restart Run-Shine.command to load your keys. No API requests were made.')

if __name__=='__main__':
    try:main()
    except (OSError,ValueError,EOFError,KeyboardInterrupt):
        print('Setup stopped. Check the local .env file; credentials are never printed.')
        raise SystemExit(1)

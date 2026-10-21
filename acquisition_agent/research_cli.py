"""On-demand research into the existing Mac state and original Notion database.

Run from this source with --installation pointing at the preserved installation.
Configured keys stay in its .env; no delivery operation is imported or invoked.
"""
import argparse
import json
import os
from pathlib import Path
from .core import Store, read_json
from .targeting import create_session
from .automatic import run


def load_settings(root):
    root=Path(root).expanduser().resolve()
    for line in (root/'.env').read_text().splitlines():
        if '=' not in line or line.lstrip().startswith('#'):continue
        key,value=line.split('=',1)
        if key.strip() in ('NOTION_TOKEN','NOTION_API_KEY','OPENAI_API_KEY','FIRECRAWL_API_KEY'):
            os.environ[key.strip()]=value.strip().strip('\"').strip("'")
    if not os.getenv('NOTION_TOKEN') and os.getenv('NOTION_API_KEY'):
        os.environ['NOTION_TOKEN']=os.environ['NOTION_API_KEY']
    settings={key:read_json(root/'config'/(key+'.json')) for key in ('profile','preferences','sending','exclusions')}
    if settings['sending']['mode']!='draft-only':
        raise ValueError('Keep the Mac sender in draft-only while hosted delivery owns the queue')
    return root,settings


def main():
    p=argparse.ArgumentParser(description='Research, personalize, sync to Notion. Final approval stays in Notion.')
    p.add_argument('--installation',required=True)
    p.add_argument('--state-dir',help='Optional separate research state directory; preserves the original Mac queue')
    p.add_argument('--country',required=True);p.add_argument('--city',required=True)
    p.add_argument('--company-type',choices=['Brand','Agency','Start-up'],required=True)
    p.add_argument('--industry',action='append',default=[])
    p.add_argument('--kind',choices=['Cold Outreach','Posted Job'],default='Cold Outreach')
    p.add_argument('--limit',type=int,default=3)
    args=p.parse_args()
    root,s=load_settings(args.installation)
    # Harmless credential check before reserving credit or creating a session.
    from .network import api_json
    from .automatic import provider_error
    try:
        api_json('https://api.firecrawl.dev/v2/team/credit-usage','GET',headers={
            'Authorization':'Bearer '+os.environ.get('FIRECRAWL_API_KEY','')})
    except ValueError as exc:
        raise SystemExit(provider_error(exc)) from None
    store=Store(Path(args.state_dir).resolve() if args.state_dir else root/'state')
    try:
        spec={'country':args.country,'city':args.city,'company_type':args.company_type,
              'industries':args.industry,'kind':args.kind,'limit':args.limit}
        session=create_session(store,spec,s['preferences'],s['profile'],s['exclusions'])
        def progress(result):
            print(json.dumps({k:result[k] for k in ('stage','researched','drafts','new','duplicates') if k in result}),flush=True)
        result=run(store,session,s['preferences'],s['profile'],s['exclusions'],
                   progress=progress,sending_config=dict(s['sending'],delivery_backend='github'))
        print(json.dumps({'session_id':session['id'],**result},ensure_ascii=False),flush=True)
    finally:store.db.close()


if __name__=='__main__':main()

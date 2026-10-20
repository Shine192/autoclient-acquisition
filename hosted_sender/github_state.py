"""Encrypted Git history with fast-forward-only claims, never runner-only state.

Every transaction finishes its remote ref update before returning. A failed or
ambiguous update poisons this instance; no caller may continue to dispatch.
No message sends or other external side effects belong in transaction callbacks.
"""
import base64,copy,json,re,zlib
from urllib import request,error,parse
from cryptography.fernet import Fernet,InvalidToken

BRANCH='shine-delivery-state'
MAX_PLAIN=12_000_000
MAX_SEALED=900_000  # Contents API returns inline base64 only below one MiB.

class StateError(RuntimeError):pass

class Codec:
    def __init__(self,key,repository):
        self.cipher=Fernet(key.encode() if isinstance(key,str) else key)
        self.repository=repository
    def seal(self,records):
        raw=json.dumps({'version':1,'repository':self.repository,'records':records},ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
        if len(raw)>MAX_PLAIN:raise StateError('State too large; archive completed campaigns with technical help')
        sealed=self.cipher.encrypt(zlib.compress(raw,9))
        if len(sealed)>MAX_SEALED:raise StateError('Encrypted state exceeds pilot size limit')
        return sealed.decode()
    def open(self,sealed):
        if len(sealed)>MAX_SEALED:raise StateError('Encrypted state too large')
        try:
            packed=self.cipher.decrypt(sealed.encode());d=zlib.decompressobj()
            raw=d.decompress(packed,MAX_PLAIN+1)
            if len(raw)>MAX_PLAIN or not d.eof:raise ValueError('Decompression limit')
            value=json.loads(raw)
            if value['version']!=1 or value['repository']!=self.repository or not isinstance(value['records'],dict):raise ValueError('State identity')
            return value['records']
        except (InvalidToken,ValueError,KeyError,zlib.error,TypeError):raise StateError('State cannot be verified; no sending allowed') from None

class API:
    def __init__(self,repository,token):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repository) or not token:raise StateError('GitHub repository/token missing')
        self.base='https://api.github.com/repos/'+repository+'/'
        self.token=token
    def __call__(self,path,method='GET',data=None):
        from acquisition_agent.network import NoRedirect
        body=json.dumps(data).encode() if data is not None else None
        req=request.Request(self.base+path,data=body,method=method,headers={'Authorization':'Bearer '+self.token,'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28','Content-Type':'application/json','User-Agent':'ShineHostedSender/0.1'})
        try:
            with request.build_opener(NoRedirect()).open(req,timeout=45) as r:
                raw=r.read(4_000_001)
                if len(raw)>4_000_000:raise StateError('GitHub response exceeds pilot limit')
                return json.loads(raw)
        except (error.URLError,ValueError):raise StateError('GitHub state request failed; delivery stopped safely') from None

class GitHubState:
    def __init__(self,repository,key,api):
        self.codec=Codec(key,repository);self.api=api;self.broken=False
        ref=api('git/ref/heads/'+BRANCH);self.head=ref['object']['sha']
        commit=api('git/commits/'+self.head);self.tree=commit['tree']['sha']
        contents=api('contents/ledger.enc?ref='+parse.quote(self.head,safe=''))
        if contents.get('encoding')!='base64':raise StateError('Unsupported encrypted state response')
        self.records=self.codec.open(base64.b64decode(contents['content']).decode())
    def transaction(self,fn):
        if self.broken:raise StateError('State persistence previously failed; restart from durable state')
        proposed=copy.deepcopy(self.records)
        class Tx:
            def get(self,k):return copy.deepcopy(proposed.get(k))
            def put(self,k,v):proposed[k]=copy.deepcopy(v)
        result=fn(Tx())
        if proposed==self.records:return result
        try:
            content=self.codec.seal(proposed)
            blob=self.api('git/blobs','POST',{'content':content,'encoding':'utf-8'})
            tree=self.api('git/trees','POST',{'base_tree':self.tree,'tree':[{'path':'ledger.enc','mode':'100644','type':'blob','sha':blob['sha']}]})
            commit=self.api('git/commits','POST',{'message':'Persist encrypted delivery state','tree':tree['sha'],'parents':[self.head]})
            # Sibling claims cannot both fast-forward the same branch. Never force.
            self.api('git/refs/heads/'+BRANCH,'PATCH',{'sha':commit['sha'],'force':False})
            self.head,self.tree,self.records=commit['sha'],tree['sha'],proposed
        except BaseException:
            self.broken=True
            raise
        return result
    def get(self,key):return self.transaction(lambda tx:tx.get(key))
    def assert_current(self):
        if self.broken:raise StateError('State persistence failed')
        if self.api('git/ref/heads/'+BRANCH)['object']['sha']!=self.head:
            self.broken=True
            raise StateError('Delivery state changed after claim; inspect before sending')
    def list(self,kind,limit=200):
        if self.broken:raise StateError('State persistence failed')
        found=[copy.deepcopy(v) for v in self.records.values() if v.get('kind')==kind]
        if len(found)>limit:raise StateError('Pilot record limit reached')
        return found

def initialize(repository,key,api,records):
    """Explicit setup only: creating an existing branch fails; never overwrites it."""
    sealed=Codec(key,repository).seal(records)
    blob=api('git/blobs','POST',{'content':sealed,'encoding':'utf-8'})
    tree=api('git/trees','POST',{'tree':[{'path':'ledger.enc','mode':'100644','type':'blob','sha':blob['sha']}]})
    commit=api('git/commits','POST',{'message':'Initialize encrypted delivery history','tree':tree['sha'],'parents':[]})
    api('git/refs','POST',{'ref':'refs/heads/'+BRANCH,'sha':commit['sha']})

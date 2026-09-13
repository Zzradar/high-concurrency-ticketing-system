"""Append-only packaging and audit for the login-race follow-up; never rewrites Phase19 baseline."""
import argparse, hashlib, json, os, re, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
DEST=ROOT/'performance/experiments/phase19-auth-login-race-fix'
OLD=ROOT/'performance/experiments/phase19-global-polling-mixed-load'
BASE='5bee9e7ea400814e8e487bf4075677a4a4311880'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def textsha(p):return hashlib.sha256(p.read_bytes().replace(b"\r\n",b"\n")).hexdigest()
def git(*args):return subprocess.check_output(['git','-C',str(ROOT),*args],text=True,encoding='utf8').strip()
def save(p,value):
    assert not p.exists(), str(p)+' already exists'
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_bytes((json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode())
def package():
    from phase19_archive_formal import package as archive
    from phase19_archive_candidate import redact
    sys.path.insert(0,str(OLD/'protocol'))
    from report_tables import capacity,browser
    private=Path(os.environ['TEMP'])
    table={'capacity':{},'browser':{}}
    for name in ['closed-2000-10m','open-l3','journeys-5001','hotspot-1000']:
        source=private/'phase19-authfix-final-points'/({'journeys-5001':'journeys-5001-retry','open-l3':'open-l3-warmed'}.get(name,name))
        assert json.loads((source/'result.json').read_text())['valid'],name
        target=DEST/'capacity'/name;archive(source,target);table['capacity'][name]=capacity(target)
    for name in ['open-precheck','open-l1','open-l2']:
        source=private/'phase19-authfix-final-points'/name
        assert json.loads((source/'result.json').read_text())['valid'],name
        archive(source,DEST/'open-prerequisites'/name)
    archive(private/'phase19-authfix-final-points/open-l3',DEST/'diagnostics/final-direct-open-l3')
    initial=private/'phase19-authfix-final-points/journeys-5001'
    save(DEST/'diagnostics/journeys-precondition-rejection.json',{'verifierBefore':json.loads((initial/'verifier-before.json').read_text()),'meaning':'No load began because Redis display had not converged after aborted Open point; subsequent unchanged verifier passed before retry.'})
    for name in ['events','panel','seat','payment','refund','submitting','logout']:
        source=private/'phase19-authfix-final-browser'/name
        result=json.loads((source/'browser.json').read_text(encoding='utf8'));assert result['passed'],name
        archive(source,DEST/'polling-after'/name);table['browser'][name]=browser(result)
    regression_files={}
    for folder in ['phase19-authfix-regression','phase19-authfix-financial','phase19-authfix-overload','phase19-authfix-real-identity']:
        source=private/folder;assert source.is_dir()
        for p in source.rglob('*'):
            if not p.is_file() or not (p.suffix=='.log' or p.name in ['overload-recovery.json','identity-browser.json','availability-outage-diagnostic.json','result.json']):continue
            target=DEST/'regression'/folder/p.relative_to(source)
            assert not target.exists();target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(redact(p.read_text(encoding='utf8').replace('\r\n','\n')).encode())
            regression_files[target.relative_to(DEST).as_posix()]={'sourceSha256':sha(p),'sourceBytes':p.stat().st_size,'archivedSha256':sha(target),'archivedBytes':target.stat().st_size}
    save(DEST/'regression-archive-manifest.json',{'normalization':'Private paths and UTF-8 newlines only','files':regression_files})
    # Preserve completed first-run points under an explicitly superseded identity.
    for group in ['phase19-authfix-points','phase19-authfix-browser']:
        for source in (private/group).iterdir():
            if source.is_dir() and ((source/'result.json').exists() or (source/'browser.json').exists()):
                archive(source,DEST/'diagnostics'/group/source.name)
    save(DEST/'summary.json',table)
def manifest():
    source=git('rev-parse','a7a96d3')
    assert git('diff',BASE,'--',str(OLD.relative_to(ROOT)))=='','Old evidence changed'
    files={p.relative_to(DEST).as_posix():{'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(DEST.rglob('*')) if p.is_file() and p.name not in ['Manifest.json','REPORT.md']}
    save(DEST/'Manifest.json',{'sourceCommit':source,'acceptance':json.loads((DEST/'regression-status.json').read_text()),'frontendTree':git('rev-parse',source+':frontend/src'),'frontendArtifacts':json.loads((DEST/'polling-after/events/browser.json').read_text())['artifacts'],'backendProductionTree':git('rev-parse',source+':backend/src'),'testFileHashNormalization':'CRLF normalized to LF','testFiles':{str(p.relative_to(ROOT)).replace('\\','/'):textsha(p) for p in sorted((ROOT/'frontend/tests').glob('phase19.*.test.ts'))},'baselineCommit':BASE,'baselineEvidenceTree':git('rev-parse',BASE+':'+OLD.relative_to(ROOT).as_posix()),'frozenProtocolSha256':sha(OLD/'protocol-sha256.json'),'files':files,'scripts':{str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in [Path(__file__),ROOT/'performance/scripts/phase19_auth_identity.mjs']},'exclusions':['Manifest.json (self)','REPORT.md (references this manifest hash)']})
    audit()
def audit():
    m=json.loads((DEST/'Manifest.json').read_text(encoding='utf8'))
    assert git('diff',BASE,'--',str(OLD.relative_to(ROOT)))==''
    assert git('rev-parse','HEAD:frontend/src')==m['frontendTree']
    for name,v in m['files'].items():assert sha(DEST/name)==v['sha256'] and (DEST/name).stat().st_size==v['bytes'],name
    for name,value in m['frontendArtifacts'].items():assert sha(ROOT/'frontend/dist'/name)==value['sha256'],name
    for name,digest in m['scripts'].items():assert sha(ROOT/name)==digest,name
    for name,digest in m['testFiles'].items():assert textsha(ROOT/name)==digest,name
    actual={p.relative_to(DEST).as_posix() for p in DEST.rglob('*') if p.is_file() and p.name not in ['Manifest.json','REPORT.md']}
    assert actual==set(m['files'])
    for p in (DEST/'capacity').glob('*/result.json'):
        assert json.loads(p.read_text())['valid'],str(p)
        identity=json.loads(p.with_name('identity.json').read_text())
        assert identity['stack']['sourceCommit']==m['sourceCommit']
        assert identity['stack']['binarySha256']=='d9082f28bdf8d5bb8312cee40c9e6a79345b559554d4cbd2a301e742fae0bad5'
        assert identity['generatorLimits']['memoryBytes']==4*1024**3
    for p in (DEST/'polling-after').glob('*/browser.json'):
        b=json.loads(p.read_text());assert b['passed'] and b['frontendTree']==m['frontendTree'] and b['sourceCommit']==m['sourceCommit'] and b['artifacts']==m['frontendArtifacts']
    b=json.loads((DEST/'regression/phase19-authfix-real-identity/identity-browser.json').read_text(encoding='utf8'));assert b['passed'] and b['sourceCommit']==m['sourceCommit']
    assert len(list((DEST/'capacity').glob('*/result.json')))==4
    assert len(list((DEST/'polling-after').glob('*/browser.json')))==7
    assert m['acceptance']['frontend']['passed']==344
    assert m['acceptance']['backend']['total']==166
    print(json.dumps({'evidenceAuditPassed':True,'acceptanceStatus':m['acceptance']['status'],'sourceCommit':m['sourceCommit'],'manifestSha256':sha(DEST/'Manifest.json'),'indexedFiles':len(actual)}))
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['package','manifest','audit']);args=parser.parse_args()
    globals()[args.action]()

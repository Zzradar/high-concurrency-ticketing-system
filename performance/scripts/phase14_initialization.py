"""Serialize VU initialization while the unchanged safety sampler keeps running."""
import json
from pathlib import Path
import threading
import time


class Initialization:
    def __init__(self, root, run_id, shards, release_at_ms, observe, *, serial=True, deadline_at_ms=None, abort=None):
        self.root=Path(root);self.run_id=run_id;self.shards=[str(s) for s in shards]
        self.release_at_ms=release_at_ms;self.observe=observe
        self.deadline_at_ms=deadline_at_ms or release_at_ms;self.abort=abort
        self.stop=threading.Event();self.error=None;self.ready=[]
        self.serial=serial;self.pending=[]
        self.thread=threading.Thread(target=self.watch,name='phase14-initialization-sampler',daemon=True)

    def watch(self):
        try:
            while not self.stop.is_set():self.observe()
        except Exception as error:
            self.error=error;self.stop.set()

    def __enter__(self):
        self.thread.start();return self

    def register(self, process, log, shard):
        if self.serial:self.wait(process,log,shard)
        else:self.pending.append((process,log,shard))

    def finish(self):
        for process,log,shard in self.pending:self.wait(process,log,shard)

    def wait(self, process, log, shard):
        shard=str(shard)
        if shard!=self.shards[len(self.ready)]:raise ValueError('initialization shard order changed')
        marker=('PHASE14_INIT_READY|'+self.run_id+'|'+shard+'|').encode()
        while True:
            if self.error:raise RuntimeError('initialization sampler failed: '+str(self.error))
            if process.poll() is not None:raise RuntimeError('generator exited before initialization readiness')
            if time.time()*1000>=self.deadline_at_ms:raise RuntimeError('initialization missed frozen release point')
            path=Path(log.name)
            with path.open('rb') as stream:
                stream.seek(max(0,path.stat().st_size-65536));tail=stream.read()
            if marker in tail:
                self.ready.append({'shard':shard,'readyAtMs':time.time()*1000})
                return
            self.stop.wait(.05)

    def __exit__(self, kind, error, traceback):
        self.stop.set()
        failure=error or self.error
        if failure and self.abort:
            try:self.abort()
            except Exception as stop_error:failure=RuntimeError(str(failure)+'; abort failed: '+str(stop_error))
        self.thread.join(timeout=5 if self.abort else 30)
        if self.thread.is_alive():failure=RuntimeError('initialization sampler did not stop')
        if not failure and len(self.ready)!=len(self.shards):failure=RuntimeError('incomplete initialization')
        record={'mode':'serial_initialization' if self.serial else 'concurrent_smoke_initialization','runId':self.run_id,'shards':self.shards,
                'releaseAtMs':self.release_at_ms,'deadlineAtMs':self.deadline_at_ms,'ready':self.ready,'safetySampling':True,
                'status':'fail' if failure else 'pass','error':str(failure) if failure else None}
        (self.root/'initialization.json').write_text(json.dumps(record,indent=2)+'\n')
        if kind is None and failure:raise failure
        return False

"""One owned read-only psql connection for light activity observations."""
import json
from pathlib import Path
import queue
import subprocess
import threading

class ActivityConnection:
    def __init__(self,env):
        self.env=env;self.lines=queue.Queue();self.pid=None;self.birth=None
        self.process=env.psql_popen()
        self.reader=threading.Thread(target=self._read,daemon=True);self.reader.start()
        try:
            info=json.loads(self.sql("SET default_transaction_read_only=on; SET statement_timeout='5s'; SELECT json_build_object('pid',pg_backend_pid(),'birth',backend_start) FROM pg_stat_activity WHERE pid=pg_backend_pid();"))
            self.pid=info['pid'];self.birth=info['birth']
        except Exception:
            self.close();raise
    def _read(self):
        for line in self.process.stdout:self.lines.put(line)
        self.lines.put(None)
    def sql(self,sql):
        self.process.stdin.write(sql+'\n');self.process.stdin.flush()
        line=self.lines.get(timeout=10)
        if line is None:raise RuntimeError('persistent activity connection ended')
        return line.strip()
    def close(self):
        if self.process.poll() is None:
            try:
                self.process.stdin.write('\\q\n');self.process.stdin.flush();self.process.wait(timeout=7)
            except (OSError,subprocess.TimeoutExpired):
                if self.pid is not None:
                    self.env.sql(f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE pid={int(self.pid)} AND backend_start='{self.birth}' AND application_name='phase14_sampler';")
                self.process.wait(timeout=10)
        self.reader.join(timeout=2)
        for stream in (self.process.stdin,self.process.stdout,self.process.stderr):stream.close()

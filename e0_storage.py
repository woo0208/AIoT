"""Bounded numeric log checkpoints and exact, disk-backed percentiles.

No sampling/eviction: committed chunks retain every record in original order.
Publication uses exclusive .partial files and rename; disk errors fail closed.
The buffer bound is not a hard bound on process RSS or the 10s feature window.
"""
import json
import math
import os
from pathlib import Path
import sqlite3
import tempfile
import time

import numpy as np
import performance_output as output
from probe_timing import _stats


class LogStorageError(RuntimeError):
    pass


def publish(path, write):
    path=Path(path)
    if path.exists():
        raise FileExistsError(path.name)
    partial=path.with_name(path.name+'.partial')
    try:
        with partial.open('x',encoding='utf-8',newline='\n') as stream:
            write(stream)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            raise FileExistsError(path.name)
        os.rename(partial,path)
    except Exception as exc:
        raise LogStorageError(type(exc).__name__) from None


def write_json(path, document, *, arrays=()):
    def write(stream):
        stream.write('{')
        for i,(key,value) in enumerate(document.items()):
            if i:stream.write(',')
            stream.write(json.dumps(key)+':')
            if key in arrays:
                stream.write('[')
                for j,row in enumerate(value):
                    if j:stream.write(',')
                    stream.write(output.canonical(row))
                stream.write(']')
            else:
                stream.write(output.canonical(value))
        stream.write('}\n')
    publish(path,write)


def write_rows(path, rows):
    def write(stream):
        for row in rows:stream.write(output.canonical(row)+'\n')
    publish(path,write)


class CheckpointList:
    def __init__(self, directory, limit=256, *, max_bytes=64*2**20, clock_ns=time.perf_counter_ns):
        if type(limit) is not int or limit<1 or max_bytes<1:
            raise ValueError('positive checkpoint limits required')
        self.directory=Path(directory)
        self.directory.mkdir(parents=True,exist_ok=False)
        self.limit,self.max_bytes,self.clock_ns=limit,max_bytes,clock_ns
        self.buffer=[]
        self.disk_count=self.chunk_count=self.bytes_written=self.flush_ns=self.peak_buffered=0

    def append(self,row):
        if len(self.buffer)>=self.limit:self.flush()
        self.buffer.append(row)
        self.peak_buffered=max(self.peak_buffered,len(self.buffer))

    def flush(self):
        if not self.buffer:return
        start=self.clock_ns()
        encoded=[output.canonical(row)+'\n' for row in self.buffer]
        sizes=[len(row.encode('utf-8')) for row in encoded]
        if max(sizes)>64*1024 or self.bytes_written+sum(sizes)>self.max_bytes:
            raise LogStorageError('LOG_CAPACITY_EXCEEDED')
        path=self.directory/f'{self.chunk_count:08}.jsonl'
        publish(path,lambda stream:stream.writelines(encoded))
        self.disk_count+=len(self.buffer)
        self.chunk_count+=1
        self.bytes_written+=sum(sizes)
        self.buffer.clear()
        self.flush_ns+=self.clock_ns()-start

    def __len__(self):return self.disk_count+len(self.buffer)

    def __iter__(self):
        for index in range(self.chunk_count):
            with (self.directory/f'{index:08}.jsonl').open(encoding='utf-8') as stream:
                for line in stream:yield json.loads(line)
        yield from self.buffer

    def __getitem__(self,index):
        if isinstance(index,slice):
            start,stop,step=index.indices(len(self))
            return [row for i,row in enumerate(self) if start<=i<stop and (i-start)%step==0]
        if index<0:index+=len(self)
        if index<0 or index>=len(self):raise IndexError(index)
        if index>=self.disk_count:return self.buffer[index-self.disk_count]
        return next(row for i,row in enumerate(self) if i==index)

    def status(self):
        return dict(limit_records=self.limit,buffered_records=len(self.buffer),
            peak_buffered_records=self.peak_buffered,records=len(self),chunks=self.chunk_count,
            bytes_written=self.bytes_written,flush_ns=self.flush_ns,max_spool_bytes=self.max_bytes)


def exact_stats(values, *, include_p99=False, disk=False):
    if not disk:
        values=list(values)
        result=_stats(values)
        if include_p99:result['p99']=float(np.percentile(values,99)) if values else None
        return result
    with tempfile.TemporaryDirectory(prefix='e0-numeric-stats-') as temp:
        connection=sqlite3.connect(str(Path(temp)/'numeric.sqlite'))
        try:
            connection.execute('PRAGMA temp_store=FILE')
            connection.execute('PRAGMA cache_size=-1024')
            connection.execute('PRAGMA mmap_size=0')
            connection.execute('CREATE TABLE sample(value REAL NOT NULL)')
            def rows():
                for value in values:
                    value=float(value)
                    if not math.isfinite(value):raise ValueError('nonfinite timing statistic')
                    yield (value,)
            connection.executemany('INSERT INTO sample VALUES (?)',rows())
            connection.execute('CREATE INDEX ordered_values ON sample(value)')
            count=connection.execute('SELECT count(*) FROM sample').fetchone()[0]
            result=dict(count=count)
            for percentile in ([50,95,99] if include_p99 else [50,95]):
                if not count:
                    result[f'p{percentile}']=None
                    continue
                location=(count-1)*np.float64(percentile/100)
                low=int(location);fraction=location-low
                bounds=[r[0] for r in connection.execute(
                    'SELECT value FROM sample ORDER BY value LIMIT 2 OFFSET ?', (low,))]
                a=np.float64(bounds[0]);b=np.float64(bounds[-1]);delta=b-a
                # NumPy's linear interpolation, including its >=0.5 rounding branch.
                result[f'p{percentile}']=float(a+delta*fraction if fraction<.5 else b-delta*(1-fraction))
            result['maximum']=connection.execute('SELECT max(value) FROM sample').fetchone()[0]
            return result
        finally:
            connection.close()

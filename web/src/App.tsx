import { useCallback, useEffect, useMemo, useState } from 'react';

const API = (import.meta.env.VITE_LOCAL_API as string | undefined) ?? 'http://127.0.0.1:8780';

type Health = {
  ok: boolean;
  rag?: { ok?: boolean };
  mineru?: { ok?: boolean; path?: string };
  deepread?: { ok?: boolean; path?: string };
  ssh_configured?: boolean;
  org_id?: string;
  api_url?: string;
};

type Job = {
  id: string;
  kind: string;
  state: string;
  phase?: string;
  progress?: number;
  error?: string | null;
  result?: Record<string, unknown> | null;
  logs?: string[];
};

type Track = 'knowledge' | 'survey';

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [track, setTrack] = useState<Track>('knowledge');
  const [orgId, setOrgId] = useState('');
  const [mode, setMode] = useState('auto');
  const [upload, setUpload] = useState(true);
  const [skipMineru, setSkipMineru] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const accept =
    track === 'survey'
      ? '.xlsx,.xlsm,.docx,.jsonl,.gz,application/gzip'
      : '.pdf,.md,.markdown,.json';

  const dropHint =
    track === 'survey'
      ? 'Drop Excel / Word / chunks.jsonl.gz'
      : 'Drop PDF / MD / *_corpus.json';

  const refreshHealth = useCallback(async () => {
    try {
      const res = await fetch(`${API}/health`);
      const data = (await res.json()) as Health;
      setHealth(data);
      setError(null);
      if (!orgId && data.org_id) setOrgId(data.org_id);
    } catch (e) {
      setHealth(null);
      setError(`API unreachable at ${API}: ${String(e)}`);
    }
  }, [orgId]);

  useEffect(() => {
    void refreshHealth();
  }, [refreshHealth]);

  useEffect(() => {
    if (!job || job.state === 'done' || job.state === 'failed') return;
    const t = setInterval(async () => {
      const res = await fetch(`${API}/jobs/${job.id}`);
      if (!res.ok) return;
      const data = (await res.json()) as Job;
      setJob(data);
      if (data.state === 'done' || data.state === 'failed') setBusy(false);
    }, 1200);
    return () => clearInterval(t);
  }, [job]);

  const onDrop = (files: FileList | null) => {
    if (!files?.length) return;
    setFile(files[0]);
    setError(null);
  };

  const startPipeline = async () => {
    if (!file) {
      setError(
        track === 'survey'
          ? 'Choose an Excel / Word / chunks.jsonl(.gz) file first'
          : 'Choose a PDF / markdown / corpus.json first',
      );
      return;
    }
    setBusy(true);
    setError(null);
    setJob(null);
    const body = new FormData();
    body.append('file', file);
    body.append('track', track);
    body.append('mode', mode);
    body.append('upload', String(upload));
    body.append('skip_mineru', String(skipMineru));
    if (orgId.trim()) body.append('org_id', orgId.trim());
    body.append('document_id', file.name.replace(/\.[^.]+$/, ''));
    body.append('filename', file.name);
    try {
      const res = await fetch(`${API}/jobs/pipeline`, { method: 'POST', body });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail ? JSON.stringify(data.detail) : res.statusText);
      }
      setJob(data as Job);
    } catch (e) {
      setBusy(false);
      setError(String(e));
    }
  };

  const healthPills = useMemo(() => {
    if (!health) return null;
    return (
      <div className="health">
        <span className={`pill ${health.rag?.ok ? '' : 'bad'}`}>
          RAG {health.rag?.ok ? 'ok' : 'down'}
        </span>
        <span className={`pill ${health.mineru?.ok ? '' : 'bad'}`}>
          MinerU {health.mineru?.ok ? 'ok' : 'missing'}
        </span>
        <span className={`pill ${health.deepread?.ok ? '' : 'bad'}`}>
          DeepRead {health.deepread?.ok ? 'ok' : 'missing'}
        </span>
        <span className={`pill ${health.ssh_configured ? '' : 'bad'}`}>
          SSH {health.ssh_configured ? 'set' : 'unset'}
        </span>
      </div>
    );
  }, [health]);

  const progress = Math.round(job?.progress ?? 0);

  return (
    <div className="app">
      <h1 className="brand">userbank-local</h1>
      <p className="lead">
        Laptop ingest: parse → embed on local RAG → HTTP/rsync to production. Knowledge = PDF/papers;
        Survey = Excel/Word/jsonl. Embeddings are computed here, not on the server.
      </p>

      <section className="panel">
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <strong>Control plane</strong>
          <button type="button" className="ghost" onClick={() => void refreshHealth()}>
            Refresh health
          </button>
        </div>
        <p className="muted" style={{ marginTop: '0.5rem' }}>
          API <code>{API}</code>
          {health?.api_url ? (
            <>
              {' '}
              · target <code>{health.api_url}</code>
            </>
          ) : null}
        </p>
        {healthPills}
      </section>

      <section className="panel">
        <div className="row">
          <label>
            Track{' '}
            <select
              value={track}
              onChange={(e) => {
                setTrack(e.target.value as Track);
                setFile(null);
              }}
            >
              <option value="knowledge">Knowledge (PDF / papers)</option>
              <option value="survey">Survey (Excel / Word / jsonl)</option>
            </select>
          </label>
        </div>

        <label
          className="drop"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            onDrop(e.dataTransfer.files);
          }}
        >
          <strong>{file ? file.name : dropHint}</strong>
          <span className="muted">or click to choose a file</span>
          <input
            type="file"
            accept={accept}
            style={{ display: 'none' }}
            onChange={(e) => onDrop(e.target.files)}
          />
        </label>

        <div className="row">
          <label>
            Org ID{' '}
            <input type="text" value={orgId} onChange={(e) => setOrgId(e.target.value)} />
          </label>
          <label>
            Upload mode{' '}
            <select value={mode} onChange={(e) => setMode(e.target.value)}>
              <option value="auto">auto</option>
              <option value="http">http</option>
              <option value="rsync">rsync</option>
            </select>
          </label>
          <label>
            <input type="checkbox" checked={upload} onChange={(e) => setUpload(e.target.checked)} />{' '}
            Upload after embed
          </label>
          {track === 'knowledge' ? (
            <label>
              <input
                type="checkbox"
                checked={skipMineru}
                onChange={(e) => setSkipMineru(e.target.checked)}
              />{' '}
              Skip MinerU
            </label>
          ) : null}
        </div>

        <div className="row">
          <button
            type="button"
            className="primary"
            disabled={busy || !file}
            onClick={() => void startPipeline()}
          >
            {busy ? 'Running…' : 'Parse → embed → upload'}
          </button>
        </div>
        {error ? <p className="error">{error}</p> : null}
      </section>

      {job ? (
        <section className="panel">
          <strong>
            Job {job.id.slice(0, 8)} · {job.kind} · {job.state}
            {job.phase ? ` · ${job.phase}` : ''}
          </strong>
          <div className="progress-wrap" aria-label="job progress">
            <div className="progress-bar" style={{ width: `${progress}%` }} />
          </div>
          <p className="muted">
            {progress}%{job.phase ? ` — ${job.phase}` : ''}
          </p>
          {job.error ? <p className="error">{job.error}</p> : null}
          {job.result ? (
            <pre className="muted" style={{ marginTop: '0.75rem' }}>
              {JSON.stringify(job.result, null, 2)}
            </pre>
          ) : null}
          <pre className="logs">{(job.logs ?? []).join('\n') || '…'}</pre>
        </section>
      ) : null}
    </div>
  );
}

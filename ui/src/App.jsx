import { useEffect, useMemo, useState } from "react";

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
  });
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { detail: text };
  }
  if (!res.ok) {
    throw new Error(data?.detail || res.statusText);
  }
  return data;
}

const NAV = [
  ["idea", "Idea"],
  ["board", "Board"],
  ["queue", "Queue"],
  ["jobs", "Jobs"],
  ["videos", "Videos"],
  ["spend", "Spend"],
];

export default function App() {
  const [page, setPage] = useState("idea");
  const [dash, setDash] = useState(null);
  const [error, setError] = useState("");
  const [idea, setIdea] = useState("");
  const [busy, setBusy] = useState(false);
  const [activeJob, setActiveJob] = useState(null);
  const [job, setJob] = useState(null);

  async function refresh() {
    try {
      setDash(await api("/api/dashboard"));
      setError("");
    } catch (err) {
      setError(String(err.message || err));
    }
  }

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 4000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!activeJob) return undefined;
    let alive = true;
    async function poll() {
      try {
        const next = await api(`/api/jobs/${activeJob}`);
        if (alive) setJob(next);
        if (next.status !== "running") refresh();
      } catch (err) {
        if (alive) setError(String(err.message || err));
      }
    }
    poll();
    const timer = setInterval(poll, 2000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [activeJob]);

  const running = useMemo(
    () => (dash?.jobs || []).filter((item) => item.status === "running"),
    [dash],
  );

  async function submitIdea({ surprise = false, produce = true } = {}) {
    if (!surprise && idea.trim().length < 8) {
      setError("Give Astra a real thought — one sentence is enough.");
      return;
    }
    if (produce && !window.confirm("This spends about 540 Runway credits (~$5.40) plus Astra and ElevenLabs. Make the video?")) {
      return;
    }
    setBusy(true);
    setError("");
    try {
      const result = await api("/api/ideas", {
        method: "POST",
        body: JSON.stringify({ idea, surprise, produce }),
      });
      if (result.job?.id) {
        setActiveJob(result.job.id);
        setPage("jobs");
      }
      await refresh();
    } catch (err) {
      setError(String(err.message || err));
    } finally {
      setBusy(false);
    }
  }

  async function produceId(contentId) {
    if (!window.confirm(`Produce ${contentId}? About 540 Runway credits.`)) return;
    setBusy(true);
    try {
      const result = await api("/api/produce", {
        method: "POST",
        body: JSON.stringify({ content_id: contentId }),
      });
      if (result.job?.id) {
        setActiveJob(result.job.id);
        setPage("jobs");
      }
      await refresh();
    } catch (err) {
      setError(String(err.message || err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="shell">
      <header className="top">
        <div>
          <p className="eyebrow">Somehow True</p>
          <h1>Studio</h1>
        </div>
        <p className="tagline">Facts that sound made up. Checked before we tell them.</p>
      </header>
      <nav>
        {NAV.map(([id, label]) => (
          <button
            key={id}
            className={page === id ? "on" : ""}
            onClick={() => setPage(id)}
            type="button"
          >
            {label}
            {id === "jobs" && running.length ? <span className="dot">{running.length}</span> : null}
          </button>
        ))}
      </nav>
      {error ? <p className="banner">{error}</p> : null}

      {page === "idea" && (
        <section className="hero">
          <h2>I thought of something</h2>
          <p>
            Type a messy thought. Astra hunts the most interesting true cut, writes the script,
            then Runway builds the short.
          </p>
          <textarea
            value={idea}
            onChange={(e) => setIdea(e.target.value)}
            placeholder="A town inside another country, an animal that should not exist, a spacecraft still going…"
            rows={6}
          />
          <div className="row">
            <button className="primary" disabled={busy} onClick={() => submitIdea()} type="button">
              {busy ? "Working…" : "Make the video"}
            </button>
            <button disabled={busy} onClick={() => submitIdea({ surprise: true })} type="button">
              Surprise me
            </button>
            <button disabled={busy} onClick={() => submitIdea({ produce: false })} type="button">
              Queue only
            </button>
          </div>
          <p className="hint">Full short ≈ 540 Runway credits / $5.40. Uploads private with the AI label.</p>
        </section>
      )}

      {page === "board" && dash && (
        <section className="grid">
          <Stat label="In queue" value={dash.queue.ready} />
          <Stat label="Produced" value={dash.queue.produced} />
          <Stat label="Runway credits" value={Math.round(dash.spend.runway_credits || 0)} />
          <Stat label="API spend" value={`$${(dash.spend.usd || 0).toFixed(2)}`} />
          <div className="panel span">
            <h3>Latest videos</h3>
            <VideoList videos={dash.videos} />
          </div>
        </section>
      )}

      {page === "queue" && dash && (
        <section className="panel">
          <h3>Content queue</h3>
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Topic</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {dash.queue.rows.map((row) => (
                <tr key={row.id}>
                  <td>{row.id}</td>
                  <td>{row.hook || row.topic}</td>
                  <td>{row.produced ? "done" : row.status}</td>
                  <td>
                    {row.produced ? null : (
                      <button disabled={busy} onClick={() => produceId(row.id)} type="button">
                        Produce
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {page === "jobs" && (
        <section className="split">
          <div className="panel">
            <h3>Jobs</h3>
            <ul className="jobs">
              {(dash?.jobs || []).map((item) => (
                <li key={item.id}>
                  <button
                    className={activeJob === item.id ? "on" : ""}
                    onClick={() => setActiveJob(item.id)}
                    type="button"
                  >
                    <strong>{item.title}</strong>
                    <span>{item.status}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
          <div className="panel log">
            <h3>{job?.title || "Log"}</h3>
            <pre>{job?.log || "Pick a job."}</pre>
          </div>
        </section>
      )}

      {page === "videos" && dash && (
        <section className="panel">
          <h3>Videos</h3>
          <VideoList videos={dash.videos} />
        </section>
      )}

      {page === "spend" && dash && (
        <section className="panel">
          <h3>API spend</h3>
          <p>Total ${dash.spend.usd?.toFixed(4)} · {dash.spend.runway_credits} Runway credits</p>
          <ul>
            {Object.entries(dash.spend.by_provider || {}).map(([name, val]) => (
              <li key={name}>
                {name}: ${val.usd.toFixed(4)}
                {val.credits ? ` · ${val.credits} credits` : ""} · {val.calls} calls
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function Stat({ label, value }) {
  return (
    <div className="stat">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function VideoList({ videos }) {
  if (!videos?.length) return <p className="hint">Nothing rendered yet.</p>;
  return (
    <ul className="videos">
      {videos.map((video) => (
        <li key={video.id}>
          <strong>{video.title}</strong>
          <span>{video.id}</span>
          {video.youtube ? (
            <a href={video.youtube} target="_blank" rel="noreferrer">
              Open in Studio
            </a>
          ) : (
            <span>local only</span>
          )}
        </li>
      ))}
    </ul>
  );
}

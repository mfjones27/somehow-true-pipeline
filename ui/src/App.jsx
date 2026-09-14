import { useEffect, useMemo, useState } from "react";
import logo from "./logo.png";

async function api(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  if (opts.body && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  const res = await fetch(path, { ...opts, headers });
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
  const [toast, setToast] = useState("");
  const [idea, setIdea] = useState("");
  const [busy, setBusy] = useState(false);
  const [activeJob, setActiveJob] = useState(null);
  const [job, setJob] = useState(null);
  const [confirm, setConfirm] = useState(null);

  async function refresh() {
    try {
      setDash(await api("/api/dashboard"));
      setError("");
    } catch (err) {
      const message = String(err.message || err);
      setError(
        message === "Failed to fetch"
          ? "Studio backend is not running. Close this window and open Somehow True again."
          : message,
      );
    }
  }

  useEffect(() => {
    let alive = true;
    async function boot() {
      for (let i = 0; i < 8; i += 1) {
        try {
          const data = await api("/api/dashboard");
          if (!alive) return;
          setDash(data);
          setError("");
          return;
        } catch (err) {
          if (i === 7 && alive) {
            setError("Studio backend is not running. Close this window and open Somehow True again.");
          } else {
            await new Promise((resolve) => setTimeout(resolve, 250));
          }
        }
      }
    }
    boot();
    const timer = setInterval(refresh, 4000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
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

  useEffect(() => {
    if (!toast) return undefined;
    const timer = setTimeout(() => setToast(""), 2200);
    return () => clearTimeout(timer);
  }, [toast]);

  const running = useMemo(
    () => (dash?.jobs || []).filter((item) => item.status === "running"),
    [dash],
  );

  function ask(message, onYes) {
    setConfirm({ message, onYes });
  }

  async function submitIdea({ surprise = false, produce = true } = {}) {
    if (!surprise && idea.trim().length < 8) {
      setError("Give Astra a real thought — one sentence is enough.");
      return;
    }
    const go = async () => {
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
        } else {
          setPage("queue");
        }
        await refresh();
      } catch (err) {
        setError(String(err.message || err));
      } finally {
        setBusy(false);
      }
    };
    if (produce) {
      ask("This spends about 540 Runway credits (~$5.40) plus Astra and ElevenLabs. Make the video?", go);
      return;
    }
    await go();
  }

  async function submitCliplytics({ produce = true } = {}) {
    const next = dash?.cliplytics?.next;
    const go = async () => {
      setBusy(true);
      setError("");
      try {
        const result = await api("/api/cliplytics", {
          method: "POST",
          body: JSON.stringify({ produce }),
        });
        if (result.job?.id) {
          setActiveJob(result.job.id);
          setPage("jobs");
        } else {
          setPage("queue");
        }
        await refresh();
      } catch (err) {
        setError(String(err.message || err));
      } finally {
        setBusy(false);
      }
    };
    if (produce) {
      const topic = next?.hook || next?.topic || "the next unused Cliplytics topic";
      ask(
        `Import “${topic}” from Cliplytics and make the video? Astra will source a script — viral claims are not used as narration. About 540 Runway credits (~$5.40).`,
        go,
      );
      return;
    }
    await go();
  }

  async function produceId(contentId, { continueWork = false, skipCaptions = false } = {}) {
    const message = continueWork
      ? `Finish ${contentId} from clips already on disk? No new Runway generation unless a fill clip is needed.`
      : `Produce ${contentId}? About 540 Runway credits.`;
    ask(message, async () => {
      setBusy(true);
      try {
        const result = await api("/api/produce", {
          method: "POST",
          body: JSON.stringify({
            content_id: contentId,
            skip_runway: continueWork,
            skip_captions: continueWork && skipCaptions,
          }),
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
    });
  }

  async function copyText(text) {
    if (!text) return;
    try {
      await api("/api/copy", { method: "POST", body: JSON.stringify({ text }) });
      setToast("Copied");
      return;
    } catch {
      /* native clipboard below */
    }
    try {
      await navigator.clipboard.writeText(text);
      setToast("Copied");
      return;
    } catch {
      const field = document.createElement("textarea");
      field.value = text;
      field.setAttribute("readonly", "");
      field.style.position = "fixed";
      field.style.left = "-9999px";
      document.body.appendChild(field);
      field.select();
      const ok = document.execCommand("copy");
      field.remove();
      if (ok) setToast("Copied");
      else setError("Could not copy. Click the link and press Ctrl+C.");
    }
  }

  async function openUrl(url) {
    if (!url) return;
    try {
      await api("/api/open", { method: "POST", body: JSON.stringify({ url }) });
    } catch (err) {
      setError(String(err.message || err));
    }
  }

  const title = NAV.find(([id]) => id === page)?.[1] || "Studio";

  return (
    <div className="app">
      <header className="chrome">
        <div className="brand">
          <img src={logo} alt="Somehow True" width="40" height="40" />
          <div>
            <p className="eyebrow">Somehow True</p>
            <strong>Studio</strong>
          </div>
        </div>
        <nav className="tabs" aria-label="Studio">
          {NAV.map(([id, label]) => (
            <button
              key={id}
              className={page === id ? "on" : ""}
              onClick={() => setPage(id)}
              type="button"
            >
              {label}
              {id === "jobs" && running.length ? <em>{running.length}</em> : null}
            </button>
          ))}
        </nav>
        <div className="chrome-meta">
          {running.length ? <span className="live">{running.length} running</span> : <span className="idle">Idle</span>}
          <p>{dash?.youtube_ready ? "YouTube ready" : "YouTube not signed in"}</p>
        </div>
      </header>

      <main>
        <header className="top">
          <div>
            <p className="kicker">{page}</p>
            <h1>{title}</h1>
          </div>
          <p className="spend-chip">${(dash?.spend?.usd || 0).toFixed(2)} spent</p>
        </header>

        {error ? <p className="banner">{error}</p> : null}

        {page === "idea" && (
          <section className="hero">
            <h2>Give Astra something worth hunting.</h2>
            <p>
              A messy thought is enough. Astra has to find the cut that would actually get views —
              a named instance, a number, a cause. About one in five surprises comes back as a Top 5.
            </p>
            <textarea
              value={idea}
              onChange={(e) => setIdea(e.target.value)}
              placeholder="A town that is legally in the wrong country, an animal whose body should not work, a machine that has been running since 1927…"
              rows={7}
            />
            <div className="row">
              <button className="primary" disabled={busy} onClick={() => submitIdea()} type="button">
                {busy ? "Working…" : "Make the video"}
              </button>
              <button disabled={busy} onClick={() => submitIdea({ surprise: true })} type="button">
                Surprise me
              </button>
              <button className="ghost" disabled={busy} onClick={() => submitIdea({ produce: false })} type="button">
                Queue only
              </button>
            </div>
            <p className="hint">Full short ≈ 540 Runway credits / $5.40. Uploads private with the AI label.</p>
          </section>
        )}

        {page === "idea" && (
          <section className="hero cliplytics-hero">
            <h2>Or pull a viral Cliplytics topic.</h2>
            <p>
              One click reads the next unused remix from your local Cliplytics folder,
              then Astra hunts a sourced Somehow True angle and produces the short.
            </p>
            {dash?.cliplytics?.next ? (
              <div className="topic-preview">
                <p className="kicker">Next unused</p>
                <strong>{dash.cliplytics.next.hook || dash.cliplytics.next.topic}</strong>
                <p className="hint">
                  {dash.cliplytics.next.author ? `@${dash.cliplytics.next.author}` : "Cliplytics"}
                  {dash.cliplytics.next.views != null ? ` · ${Number(dash.cliplytics.next.views).toLocaleString()} views` : ""}
                  {` · ${dash.cliplytics.unused} unused`}
                </p>
              </div>
            ) : (
              <p className="hint">
                {dash?.cliplytics?.error
                  || "Looking for Cliplytics…"}
                {dash?.cliplytics?.dir ? ` (${dash.cliplytics.dir})` : ""}
              </p>
            )}
            <div className="row">
              <button
                className="primary"
                disabled={busy || !dash?.cliplytics?.next}
                onClick={() => submitCliplytics()}
                type="button"
              >
                {busy ? "Working…" : "Make video from Cliplytics"}
              </button>
              <button
                className="ghost"
                disabled={busy || !dash?.cliplytics?.next}
                onClick={() => submitCliplytics({ produce: false })}
                type="button"
              >
                Queue topic only
              </button>
            </div>
          </section>
        )}

        {page === "board" && dash && (
          <section className="stack">
            <div className="grid">
              <Stat label="In queue" value={dash.queue.ready} />
              <Stat label="Failed" value={dash.queue.failed} />
              <Stat label="Runway credits" value={Math.round(dash.spend.runway_credits || 0)} />
              <Stat label="API spend" value={`$${(dash.spend.usd || 0).toFixed(2)}`} />
            </div>
            <div className="panel">
              <h3>Local work</h3>
              <p className="hint">Drafts and failed jobs stay here. Posted YouTube videos live on Videos.</p>
              <ProjectList
                projects={dash.projects}
                busy={busy}
                onContinue={(item) => produceId(item.id, { continueWork: true, skipCaptions: item.has_captions })}
              />
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
                    <td className="mono">{row.id}</td>
                    <td>{row.hook || row.topic}</td>
                    <td>
                      <span className={`pill ${row.produced ? "done" : row.failed ? "failed" : ""}`}>
                        {row.produced ? "done" : row.failed ? "failed" : row.status}
                      </span>
                      {row.has_clips ? <span className="pill">{row.clips} clips</span> : null}
                    </td>
                    <td>
                      {row.produced ? null : row.can_continue ? (
                        <button
                          className="primary"
                          disabled={busy}
                          onClick={() => produceId(row.id, { continueWork: true, skipCaptions: row.has_captions })}
                          type="button"
                        >
                          Continue
                        </button>
                      ) : (
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
                      <span className={`pill ${item.status}`}>{item.status}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
            <div className="panel log">
              <h3>{job?.title || "Log"}</h3>
              {(job?.youtube || job?.watch) && (
                <LinkBar
                  studio={job.youtube}
                  watch={job.watch}
                  onCopy={copyText}
                  onOpen={openUrl}
                />
              )}
              <pre>{job?.log || "Pick a job."}</pre>
            </div>
          </section>
        )}

        {page === "videos" && dash && (
          <section className="panel">
            <h3>On YouTube</h3>
            <p className="hint">Live from the channel. Deleted videos disappear here after refresh.</p>
            <VideoList videos={dash.videos} onCopy={copyText} onOpen={openUrl} />
          </section>
        )}

        {page === "spend" && dash && (
          <section className="panel">
            <h3>API spend</h3>
            <p className="lede">
              Total ${(dash.spend.usd || 0).toFixed(4)} · {dash.spend.runway_credits} Runway credits
            </p>
            <ul className="spend">
              {Object.entries(dash.spend.by_provider || {}).map(([name, val]) => (
                <li key={name}>
                  <strong>{name}</strong>
                  <span>
                    ${val.usd.toFixed(4)}
                    {val.credits ? ` · ${val.credits} credits` : ""} · {val.calls} calls
                  </span>
                </li>
              ))}
            </ul>
          </section>
        )}
      </main>

      {toast ? <p className="toast">{toast}</p> : null}
      {confirm ? (
        <div className="modal-back" onClick={() => setConfirm(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <p>{confirm.message}</p>
            <div className="row">
              <button
                className="primary"
                type="button"
                onClick={() => {
                  const go = confirm.onYes;
                  setConfirm(null);
                  go();
                }}
              >
                Do it
              </button>
              <button type="button" onClick={() => setConfirm(null)}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      ) : null}
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

function LinkBar({ studio, watch, onCopy, onOpen }) {
  const url = studio || watch;
  if (!url) return null;
  return (
    <div className="linkbar">
      <input
        className="url"
        readOnly
        value={url}
        onFocus={(e) => e.target.select()}
        onClick={(e) => e.target.select()}
      />
      <button type="button" onClick={() => onCopy(url)}>
        Copy
      </button>
      {studio ? (
        <button className="primary" type="button" onClick={() => onOpen(studio)}>
          Open Studio
        </button>
      ) : null}
      {watch ? (
        <button type="button" onClick={() => onOpen(watch)}>
          Watch
        </button>
      ) : null}
    </div>
  );
}

function ProjectList({ projects, busy, onContinue }) {
  if (!projects?.length) return <p className="hint">Nothing on disk yet.</p>;
  return (
    <ul className="videos">
      {projects.map((item) => (
        <li key={item.id}>
          <div className="video-head">
            <strong>{item.title || item.id}</strong>
            <span className="mono">{item.id}</span>
          </div>
          <div className="row">
            <span className={`pill ${item.stage === "failed" ? "failed" : item.stage === "produced" ? "done" : ""}`}>
              {item.stage}
            </span>
            {item.has_clips ? <span className="pill">{item.clips} clips</span> : null}
            {item.can_continue && item.stage !== "produced" ? (
              <button className="primary" disabled={busy} type="button" onClick={() => onContinue(item)}>
                Continue
              </button>
            ) : null}
          </div>
        </li>
      ))}
    </ul>
  );
}

function VideoList({ videos, onCopy, onOpen }) {
  if (!videos?.length) return <p className="hint">No videos currently on the YouTube channel.</p>;
  return (
    <ul className="videos">
      {videos.map((video) => (
        <li key={video.id}>
          <div className="video-head">
            <strong>{video.title}</strong>
            <span className={`pill privacy-${video.privacy || "private"}`}>{video.privacy || "private"}</span>
          </div>
          <LinkBar
            studio={video.studio || video.youtube}
            watch={video.watch}
            onCopy={onCopy}
            onOpen={onOpen}
          />
        </li>
      ))}
    </ul>
  );
}

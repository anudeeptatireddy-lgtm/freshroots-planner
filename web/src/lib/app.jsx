import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, toBase64 } from "./api";

const Ctx = createContext(null);
export const useApp = () => useContext(Ctx);

const stored = (k) => { try { return localStorage.getItem(k) || ""; } catch { return ""; } };
const store = (k, v) => { try { localStorage.setItem(k, v); } catch { /* private mode */ } };

export function AppProvider({ children }) {
  const [runs, setRuns] = useState([]);
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [flash, setFlash] = useState("");
  const [reviewer, setReviewerState] = useState(() => stored("fr_reviewer"));

  const setReviewer = (v) => { setReviewerState(v); store("fr_reviewer", v); };
  const needName = () => {
    if (reviewer.trim()) return false;
    setError("Type your name at the top first, so the log shows who decided.");
    return true;
  };
  const say = (msg) => { setFlash(msg); setTimeout(() => setFlash(""), 3500); };

  const act = useCallback(async (fn, ok) => {
    setBusy(true); setError("");
    try {
      const r = await fn();
      if (r) { setData(r); if (ok) say(typeof ok === "function" ? ok(r) : ok); }
      return r;
    } catch (e) { setError(e.message); return null; } finally { setBusy(false); }
  }, []);

  const refreshRuns = async () => setRuns((await api.runs()).runs);
  const openRun = (id) => act(() => api.run(id));

  useEffect(() => {
    (async () => {
      try {
        const { runs: ids } = await api.runs();
        setRuns(ids);
        if (ids.length) setData(await api.run(ids[0]));
      } catch (e) { setError(e.message); } finally { setBusy(false); }
    })();
  }, []);

  const value = useMemo(() => ({
    runs, data, busy, error, flash, reviewer, setReviewer, openRun, clearError: () => setError(""),
    decide: (changes, msg) => (needName() ? null : act(() => api.decide(data.id, reviewer, changes), msg || "Saved.")),
    generate: () => (needName() ? null : act(() => api.generate(data.id, reviewer), "Purchase orders are ready.")),
    zoho: (mode, confirm) => act(() => api.zoho(data.id, mode, confirm), mode === "send" ? "Sent to Zoho as drafts." : "Preview ready. Nothing was sent."),
    plan: async (files) => {
      const payload = Object.fromEntries(await Promise.all(files.map(async (f) => [f.name, await toBase64(f)])));
      const r = await act(() => api.plan(payload), (d) => `New run ${d.id} planned.`);
      if (r) refreshRuns();
      return r;
    },
  }), [runs, data, busy, error, flash, reviewer, act]); // eslint-disable-line react-hooks/exhaustive-deps

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

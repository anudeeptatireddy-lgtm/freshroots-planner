const call = async (op, { method = "GET", params = {}, body } = {}) => {
  const qs = new URLSearchParams({ op, ...params }).toString();
  const res = await fetch(`/api/index?${qs}`, { method, headers: body ? { "content-type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
};

export const api = {
  runs: () => call("runs"),
  run: (id) => call("run", { params: { id } }),
  decide: (run, reviewer, changes, bundle) => call("decide", { method: "POST", body: { run, reviewer, changes, bundle } }),
  plan: (files) => call("plan", { method: "POST", body: { files } }),
  generate: (run, reviewer, bundle) => call("generate", { method: "POST", body: { run, reviewer, bundle } }),
  zoho: (run, mode, confirm = false, bundle) => call("zoho", { method: "POST", body: { run, mode, confirm, bundle } }),
  fileUrl: (run, name) => `/api/index?op=file&run=${encodeURIComponent(run)}&name=${encodeURIComponent(name)}`,
};

export const toBase64 = (file) =>
  new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).split(",")[1]);
    r.onerror = reject;
    r.readAsDataURL(file);
  });

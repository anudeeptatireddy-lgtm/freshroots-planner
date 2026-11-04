import { api } from "../lib/api";
import { TIPS } from "../lib/glossary";

export const Tip = ({ k, text }) => (
  <span className="tip" tabIndex={0} role="note" data-tip={text || TIPS[k]} aria-label={text || TIPS[k]}>?</span>
);

const BAD = new Set(["URGENT", "BELOW_MIN_AFTER_ORDER", "SHARP_DROP", "DATA_ISSUE"]);
/** Codes stay visible as badge text. Colour is never the only signal: the text and the tooltip carry the meaning too. */
export const Chip = ({ code }) => (
  <span className={`chip ${BAD.has(code) ? "chip-bad" : "chip-" + code}`}>{code}{TIPS[code] && <Tip k={code} />}</span>
);

const MIME = { pdf: "application/pdf", csv: "text/csv", md: "text/markdown", json: "application/json" };
/** With a database the file comes from the API; without one the browser already holds it (the run's bundle). */
export const Download = ({ d, name, children, primary }) => {
  const b64 = d.bundle?.[name];
  const href = b64 ? `data:${MIME[name.split(".").pop()] || "application/octet-stream"};base64,${b64}` : api.fileUrl(d.id, name);
  return <a className={`btn ${primary ? "btn-primary" : "btn-soft"}`} href={href} download={name}>{children}</a>;
};


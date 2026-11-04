import { TIPS } from "../lib/glossary";

export const Tip = ({ k, text }) => (
  <span className="tip" tabIndex={0} role="note" data-tip={text || TIPS[k]} aria-label={text || TIPS[k]}>?</span>
);

const BAD = new Set(["URGENT", "BELOW_MIN_AFTER_ORDER", "SHARP_DROP", "DATA_ISSUE"]);
/** Codes stay visible as badge text. Colour is never the only signal: the text and the tooltip carry the meaning too. */
export const Chip = ({ code }) => (
  <span className={`chip ${BAD.has(code) ? "chip-bad" : "chip-" + code}`}>{code}{TIPS[code] && <Tip k={code} />}</span>
);

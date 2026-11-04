import { TIPS, label } from "../lib/glossary";

export const Tip = ({ k, text }) => (
  <span className="tip" tabIndex={0} role="note" data-tip={text || TIPS[k]} aria-label={text || TIPS[k]}>?</span>
);

export const Chip = ({ code, tone }) => (
  <span className={`chip chip-${tone || code}`}>{label(code)}{TIPS[code] && <Tip k={code} />}</span>
);

/** Weeks of cover on a 0-16 week scale: filled = now, ghost = after the order, band = the safe min-max range. */
export const CoverBar = ({ now, after, min, max, scale = 16 }) => {
  const pct = (v) => `${Math.min(100, (v / scale) * 100)}%`;
  return (
    <div className="cover" aria-label={`Cover ${now?.toFixed?.(1)} weeks, ${after?.toFixed?.(1)} after order, safe range ${min} to ${max}`}>
      <div className="cover-band" style={{ left: pct(min), width: `calc(${pct(max)} - ${pct(min)})` }} />
      {after > now && <div className="cover-after" style={{ width: pct(after) }} />}
      <div className="cover-now" style={{ width: pct(now) }} />
    </div>
  );
};
